import psycopg
import uuid
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.db import migrate


def test_revenuecat_event_is_authenticated_and_deduplicated(monkeypatch) -> None:
    database_url = "postgresql://postgres:postgres@localhost:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REVENUECAT_AUTHORIZATION", "Bearer webhook-secret")
    monkeypatch.setenv("REVENUECAT_CREDIT_PACKS", '{"credits10":10}')
    monkeypatch.setenv("REVENUECAT_APP_ID", "test-app")
    monkeypatch.setenv("REVENUECAT_ENVIRONMENT", "SANDBOX")
    migrate()
    account_id = "00000000-0000-0000-0000-000000000002"
    with psycopg.connect(database_url) as connection:
        connection.execute("INSERT INTO app.accounts (id, email) VALUES (%s, 'buyer@example.com') ON CONFLICT DO NOTHING", (account_id,))
        before = connection.execute("SELECT COALESCE(SUM(delta), 0) FROM app.credit_ledger WHERE account_id=%s", (account_id,)).fetchone()[0]
    event_id = str(uuid.uuid4())
    payload = {"event": {"id": event_id, "type": "NON_RENEWING_PURCHASE", "app_user_id": account_id, "product_id": "credits10", "transaction_id": event_id, "app_id": "test-app", "store": "APP_STORE", "environment": "SANDBOX"}}
    client = TestClient(app)
    assert client.post("/v1/webhooks/revenuecat", json=payload).status_code == 401
    headers = {"Authorization": "Bearer webhook-secret"}
    assert client.post("/v1/webhooks/revenuecat", json=payload, headers=headers).status_code == 202
    assert client.post("/v1/webhooks/revenuecat", json=payload, headers=headers).status_code == 202
    refund_id = str(uuid.uuid4())
    refund = {"event": {**payload["event"], "id": refund_id, "type": "CANCELLATION", "cancel_reason": "CUSTOMER_SUPPORT"}}
    assert client.post("/v1/webhooks/revenuecat", json=refund, headers=headers).status_code == 202
    assert client.post("/v1/webhooks/revenuecat", json=refund, headers=headers).status_code == 202
    with psycopg.connect(database_url) as connection:
        assert connection.execute("SELECT COUNT(*) FROM app.webhook_events WHERE event_id=%s", (event_id,)).fetchone()[0] == 1
        assert connection.execute("SELECT COALESCE(SUM(delta), 0) FROM app.credit_ledger WHERE account_id=%s", (account_id,)).fetchone()[0] == before
        assert connection.execute("SELECT outcome FROM app.webhook_events WHERE event_id=%s", (refund_id,)).fetchone()[0] == "reversed"
