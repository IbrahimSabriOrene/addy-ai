from concurrent.futures import ThreadPoolExecutor
import uuid

import psycopg
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.consent import DISCLOSURE_VERSION
from admaker.eligibility import POLICY_VERSION
from test_worker_leases import URL, queued_job


def test_one_action_is_atomic_replayable_and_can_close_without_creating_a_campaign(queued_job, monkeypatch):
    account, old_job, reservation, queue = queued_job
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("ENABLE_CAMPAIGN_PACKS", "true")
    monkeypatch.setenv("CAMPAIGN_PACK_CREDITS", "3")
    monkeypatch.setenv("CAMPAIGN_PACK_QUEUE", queue)
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "merchant@example.test")
    try:
        with psycopg.connect(URL) as c:
            asset = c.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (old_job,)).fetchone()[0]
        with TestClient(app) as client:
            product = client.post("/v1/products", json={"name": "Fixture", "assetKey": str(asset)}).json()["id"]
            assert client.post(f"/v1/products/{product}/approved-image", json={"assetKey": str(asset), "expectedVersion": 0}).status_code == 200
            payload = {"productId": product, "imageVersion": 1, "templateId": "pedestal_spin", "templateVersion": 1, "offer": "20% off", "confirmedCredits": 3}
            path, headers = "/v1/campaign-pack/generate", {"Idempotency-Key": "new-pack"}
            assert client.post(path, json=payload, headers=headers).status_code == 403
            assert client.post("/v1/account/eligibility", json={"over18": True, "businessUse": True, "policyVersion": POLICY_VERSION}).status_code == 200
            client.put("/v1/account/ai-consent", json={"granted": True, "disclosureVersion": DISCLOSURE_VERSION})
            assert client.post(path, json=payload, headers=headers).status_code == 409  # No credits.
            with psycopg.connect(URL) as c:
                assert c.execute("SELECT count(*) FROM app.campaigns WHERE owner_id=%s", (account,)).fetchone() == (0,)
                c.execute("INSERT INTO app.credit_ledger(account_id,delta,event_key) VALUES (%s,10,%s)", (account, str(uuid.uuid4())))
            assert client.post(path, json={**payload, "confirmedCredits": 2}, headers=headers).status_code == 409
            closed = {"Idempotency-Key": "closed-pack"}
            assert client.post(path + "/close", json=payload, headers=closed).json() == {"state": "cancelled"}
            assert client.post(path, json=payload, headers=closed).status_code == 409
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(lambda _: client.post(path, json=payload, headers=headers), range(2)))
            assert all(response.status_code == 202 for response in responses)
            result = responses[0].json()
            assert result == responses[1].json()
            monkeypatch.setenv("ENABLE_CAMPAIGN_PACKS", "false")
            client.put("/v1/account/ai-consent", json={"granted": False, "disclosureVersion": DISCLOSURE_VERSION})
            assert client.post(path, json=payload, headers=headers).json() == result
            assert client.post(path + "/close", json=payload, headers=headers).json() == result
            assert client.post(path, json={**payload, "offer": "15% off"}, headers=headers).status_code == 409
            with psycopg.connect(URL) as c:
                assert c.execute("SELECT count(*) FROM app.campaigns WHERE owner_id=%s", (account,)).fetchone() == (1,)
                assert c.execute("SELECT amount,state FROM app.credit_reservations WHERE job_id=%s", (result["id"],)).fetchone() == (3, "held")
                assert c.execute("SELECT sum(delta) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (10,)
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
