import uuid

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject
from admaker.consent import DISCLOSURE_VERSION, require_ai_consent
from admaker.eligibility import POLICY_VERSION
from test_worker_leases import URL, queued_job


def test_age_boundary_is_owned_explicit_versioned_and_does_not_grant_ai_consent(queued_job, monkeypatch):
    owner = queued_job[0]
    other = uuid.uuid4()
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setattr("admaker.auth.verify_access_token", lambda token: Subject(str(owner if token == "owner" else other), "adult@example.test"))
    monkeypatch.setattr("admaker.rate_limit.enforce_account_rate_limit", lambda account: None)
    headers = {"Authorization": "Bearer owner"}
    body = {"over18": True, "businessUse": True, "policyVersion": POLICY_VERSION}
    try:
        with TestClient(app) as client:
            assert client.get("/v1/account/eligibility").status_code == 401
            assert client.get("/v1/account/eligibility", headers=headers).json()["confirmed"] is False
            assert client.post("/v1/uploads/presign", headers=headers, json={}).status_code == 403
            assert client.post("/v1/jobs", headers=headers, json={}).status_code == 403
            for change, code in [({"over18": False}, 403), ({"businessUse": False}, 403), ({"over18": "true"}, 422), ({"policyVersion": "old"}, 409), ({"accountId": str(other)}, 422)]:
                assert client.post("/v1/account/eligibility", headers=headers, json={**body, **change}).status_code == code
            # Withdrawal remains possible without an age confirmation.
            assert client.put("/v1/account/ai-consent", headers=headers, json={"granted": False, "disclosureVersion": "old"}).status_code == 200
            first = client.post("/v1/account/eligibility", headers=headers, json=body)
            assert first.status_code == 200 and first.json()["confirmed"] is True
            assert client.post("/v1/account/eligibility", headers=headers, json=body).json() == first.json()
            assert client.get("/v1/account/eligibility", headers={"Authorization": "Bearer other"}).json()["confirmed"] is False
            assert client.get("/v1/account/ai-consent", headers=headers).json()["granted"] is False
            with pytest.raises(PermissionError):
                require_ai_consent(str(owner))
            assert client.put("/v1/account/ai-consent", headers=headers, json={"granted": True, "disclosureVersion": DISCLOSURE_VERSION}).status_code == 200
            require_ai_consent(str(owner))
            with psycopg.connect(URL) as c:
                c.execute("UPDATE app.account_eligibility SET policy_version='old' WHERE account_id=%s", (owner,))
            with pytest.raises(PermissionError):
                require_ai_consent(str(owner))
            assert client.post("/v1/jobs", headers=headers, json={}).status_code == 403
            # Reporting reaches its own validation, rather than the adult gate.
            assert client.post(f"/v1/jobs/{queued_job[1]}/reports", headers=headers, json={}).status_code == 422
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.ai_consent WHERE account_id=%s", (owner,))
