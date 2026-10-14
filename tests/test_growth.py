import uuid
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from admaker.api import app, CampaignRequest
from admaker.auth import Subject, authenticated_subject
from admaker.growth import Preferences
from admaker.growth_worker import collect_notifications, dispatch_account
from test_worker_leases import URL, queued_job


@pytest.fixture
def growth_account(queued_job, monkeypatch):
    account, job, reservation, queue = queued_job
    monkeypatch.setenv("DATABASE_URL", URL)
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "growth@example.com")
    try:
        with TestClient(app) as client:
            yield account, job, client
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)


def test_preferences_default_off_validation_and_withdrawal(growth_account):
    account, job, client = growth_account
    initial = client.get("/v1/account/engagement").json()
    assert initial["version"] == 0
    assert not any(initial["preferences"][k] for k in ("completion", "weekly", "analytics"))
    device = {"token": "ExpoPushToken[fixture]"}
    assert client.put("/v1/account/push-device", json=device).status_code == 409
    prefs = {**initial["preferences"], "completion": True, "weekly": True, "analytics": True, "expectedVersion": 0}
    assert client.put("/v1/account/engagement", json={**prefs, "timezone": "not/a-zone"}).status_code == 422
    assert client.put("/v1/account/engagement", json={**prefs, "hour": 3}).status_code == 422
    assert client.put("/v1/account/engagement", json=prefs).status_code == 200
    assert client.put("/v1/account/engagement", json=prefs).status_code == 409
    assert client.put("/v1/account/push-device", json=device).status_code == 200
    for _ in range(2):
        assert client.post("/v1/account/engagement/events", json={"name": "browse"}).status_code == 204
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT count(*) FROM app.growth_events WHERE account_id=%s", (account,)).fetchone() == (1,)
    assert client.put("/v1/account/engagement", json={**initial["preferences"], "expectedVersion": 1}).status_code == 200
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT count(*) FROM app.growth_events WHERE account_id=%s", (account,)).fetchone() == (0,)
        assert c.execute("SELECT count(*) FROM app.push_devices WHERE account_id=%s", (account,)).fetchone() == (0,)
    assert client.post("/v1/account/engagement/events", json={"name": "browse", "photo": "private"}).status_code == 422


def test_outcomes_owner_and_conflict(growth_account):
    account, job, client = growth_account
    product, campaign = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(URL) as c:
        asset = c.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (job,)).fetchone()[0]
        c.execute("INSERT INTO app.products(id,owner_id,name,source_asset_id) VALUES (%s,%s,'Growth',%s)", (product, account, asset))
        c.execute("INSERT INTO app.product_images(product_id,owner_id,version,asset_key) VALUES (%s,%s,1,%s)", (product, account, asset))
    try:
        created = client.post("/v1/campaigns", json={"productId": str(product), "imageVersion": 1, "objective": "weekend"}, headers={"Idempotency-Key": "growth"})
        assert created.status_code == 201, created.text
        campaign = created.json()["id"]
        assert client.get(f"/v1/campaigns/{campaign}").json()["brief"]["objective"] == "weekend"
        route = f"/v1/campaigns/{campaign}/outcome"
        assert client.get(route).json()["result"]["orders"] is None
        body = {"expectedVersion": 0, "published": True, "orders": 2, "messages": 4, "useful": True}
        assert client.put(route, json=body).status_code == 200
        assert client.put(route, json=body).status_code == 409
        assert client.get("/v1/account/engagement/stats").json()["publishedSelfReported"] == 1
        from admaker.campaign_operating_costs import record_costs
        from admaker.growth_metrics import growth_metrics
        record_costs(URL, campaign, storage=10000, support=0)
        record_costs(URL, campaign, payment_fees=20000)
        costs = growth_metrics(URL)["allocatedOperatingCosts"]
        assert next(row for row in costs if row["campaignId"] == campaign) == {"campaignId": campaign, "storageMicrousd": 10000, "supportMicrousd": 0, "paymentFeesMicrousd": 20000}
        app.dependency_overrides[authenticated_subject] = lambda: Subject(str(uuid.uuid4()), "other@example.com")
        assert client.get(route).status_code == 404
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.command_keys WHERE account_id=%s", (account,))
            c.execute("DELETE FROM app.campaigns WHERE owner_id=%s", (account,))
            c.execute("DELETE FROM app.product_images WHERE owner_id=%s", (account,))
            c.execute("DELETE FROM app.products WHERE owner_id=%s", (account,))


def test_notification_collection_quiet_hours_dedup_and_concurrent_cap(growth_account):
    account, job, client = growth_account
    now = datetime.now(timezone.utc).replace(hour=10, minute=0)
    prefs = {**Preferences().model_dump(), "completion": True, "weekly": True, "weekday": now.weekday(), "expectedVersion": 0}
    assert client.put("/v1/account/engagement", json=prefs).status_code == 200
    assert client.put("/v1/account/push-device", json={"token": "ExpoPushToken[test]"}).status_code == 200
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.growth_preferences SET updated_at=now()-interval '1 hour' WHERE account_id=%s", (account,))
        c.execute("UPDATE app.jobs SET state='delivered' WHERE id=%s", (job,))
        collect_notifications(c, account, now.replace(hour=23))
        assert c.execute("SELECT count(*) FROM app.growth_notifications WHERE account_id=%s", (account,)).fetchone() == (0,)
        collect_notifications(c, account, now)
        collect_notifications(c, account, now)
        assert c.execute("SELECT count(*) FROM app.growth_notifications WHERE account_id=%s", (account,)).fetchone() == (2,)
    sent = []
    def send(message):
        sent.append(message)
        return {"status": "ok", "id": "ticket"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: dispatch_account(URL, account, send=send, now=now), range(2)))
    assert len(sent) == 1
    assert sent[0]["data"] == {"screen": "notifications"}
    assert str(job) not in str(sent[0])
    assert client.put("/v1/account/engagement", json={**Preferences().model_dump(), "expectedVersion": 1}).status_code == 200
    dispatch_account(URL, account, send=send, now=now)
    assert len(sent) == 1
    assert client.get("/v1/account/notifications").json() == {"items": []}


@pytest.mark.parametrize("mode", ["unknown", "invalid_device", "receipt"])
def test_notification_transport_recovery(growth_account, mode):
    import httpx
    from admaker.growth_worker import reconcile_receipts
    account, job, client = growth_account
    now = datetime.now(timezone.utc).replace(hour=10)
    client.put("/v1/account/engagement", json={**Preferences().model_dump(), "completion": True, "expectedVersion": 0})
    client.put("/v1/account/push-device", json={"token": "ExpoPushToken[transport]"})
    with psycopg.connect(URL) as c:
        # Job was created before permission, but completion happens after permission.
        c.execute("UPDATE app.jobs SET state='delivered' WHERE id=%s", (job,))
        collect_notifications(c, account, now)
    calls = []
    def send(message):
        calls.append(message)
        if mode == "unknown":
            raise httpx.ReadTimeout("ambiguous")
        return {"status": "error", "details": {"error": "DeviceNotRegistered"}} if mode == "invalid_device" else {"status": "ok", "id": "receipt"}
    dispatch_account(URL, account, send=send, now=now)
    dispatch_account(URL, account, send=send, now=now)
    assert len(calls) == 1
    with psycopg.connect(URL) as c:
        expected = {"unknown": "unknown", "invalid_device": "rejected", "receipt": "accepted"}[mode]
        assert c.execute("SELECT push_state FROM app.growth_notifications WHERE account_id=%s", (account,)).fetchone() == (expected,)
        if mode == "invalid_device":
            assert c.execute("SELECT count(*) FROM app.push_devices WHERE account_id=%s", (account,)).fetchone() == (0,)
        if mode == "receipt":
            c.execute("UPDATE app.growth_notifications SET push_attempted_at=now()-interval '16 minutes' WHERE account_id=%s", (account,))
    if mode == "receipt":
        reconcile_receipts(URL, fetch=lambda ids: {"receipt": {"status": "ok"}})
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT push_state FROM app.growth_notifications WHERE account_id=%s", (account,)).fetchone() == ("receipt_ok",)


def test_growth_data_deleted_with_account(growth_account):
    from admaker.account_deletion import request_account_deletion
    from admaker.delete_application import delete_requested_application_data
    account, job, client = growth_account
    client.put("/v1/account/engagement", json={**Preferences().model_dump(), "completion": True, "analytics": True, "expectedVersion": 0})
    client.put("/v1/account/push-device", json={"token": "ExpoPushToken[delete]"})
    client.post("/v1/account/engagement/events", json={"name": "result"})
    try:
        with psycopg.connect(URL) as c:
            request_account_deletion(c, account)
            c.execute("UPDATE app.account_deletions SET identity_deleted_at=now(),media_deleted_at=now() WHERE account_id=%s", (account,))
        assert delete_requested_application_data(URL, account)["state"] == "application_removed"
        with psycopg.connect(URL) as c:
            for table in ("growth_preferences", "push_devices", "growth_events", "growth_notifications"):
                assert c.execute(f"SELECT count(*) FROM app.{table} WHERE account_id=%s", (account,)).fetchone() == (0,)
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.account_deletions WHERE account_id=%s", (account,))
