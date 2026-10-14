import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.consent import DISCLOSURE_VERSION, require_ai_consent
from admaker.db import migrate
from admaker.eligibility import POLICY_VERSION
from admaker.veo import VeoRequest, VeoService


def test_consent_refusal_and_withdrawal_block_direct_submission(monkeypatch):
    url = "postgresql://postgres:postgres@localhost:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.delenv("DEV_SEED_CREDITS", raising=False)
    migrate()
    owner = Subject(str(uuid.uuid4()), "consent@example.com")
    app.dependency_overrides[authenticated_subject] = lambda: owner
    service = object.__new__(VeoService)  # No SDK client: reaching it would fail this check.
    try:
        with TestClient(app) as client:
            assert client.get("/v1/account/ai-consent").json()["granted"] is False
            with pytest.raises(PermissionError):
                service.submit(VeoRequest("private prompt"), account_id=owner.id)
            assert client.put("/v1/account/ai-consent", json={"granted": True, "disclosureVersion": "old"}).status_code == 409
            assert client.put("/v1/account/ai-consent", json={"granted": True, "disclosureVersion": DISCLOSURE_VERSION}).status_code == 403
            assert client.post("/v1/account/eligibility", json={"over18": True, "businessUse": True, "policyVersion": POLICY_VERSION}).status_code == 200
            assert client.put("/v1/account/ai-consent", json={"granted": True, "disclosureVersion": DISCLOSURE_VERSION}).status_code == 200
            require_ai_consent(owner.id)
            assert client.put("/v1/account/ai-consent", json={"granted": False, "disclosureVersion": "old"}).status_code == 200
            with pytest.raises(PermissionError):
                service.submit(VeoRequest("private prompt"), account_id=owner.id)
    finally:
        app.dependency_overrides.clear()
        with psycopg.connect(url) as c:
            c.execute("DELETE FROM app.ai_consent WHERE account_id=%s", (owner.id,))
            c.execute("DELETE FROM app.accounts WHERE id=%s", (owner.id,))
