import uuid

import psycopg
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.db import migrate


def test_campaign_edit_conflicts_and_history(monkeypatch):
    url = "postgresql://postgres:postgres@localhost:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", url)
    migrate()
    owner, asset, product, campaign = [uuid.uuid4() for _ in range(4)]
    with psycopg.connect(url) as connection:
        connection.execute("INSERT INTO app.accounts(id,email) VALUES (%s,'edit@example.com')", (owner,))
        connection.execute("INSERT INTO app.assets(asset_key,owner_id,storage_key,mime_type,verification_state) VALUES (%s,%s,%s,'image/png','verified')", (asset, owner, str(asset)))
        connection.execute("INSERT INTO app.products(id,owner_id,name,source_asset_id) VALUES (%s,%s,'Cream',%s)", (product, owner, asset))
        connection.execute("INSERT INTO app.product_images(product_id,owner_id,version,asset_key) VALUES (%s,%s,1,%s)", (product, owner, asset))
        connection.execute("INSERT INTO app.campaigns(id,owner_id,product_id,image_version,brief) VALUES (%s,%s,%s,1,%s)", (campaign, owner, product, psycopg.types.json.Jsonb({"instructions": "Slow camera", "offer": "20% off"})))
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(owner), "edit@example.com")
    try:
        with TestClient(app) as client:
            route = f"/v1/campaigns/{campaign}"
            edit = {"expectedVersion": 1, "offer": "15% off", "caption": "Fresh", "cta": "Shop", "color": "#ABCDEF"}
            changed = client.patch(route, json=edit)
            assert changed.status_code == 200
            assert changed.json()["version"] == 2
            assert changed.json()["brief"]["instructions"] == "Slow camera"
            assert client.patch(route, json=edit).status_code == 409
            assert client.get(route).json()["brief"]["offer"] == "15% off"
            history = client.get(f"/v1/products/{product}/campaigns").json()
            assert history["items"][0]["id"] == str(campaign)
            assert history["items"][0]["version"] == 2
            app.dependency_overrides[authenticated_subject] = lambda: Subject(str(uuid.uuid4()), "other@example.com")
            assert client.patch(route, json=edit).status_code == 404
            assert client.get(f"/v1/products/{product}/campaigns").status_code == 404
        with psycopg.connect(url) as connection:
            assert connection.execute("SELECT count(*) FROM app.jobs WHERE owner_id=%s", (owner,)).fetchone()[0] == 0
    finally:
        app.dependency_overrides.clear()
        with psycopg.connect(url) as connection:
            connection.execute("DELETE FROM app.campaigns WHERE id=%s", (campaign,))
            connection.execute("DELETE FROM app.product_images WHERE product_id=%s", (product,))
            connection.execute("DELETE FROM app.products WHERE id=%s", (product,))
            connection.execute("DELETE FROM app.assets WHERE asset_key=%s", (asset,))
            connection.execute("DELETE FROM app.accounts WHERE id=%s", (owner,))
