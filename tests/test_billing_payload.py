import copy
import hashlib
import json
import uuid

import psycopg
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient

from admaker.api import app
from test_worker_leases import URL, queued_job


def test_minimized_webhooks_keep_replay_refund_and_legacy_receipt_compatibility(queued_job, monkeypatch):
    account, _, _, _ = queued_job
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("REVENUECAT_AUTHORIZATION", "Bearer fixture-secret")
    monkeypatch.setenv("REVENUECAT_CREDIT_PACKS", '{"credits10":10}')
    monkeypatch.setenv("REVENUECAT_APP_ID", "fixture-app")
    monkeypatch.setenv("REVENUECAT_ENVIRONMENT", "SANDBOX")
    purchase, refund = str(uuid.uuid4()), str(uuid.uuid4())
    payload = {"metadata": {"private": "top-level"}, "event": {
        "id": purchase, "type": "NON_RENEWING_PURCHASE", "app_user_id": str(account),
        "product_id": "credits10", "transaction_id": purchase, "app_id": "fixture-app",
        "store": "APP_STORE", "environment": "SANDBOX", "aliases": [str(account)],
        "subscriber_attributes": {"$email": {"value": "private@example.test"}},
        "ip_address": "192.0.2.1", "price": 1.99, "currency": "USD"}}
    headers = {"Authorization": "Bearer fixture-secret"}
    try:
        with TestClient(app) as client:
            for _ in range(2):
                assert client.post("/v1/webhooks/revenuecat", json=payload, headers=headers).status_code == 202
            changed = copy.deepcopy(payload)
            changed["event"]["subscriber_attributes"]["$email"]["value"] = "different@example.test"
            assert client.post("/v1/webhooks/revenuecat", json=changed, headers=headers).status_code == 409
            refund_payload = copy.deepcopy(payload)
            refund_payload["event"].update(id=refund, type="CANCELLATION", cancel_reason="CUSTOMER_SUPPORT")
            with psycopg.connect(URL) as c:
                # Existing receipts have a hash of the full canonical payload.
                digest = hashlib.sha256(json.dumps(refund_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                c.execute("INSERT INTO app.webhook_events(provider,event_id,payload_hash,payload) VALUES ('revenuecat',%s,%s,%s)", (refund, digest, Jsonb(refund_payload)))
            for _ in range(2):
                assert client.post("/v1/webhooks/revenuecat", json=refund_payload, headers=headers).status_code == 202
        with psycopg.connect(URL) as c:
            receipts = c.execute("SELECT payload,outcome FROM app.webhook_events WHERE provider='revenuecat' AND event_id=ANY(%s)", ([purchase, refund],)).fetchall()
            assert {row[1] for row in receipts} == {"granted", "reversed"}
            for saved, _ in receipts:
                assert set(saved) == {"event"}
                assert "subscriber_attributes" not in saved["event"] and "ip_address" not in saved["event"]
                assert saved["event"]["price"] == 1.99 and saved["event"]["aliases"] == [str(account)]
            assert c.execute("SELECT count(*),sum(delta) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (2, 0)
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.webhook_events WHERE provider='revenuecat' AND event_id=ANY(%s)", ([purchase, refund],))
            c.execute("DELETE FROM app.purchase_transactions WHERE transaction_id=%s", (purchase,))
