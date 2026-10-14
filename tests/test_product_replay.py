import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.db import migrate


def test_concurrent_product_save_replays_one_result(monkeypatch):
    url = "postgresql://postgres:postgres@localhost:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", url)
    migrate()
    owner, asset = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(url) as connection:
        connection.execute("INSERT INTO app.accounts(id,email) VALUES (%s,'replay@example.com')", (owner,))
        connection.execute("INSERT INTO app.assets(asset_key,owner_id,storage_key,mime_type,verification_state) VALUES (%s,%s,%s,'image/png','verified')", (asset, owner, str(asset)))
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(owner), "replay@example.com")
    payload = {"name": "Cream", "assetKey": str(asset)}
    headers = {"Idempotency-Key": str(uuid.uuid4())}
    try:
        with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: client.post("/v1/products", json=payload, headers=headers), range(2)))
            assert all(response.status_code == 201 for response in responses)
            assert responses[0].json() == responses[1].json()
            assert client.post("/v1/products", json={**payload, "name": "Changed"}, headers=headers).status_code == 409
        with psycopg.connect(url) as connection:
            assert connection.execute("SELECT count(*) FROM app.products WHERE owner_id=%s", (owner,)).fetchone()[0] == 1
    finally:
        app.dependency_overrides.clear()
        with psycopg.connect(url) as connection:
            connection.execute("DELETE FROM app.command_keys WHERE account_id=%s", (owner,))
            connection.execute("DELETE FROM app.products WHERE owner_id=%s", (owner,))
            connection.execute("DELETE FROM app.assets WHERE asset_key=%s", (asset,))
            connection.execute("DELETE FROM app.accounts WHERE id=%s", (owner,))
