import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.billing import process_revenuecat_event
from admaker.db import migrate
from admaker.auth import Subject, authenticated_subject

URL = "postgresql://postgres:postgres@localhost:54322/postgres"


@pytest.mark.parametrize("configuration", ['[]', '{"pack":true}', '{"pack":0}', '{"pack":1.5}', '{"pack":1000001}', '{" pack":10}', '{"":10}', 'invalid'])
def test_invalid_pack_catalogue_cannot_grant(billing, monkeypatch, configuration):
    send, ledger, outcome, owner, _ = billing
    monkeypatch.setenv("REVENUECAT_CREDIT_PACKS", configuration)
    app.dependency_overrides[authenticated_subject] = lambda: Subject(owner, "billing-a@example.com")
    try:
        with TestClient(app) as client:
            assert client.get("/v1/credits/packs").status_code == 503
        _, event = send()
        assert outcome(event) == "configuration_required"
        assert ledger() == []
    finally:
        app.dependency_overrides.clear()


def test_catalogue_and_private_confirmed_purchase_history(billing, monkeypatch):
    send, ledger, _, owner, other = billing
    current = owner
    client = TestClient(app)
    assert client.get("/v1/credits/packs").status_code == 401
    assert client.get("/v1/credits/purchases").status_code == 401
    app.dependency_overrides[authenticated_subject] = lambda: Subject(current, "billing-a@example.com")
    try:
        response = client.get("/v1/credits/packs")
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "private, no-store"
        assert response.json() == {"items": [{"productId": "pack", "credits": 10}]}
        assert client.get("/v1/credits/purchases").json() == {"items": []}
        _, purchase = send()
        send(transaction_id=purchase["transaction_id"])
        response = client.get("/v1/credits/purchases")
        assert response.headers["Cache-Control"] == "private, no-store"
        items = response.json()["items"]
        assert len(items) == 1 and items[0]["credits"] == 10 and items[0]["status"] == "granted"
        assert set(items[0]) == {"id", "productId", "credits", "status", "createdAt"}
        current = other
        assert client.get("/v1/credits/purchases", params={"accountId": owner}).json() == {"items": []}
        current = owner
        monkeypatch.setenv("REVENUECAT_CREDIT_PACKS", '{"pack":25}')
        assert client.get("/v1/credits/packs").json()["items"][0]["credits"] == 25
        send("CANCELLATION", purchase["transaction_id"])
        updated = client.get("/v1/credits/purchases").json()["items"]
        assert updated == [{**items[0], "status": "reversed"}]
        assert [row[1] for row in ledger()] == [10, -10]
        monkeypatch.delenv("REVENUECAT_APP_ID")
        assert client.get("/v1/credits/packs").status_code == 503
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def billing(monkeypatch):
    migrate(URL)
    owner, other = str(uuid.uuid4()), str(uuid.uuid4())
    app_id = str(uuid.uuid4())
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("REVENUECAT_AUTHORIZATION", "Bearer fixture-secret")
    monkeypatch.setenv("REVENUECAT_APP_ID", app_id)
    monkeypatch.setenv("REVENUECAT_ENVIRONMENT", "SANDBOX")
    monkeypatch.setenv("REVENUECAT_CREDIT_PACKS", '{"pack":10}')
    with psycopg.connect(URL) as c:
        c.execute("INSERT INTO app.accounts(id,email) VALUES (%s,'billing-a@example.com'),(%s,'billing-b@example.com')", (owner, other))
    client = TestClient(app)
    receipts = []

    def send(kind="NON_RENEWING_PURCHASE", transaction_id=None, **extra):
        event = {"id": str(uuid.uuid4()), "type": kind, "app_id": app_id, "store": "APP_STORE", "environment": "SANDBOX",
                 "transaction_id": str(uuid.uuid4()) if transaction_id is None else transaction_id, "product_id": "pack", "app_user_id": owner}
        if kind == "CANCELLATION":
            event["cancel_reason"] = "CUSTOMER_SUPPORT"
        event.update(extra)
        receipts.append(event["id"])
        response = client.post("/v1/webhooks/revenuecat", json={"event": event}, headers={"Authorization": "Bearer fixture-secret"})
        return response, event

    def ledger():
        with psycopg.connect(URL) as c:
            return c.execute("SELECT account_id,delta,event_key FROM app.credit_ledger WHERE account_id IN (%s,%s) ORDER BY id", (owner, other)).fetchall()

    def outcome(event):
        with psycopg.connect(URL) as c:
            return c.execute("SELECT outcome FROM app.webhook_events WHERE event_id=%s", (event["id"],)).fetchone()[0]

    try:
        yield send, ledger, outcome, owner, other
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.webhook_events WHERE provider='revenuecat' AND event_id=ANY(%s)", (receipts,))
            c.execute("DELETE FROM app.purchase_transactions WHERE app_id=%s", (app_id,))
            c.execute("DELETE FROM app.credit_ledger WHERE account_id IN (%s,%s)", (owner, other))
            c.execute("DELETE FROM app.accounts WHERE id IN (%s,%s)", (owner, other))


def test_exact_purchase_confirmation_is_private_and_read_only(billing, monkeypatch):
    send, ledger, _, owner, other = billing
    current = owner
    client = TestClient(app)
    path = "/v1/credits/purchases/status"
    query = {"transactionId": "store/order+1?with=characters", "productId": "pack", "store": "APP_STORE"}
    assert client.get(path, params=query).status_code == 401
    app.dependency_overrides[authenticated_subject] = lambda: Subject(current, "billing-a@example.com")
    try:
        assert client.get(path, params=query).json() == {"status": "pending"}
        _, purchase = send(transaction_id=query["transactionId"])
        response = client.get(path, params=query)
        assert response.headers["Cache-Control"] == "private, no-store"
        assert response.json() == {"status": "granted", "credits": 10}
        baseline = ledger()
        for changes in [{"store": "PLAY_STORE"}, {"productId": "another"}, {"transactionId": "unknown"}]:
            assert client.get(path, params={**query, **changes}).json() == {"status": "pending"}
        current = other
        assert client.get(path, params=query).json() == {"status": "pending"}
        current = owner
        with monkeypatch.context() as scoped:
            scoped.setenv("REVENUECAT_ENVIRONMENT", "PRODUCTION")
            assert client.get(path, params=query).json() == {"status": "pending"}
        assert ledger() == baseline, "Status lookups cannot grant credits"
        send("CANCELLATION", purchase["transaction_id"])
        assert client.get(path, params=query).json() == {"status": "reversed", "credits": 10}
        assert client.get(path, params={**query, "transactionId": "x" * 301}).status_code == 422
        assert client.get(path, params={**query, "store": "untrusted"}).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_refund_before_purchase_reconciles_once(billing):
    send, ledger, outcome, _, _ = billing
    transaction = str(uuid.uuid4())
    response, refund = send("CANCELLATION", transaction)
    assert response.status_code == 202
    assert outcome(refund) == "awaiting_purchase"
    assert ledger() == []
    response, purchase = send(transaction_id=transaction)
    assert response.status_code == 202
    assert outcome(purchase) == "reversed"
    assert [row[1] for row in ledger()] == [10, -10]
    assert process_revenuecat_event(URL, refund["id"]) == "reversed"
    for _ in range(2):
        send(transaction_id=transaction)
        send("CANCELLATION", transaction)
    assert [row[1] for row in ledger()] == [10, -10]


def test_refund_uses_original_amount_and_owner_even_after_spend(billing, monkeypatch):
    send, ledger, _, owner, other = billing
    _, purchase = send()
    with psycopg.connect(URL) as c:
        c.execute("INSERT INTO app.credit_ledger(account_id,delta,event_key) VALUES (%s,-7,%s)", (owner, str(uuid.uuid4())))
    monkeypatch.setenv("REVENUECAT_CREDIT_PACKS", "invalid config")
    response, _ = send("CANCELLATION", purchase["transaction_id"], app_user_id=other)
    assert response.status_code == 202
    assert [row[1] for row in ledger()] == [10, -7, -10]
    assert all(str(row[0]) == owner for row in ledger())
    assert sum(row[1] for row in ledger()) == -7, "Refund debt is preserved rather than erasing spent credits"


def test_concurrent_distinct_events_and_aliases_do_not_double_grant(billing):
    send, ledger, outcome, owner, other = billing
    transaction = str(uuid.uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: send(transaction_id=transaction), range(2)))
    assert all(response.status_code == 202 for response, _ in results)
    assert len(ledger()) == 1
    send(transaction_id=transaction, app_user_id=other)
    assert len(ledger()) == 1 and str(ledger()[0][0]) == owner
    response, aliased = send(app_user_id="$RCAnonymousID:fixture", aliases=[owner])
    assert response.status_code == 202 and outcome(aliased) == "granted"
    _, ambiguous = send(app_user_id=owner, aliases=[other])
    assert outcome(ambiguous) == "reconciliation_required"
    assert len(ledger()) == 2


def test_scope_missing_identity_and_unsupported_events_remain_safe(billing):
    send, ledger, outcome, _, _ = billing
    _, event = send(environment="PRODUCTION")
    assert outcome(event) == "ignored_environment" and ledger() == []
    _, event = send(app_user_id="$RCAnonymousID:unmapped")
    assert outcome(event) == "awaiting_identity" and ledger() == []
    _, event = send(transaction_id="")
    assert outcome(event) == "reconciliation_required" and ledger() == []
    _, malformed = send(transaction_id=["bad"])
    assert outcome(malformed) == "reconciliation_required"
    before = len(ledger())
    for kind in ("TRANSFER", "REFUND_REVERSED", "REFUND"):
        _, event = send(kind)
        assert outcome(event) == "reconciliation_required"
    assert len(ledger()) == before
    same_id = str(uuid.uuid4())
    send(transaction_id=same_id)
    send(transaction_id=same_id, store="PLAY_STORE")
    assert len(ledger()) == before + 2, "Store namespaces do not collide"


def test_receipt_survives_processing_failure_and_payload_mismatch(billing, monkeypatch):
    send, ledger, outcome, _, _ = billing
    with monkeypatch.context() as patch:
        def unavailable(*_):
            raise psycopg.OperationalError("fixture outage")
        patch.setattr("admaker.billing.process_revenuecat_event", unavailable)
        response, event = send()
    assert response.status_code == 202 and outcome(event) == "received" and ledger() == []
    assert process_revenuecat_event(URL, event["id"]) == "granted"
    response, _ = send(id=event["id"], transaction_id=event["transaction_id"], product_id="changed")
    assert response.status_code == 409 and len(ledger()) == 1


def test_invalid_webhook_envelopes_are_rejected_before_receipt(billing):
    client = TestClient(app)
    headers = {"Authorization": "Bearer fixture-secret", "Content-Type": "application/json"}
    for content in (b"not json", b"null", b"[]", b'{"event":{"id":3,"type":"TEST"}}',
                    b'{"event":{"id":"invalid","type":"TEST","price":NaN}}'):
        assert client.post("/v1/webhooks/revenuecat", content=content, headers=headers).status_code == 422
    assert client.post("/v1/webhooks/revenuecat", content=b" " * 65537, headers=headers).status_code == 413
