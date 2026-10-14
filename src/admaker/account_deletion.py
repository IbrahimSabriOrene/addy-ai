"""Account deletion admission and access tombstone; cleanup is a separate phase."""
import os
import uuid

import psycopg
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from typing import Literal

router = APIRouter()


def deletion_requested(account_id):
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        return connection.execute("SELECT 1 FROM app.account_deletions WHERE account_id=%s", (uuid.UUID(str(account_id)),)).fetchone() is not None


def request_account_deletion(connection, account_id):
    account_id = uuid.UUID(str(account_id))
    # Match account -> job -> run lock order used by credit settlement.
    account = connection.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (account_id,)).fetchone()
    prior = connection.execute("SELECT state FROM app.account_deletions WHERE account_id=%s", (account_id,)).fetchone()
    if prior:
        return {"state": prior[0]}
    if not account:
        raise LookupError("Account not found")
    connection.execute("INSERT INTO app.account_deletions(account_id) VALUES (%s)", (account_id,))
    connection.execute("UPDATE app.ai_consent SET granted=false WHERE account_id=%s", (account_id,))
    connection.execute("SELECT id FROM app.jobs WHERE owner_id=%s ORDER BY id FOR UPDATE", (account_id,)).fetchall()
    connection.execute("UPDATE app.job_runs SET fence=fence+1,state='aborted',lease_until=NULL,next_work_at=NULL WHERE job_id IN (SELECT id FROM app.jobs WHERE owner_id=%s) AND state IN ('running','awaiting_user_decision','review_required')", (account_id,))
    connection.execute("UPDATE app.job_attempts SET state='failed',completed_at=clock_timestamp() WHERE state='running' AND run_id IN (SELECT r.id FROM app.job_runs r JOIN app.jobs j ON j.id=r.job_id WHERE j.owner_id=%s)", (account_id,))
    connection.execute("UPDATE app.credit_reservations SET state='released' WHERE account_id=%s AND state='held'", (account_id,))
    connection.execute("UPDATE app.jobs SET state='aborted' WHERE owner_id=%s AND state IN ('submitted','running','awaiting_user_decision','failed')", (account_id,))
    return {"state": "requested"}


class DeleteAccountRequest(BaseModel):
    confirmation: Literal["DELETE"]


@router.post("/v1/account/deletion", status_code=202)
def delete_account_request(payload: DeleteAccountRequest, authorization: str | None = Header(default=None)):
    from admaker.auth import verify_access_token
    from admaker.api import _connection

    # Verify identity directly so a lost deletion response can be replayed after access is blocked.
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    subject = verify_access_token(authorization.removeprefix("Bearer "))
    with _connection() as connection:
        try:
            return request_account_deletion(connection, subject.id)
        except LookupError:
            raise HTTPException(404, "Account not found") from None
