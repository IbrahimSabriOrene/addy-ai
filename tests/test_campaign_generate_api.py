import uuid

import psycopg
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.consent import DISCLOSURE_VERSION
from admaker.eligibility import POLICY_VERSION
from test_worker_leases import URL, queued_job


def test_pack_quote_consent_price_and_disabled_replay(queued_job, monkeypatch):
    account, old_job, reservation, queue = queued_job
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.delenv("ENABLE_CAMPAIGN_PACKS", raising=False)
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "merchant@example.com")
    try:
        with psycopg.connect(URL) as c:
            asset = c.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (old_job,)).fetchone()[0]
            c.execute("INSERT INTO app.credit_ledger(account_id,delta,event_key) VALUES (%s,10,%s)", (account, str(uuid.uuid4())))
        with TestClient(app) as client:
            product = client.post("/v1/products", json={"name": "Fixture", "assetKey": str(asset)}).json()["id"]
            assert client.post(f"/v1/products/{product}/approved-image", json={"assetKey": str(asset), "expectedVersion": 0}).status_code == 200
            campaign = client.post("/v1/campaigns", json={"productId": product, "imageVersion": 1, "templateId": "pedestal_spin", "templateVersion": 1}, headers={"Idempotency-Key": str(uuid.uuid4())}).json()["id"]
            path = f"/v1/campaigns/{campaign}"
            body = {"expectedVersion": 1, "confirmedCredits": 3}
            headers = {"Idempotency-Key": "generate"}
            quote = client.get(path + "/generation-quote").json()
            assert quote["available"] is False and quote["priceCredits"] is None
            assert client.post(path + "/generate", json=body, headers=headers).status_code == 503
            monkeypatch.setenv("ENABLE_CAMPAIGN_PACKS", "true")
            monkeypatch.setenv("CAMPAIGN_PACK_CREDITS", "3")
            monkeypatch.setenv("CAMPAIGN_PACK_QUEUE", queue)
            assert client.get(path + "/generation-quote").json()["priceCredits"] == 3
            assert client.post(path + "/generate", json=body, headers=headers).status_code == 403
            assert client.post("/v1/account/eligibility", json={"over18": True, "businessUse": True, "policyVersion": POLICY_VERSION}).status_code == 200
            assert client.put("/v1/account/ai-consent", json={"granted": True, "disclosureVersion": DISCLOSURE_VERSION}).status_code == 200
            assert client.post(path + "/generate", json={**body, "confirmedCredits": 2}, headers=headers).status_code == 409
            first = client.post(path + "/generate", json=body, headers=headers)
            assert first.status_code == 202
            with psycopg.connect(URL) as c:
                assert c.execute("SELECT amount,state FROM app.credit_reservations WHERE job_id=%s", (first.json()["id"],)).fetchone() == (3, "held")
            monkeypatch.setenv("ENABLE_CAMPAIGN_PACKS", "false")
            client.put("/v1/account/ai-consent", json={"granted": False, "disclosureVersion": DISCLOSURE_VERSION})
            assert client.post(path + "/generate", json=body, headers=headers).json() == first.json()
            assert client.post(path + "/generate", json={**body, "expectedVersion": 2}, headers=headers).status_code == 409
            app.dependency_overrides[authenticated_subject] = lambda: Subject(str(uuid.uuid4()), "other@example.com")
            assert client.get(path + "/generation-quote").status_code == 404
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.campaign_generations WHERE campaign_id IN (SELECT id FROM app.campaigns WHERE owner_id=%s)", (account,))
            c.execute("DELETE FROM app.credit_reservations WHERE account_id=%s AND job_id<>%s", (account, old_job))
            c.execute("DELETE FROM app.jobs WHERE owner_id=%s AND id<>%s", (account, old_job))
            c.execute("DELETE FROM app.command_keys WHERE account_id=%s", (account,))
            c.execute("DELETE FROM app.campaigns WHERE owner_id=%s", (account,))
            c.execute("DELETE FROM app.product_images WHERE owner_id=%s", (account,))
            c.execute("DELETE FROM app.products WHERE owner_id=%s", (account,))
            c.execute("DELETE FROM app.ai_consent WHERE account_id=%s", (account,))
