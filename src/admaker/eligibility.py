"""Adult professional-use self-attestation; deliberately stores no birth date or ID."""
import os

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from admaker.auth import Subject, authenticated_subject

POLICY_VERSION = "adult-business-2026-09-09-v1"
POLICY_TEXT = "I am 18 or older and will use Addy AI for professional or business purposes."
router = APIRouter()


def eligibility_status(account_id):
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        row = connection.execute(
            "SELECT policy_version,confirmed_at FROM app.account_eligibility WHERE account_id=%s", (account_id,),
        ).fetchone()
    return {"confirmed": bool(row and row[0] == POLICY_VERSION), "policyVersion": POLICY_VERSION,
            "statement": POLICY_TEXT, "confirmedAt": row[1].isoformat() if row and row[0] == POLICY_VERSION else None}


def require_eligibility(account_id):
    if not eligibility_status(account_id)["confirmed"]:
        raise HTTPException(403, "Confirm that you are 18 or older in Account → Age eligibility before starting new work.")


class EligibilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    over_18: StrictBool = Field(alias="over18")
    business_use: StrictBool = Field(alias="businessUse")
    policy_version: str = Field(alias="policyVersion", max_length=100)


@router.get("/v1/account/eligibility")
def get_eligibility(subject: Subject = Depends(authenticated_subject)):
    return eligibility_status(subject.id)


@router.post("/v1/account/eligibility")
def confirm_eligibility(payload: EligibilityRequest, subject: Subject = Depends(authenticated_subject)):
    if not payload.over_18 or not payload.business_use:
        raise HTTPException(403, "Addy AI is for adults 18 or older using it for professional or business purposes.")
    if payload.policy_version != POLICY_VERSION:
        raise HTTPException(409, "The eligibility statement has changed. Reload it before confirming.")
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("INSERT INTO app.accounts(id,email) VALUES (%s,%s) ON CONFLICT(id) DO NOTHING", (subject.id, subject.email))
        connection.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (subject.id,))
        connection.execute(
            "INSERT INTO app.account_eligibility(account_id,policy_version) VALUES (%s,%s) "
            "ON CONFLICT(account_id) DO UPDATE SET policy_version=EXCLUDED.policy_version,confirmed_at=now() "
            "WHERE app.account_eligibility.policy_version<>EXCLUDED.policy_version", (subject.id, POLICY_VERSION),
        )
    return eligibility_status(subject.id)
