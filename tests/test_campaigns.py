import uuid

import psycopg
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.db import migrate


def test_campaign_snapshot_and_offer_isolation(monkeypatch):
    url = "postgresql://postgres:postgres@localhost:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", url)
    migrate()
    owner = Subject(str(uuid.uuid4()), "campaign@example.com")
    assets = [uuid.uuid4(), uuid.uuid4()]
    with psycopg.connect(url) as connection:
        connection.execute("INSERT INTO app.accounts(id,email) VALUES (%s,%s)", (owner.id, owner.email))
        for asset in assets:
            connection.execute("INSERT INTO app.assets(asset_key,owner_id,storage_key,mime_type,verification_state) VALUES (%s,%s,%s,'image/png','verified')", (asset, owner.id, str(asset)))
    app.dependency_overrides[authenticated_subject] = lambda: owner
    try:
        with TestClient(app) as client:
            product = client.post("/v1/products", json={"name": "Cream", "assetKey": str(assets[0])}).json()["id"]
            approval = f"/v1/products/{product}/approved-image"
            client.post(approval, json={"assetKey": str(assets[0]), "expectedVersion": 0})
            payload = {"productId": product, "imageVersion": 1, "offer": "20% off"}
            headers = {"Idempotency-Key": str(uuid.uuid4())}
            first = client.post("/v1/campaigns", json=payload, headers=headers)
            assert first.status_code == 201
            assert client.post("/v1/campaigns", json=payload, headers=headers).json() == first.json()
            assert client.post("/v1/campaigns", json={**payload, "offer": "15% off"}, headers=headers).status_code == 409
            client.post(approval, json={"assetKey": str(assets[1]), "expectedVersion": 1})
            second = client.post("/v1/campaigns", json={"productId": product, "imageVersion": 2}, headers={"Idempotency-Key": str(uuid.uuid4())}).json()
            assert second["brief"]["offer"] == ""
            route = f"/v1/campaigns/{first.json()['id']}"
            assert client.get(route).json()["assetKey"] == str(assets[0])
            assert client.get(route).json()["brief"]["offer"] == "20% off"
            app.dependency_overrides[authenticated_subject] = lambda: Subject(str(uuid.uuid4()), "other@example.com")
            assert client.get(route).status_code == 404
        with psycopg.connect(url) as connection:
            assert connection.execute("SELECT count(*) FROM app.campaigns WHERE owner_id=%s", (owner.id,)).fetchone()[0] == 2
            assert connection.execute("SELECT count(*) FROM app.jobs WHERE owner_id=%s", (owner.id,)).fetchone()[0] == 0
    finally:
        app.dependency_overrides.clear()
        with psycopg.connect(url) as connection:
            connection.execute("DELETE FROM app.campaigns WHERE owner_id=%s", (owner.id,))
            connection.execute("DELETE FROM app.command_keys WHERE account_id=%s", (owner.id,))
            connection.execute("DELETE FROM app.product_images WHERE owner_id=%s", (owner.id,))
            connection.execute("DELETE FROM app.products WHERE owner_id=%s", (owner.id,))
            connection.execute("DELETE FROM app.assets WHERE owner_id=%s", (owner.id,))
            connection.execute("DELETE FROM app.accounts WHERE id=%s", (owner.id,))
