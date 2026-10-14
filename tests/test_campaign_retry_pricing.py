from admaker.eligibility import POLICY_VERSION
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.types.json import Jsonb

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.consent import DISCLOSURE_VERSION
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("action", ["spend_more", "regen"])
def test_pack_retry_requires_full_price_and_uses_provider_queue(queued_job, monkeypatch, action):
    account, job, reservation, queue = queued_job
    for name, value in {"DATABASE_URL": URL, "ENABLE_CAMPAIGN_PACKS": "true", "CAMPAIGN_PACK_CREDITS": "4", "CAMPAIGN_PACK_QUEUE": queue}.items():
        monkeypatch.setenv(name, value)
    with psycopg.connect(URL) as c:
        version = c.execute("UPDATE app.jobs SET state=%s,settings=%s WHERE id=%s RETURNING version", ("delivered" if action == "regen" else "awaiting_user_decision", Jsonb({"generationKind": "campaign_pack", "priceSnapshot": {"credits": 3}}), job)).fetchone()[0]
        if action == "regen":
            c.execute("UPDATE app.credit_reservations SET state='released' WHERE id=%s", (reservation,))
        c.execute("INSERT INTO app.credit_ledger(account_id,delta,event_key) VALUES (%s,10,%s)", (account, str(uuid.uuid4())))
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "test@example.com")
    try:
        with TestClient(app) as client:
            path = f"/v1/jobs/{job}/{'regen' if action == 'regen' else 'decision'}"
            body = {"expectedVersion": version, **({"action": action} if action != "regen" else {})}
            headers = {"Idempotency-Key": "retry"}
            assert client.post(path, json=body, headers=headers).status_code == 409
            assert client.post(path, json={**body, "confirmedCredits": 1}, headers=headers).status_code == 409
            assert client.post(path, json={**body, "confirmedCredits": 3}, headers=headers).status_code == 403
            with psycopg.connect(URL) as c:
                c.execute("INSERT INTO app.account_eligibility(account_id,policy_version) VALUES (%s,%s)", (account, POLICY_VERSION))
                c.execute("INSERT INTO app.ai_consent(account_id,disclosure_version,granted) VALUES (%s,%s,true)", (account, DISCLOSURE_VERSION))
            first = client.post(path, json={**body, "confirmedCredits": 3}, headers=headers)
            assert first.status_code == 202
            monkeypatch.setenv("ENABLE_CAMPAIGN_PACKS", "false")
            assert client.post(path, json={**body, "confirmedCredits": 3}, headers=headers).json() == first.json()
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT amount FROM app.credit_reservations WHERE job_id=%s AND state='held'", (job,)).fetchall() == [(3,)]
            assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("released",)
            assert c.execute(sql.SQL("SELECT count(*) FROM pgmq.{}").format(sql.Identifier("q_" + queue))).fetchone() == (2,)
            assert c.execute("SELECT sum(delta) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (10,)
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.ai_consent WHERE account_id=%s", (account,))
            c.execute("DELETE FROM app.command_keys WHERE account_id=%s", (account,))
