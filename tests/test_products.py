import uuid

import psycopg
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.db import migrate


def test_products_persist_and_enforce_ownership(monkeypatch):
    database_url = "postgresql://postgres:postgres@localhost:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", database_url)
    migrate()
    migrate()
    owner, other = (Subject(str(uuid.uuid4()), "products@example.com") for _ in range(2))
    assets = [uuid.uuid4() for _ in range(3)]
    with psycopg.connect(database_url) as connection:
        for subject in (owner, other):
            connection.execute("INSERT INTO app.accounts(id,email) VALUES (%s,%s)", (subject.id, subject.email))
        for asset, subject, state in zip(assets, (owner, owner, other), ("verified", "pending", "verified")):
            connection.execute("INSERT INTO app.assets(asset_key,owner_id,storage_key,mime_type,verification_state) VALUES (%s,%s,%s,'image/jpeg',%s)", (asset, subject.id, f"test/{asset}", state))
    app.dependency_overrides[authenticated_subject] = lambda: owner
    try:
        with TestClient(app) as client:
            for asset in assets[1:]:
                assert client.post("/v1/products", json={"name": "No", "assetKey": str(asset)}).status_code == 422
            assert client.post("/v1/products", json={"name": "   ", "assetKey": str(assets[0])}).status_code == 422
            products = [client.post("/v1/products", json={"name": name, "assetKey": str(assets[0])}).json() for name in ("Cream", "Serum")]
            product_id = products[0]["id"]
            page = client.get("/v1/products?limit=1").json()
            second = client.get("/v1/products", params={"limit": 1, "cursor": page["nextCursor"]}).json()
            assert {page["items"][0]["id"], second["items"][0]["id"]} == {p["id"] for p in products}
            assert client.patch(f"/v1/products/{product_id}", json={"name": "New name"}).json()["name"] == "New name"
            app.dependency_overrides[authenticated_subject] = lambda: other
            assert client.get("/v1/products").json()["items"] == []
            assert client.get(f"/v1/products/{product_id}").status_code == 404
            assert client.patch(f"/v1/products/{product_id}", json={"name": "Stolen"}).status_code == 404
            assert client.delete(f"/v1/products/{product_id}").status_code == 404
        app.dependency_overrides[authenticated_subject] = lambda: owner
        with TestClient(app) as restarted:
            assert restarted.get(f"/v1/products/{product_id}").json()["name"] == "New name"
            assert restarted.delete(f"/v1/products/{product_id}").json()["assetsRetained"] is True
            assert restarted.delete(f"/v1/products/{product_id}").status_code == 200
            assert restarted.get(f"/v1/products/{product_id}").status_code == 404
            assert len(restarted.get("/v1/products").json()["items"]) == 1
        with psycopg.connect(database_url) as connection:
            assert connection.execute("SELECT count(*) FROM app.assets WHERE owner_id=%s", (owner.id,)).fetchone()[0] == 2
    finally:
        app.dependency_overrides.clear()
        with psycopg.connect(database_url) as connection:
            connection.execute("DELETE FROM app.products WHERE owner_id=%s", (owner.id,))
            for subject in (owner, other):
                connection.execute("DELETE FROM app.assets WHERE owner_id=%s", (subject.id,))
                connection.execute("DELETE FROM app.accounts WHERE id=%s", (subject.id,))
