import uuid

import psycopg
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.db import migrate


def test_approved_images_preserve_versions_without_paid_work(monkeypatch):
    url = "postgresql://postgres:postgres@localhost:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", url)
    migrate()
    owner = Subject(str(uuid.uuid4()), "images@example.com")
    assets = [uuid.uuid4(), uuid.uuid4()]
    with psycopg.connect(url) as connection:
        connection.execute("INSERT INTO app.accounts(id,email) VALUES (%s,%s)", (owner.id, owner.email))
        for asset in assets:
            connection.execute("INSERT INTO app.assets(asset_key,owner_id,storage_key,mime_type,verification_state) VALUES (%s,%s,%s,'image/png','verified')", (asset, owner.id, f"test/{asset}"))
    app.dependency_overrides[authenticated_subject] = lambda: owner
    try:
        with TestClient(app) as client:
            product = client.post("/v1/products", json={"name": "Cream", "assetKey": str(assets[0])}).json()
            route = f"/v1/products/{product['id']}/approved-image"
            assert client.get(route).json() == {"image": None}
            first = {"assetKey": str(assets[0]), "expectedVersion": 0}
            assert client.post(route, json=first).json()["version"] == 1
            assert client.post(route, json=first).json()["version"] == 1
            assert client.post(route, json={"assetKey": str(assets[1]), "expectedVersion": 0}).status_code == 409
            assert client.post(route, json={"assetKey": str(assets[1]), "expectedVersion": 1}).json()["version"] == 2
            assert client.get(route).json()["image"]["assetKey"] == str(assets[1])
            assert client.get(route, params={"version": 1}).json()["image"]["assetKey"] == str(assets[0])
            app.dependency_overrides[authenticated_subject] = lambda: Subject(str(uuid.uuid4()), "other@example.com")
            assert client.get(route).status_code == 404
            assert client.post(route, json=first).status_code == 404
            app.dependency_overrides[authenticated_subject] = lambda: owner
            client.delete(f"/v1/products/{product['id']}")
            assert client.post(route, json=first).status_code == 404
        with psycopg.connect(url) as connection:
            assert connection.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (owner.id,)).fetchone()[0] == 0
            assert connection.execute("SELECT count(*) FROM app.jobs WHERE owner_id=%s", (owner.id,)).fetchone()[0] == 0
    finally:
        app.dependency_overrides.clear()
        with psycopg.connect(url) as connection:
            connection.execute("DELETE FROM app.product_images WHERE owner_id=%s", (owner.id,))
            connection.execute("DELETE FROM app.products WHERE owner_id=%s", (owner.id,))
            connection.execute("DELETE FROM app.assets WHERE owner_id=%s", (owner.id,))
            connection.execute("DELETE FROM app.accounts WHERE id=%s", (owner.id,))
