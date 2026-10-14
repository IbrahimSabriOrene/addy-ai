import hashlib
import io
import uuid

import psycopg
from fastapi.testclient import TestClient
from PIL import Image

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from test_worker_leases import URL, queued_job


def test_campaign_logo_is_owned_versioned_removable_and_verified(queued_job, monkeypatch, tmp_path):
    account, job, _, _ = queued_job
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("LOCAL_ASSET_ROOT", str(tmp_path))
    source = tmp_path / "test.png"
    Image.new("RGB", (360, 110), "blue").save(source)
    with psycopg.connect(URL) as c:
        asset = c.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (job,)).fetchone()[0]
        c.execute("UPDATE app.assets SET checksum=%s WHERE asset_key=%s", (hashlib.sha256(source.read_bytes()).hexdigest(), asset))
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "logo@example.com")
    try:
        with TestClient(app) as client:
            product = client.post("/v1/products", json={"name": "Logo test", "assetKey": str(asset)}).json()
            assert client.post(f"/v1/products/{product['id']}/approved-image", json={"assetKey": str(asset), "expectedVersion": 0}).status_code == 200
            payload = {"productId": product["id"], "imageVersion": 1, "offer": "Save 20%", "cta": "Shop", "caption": "", "color": "#FFFFFF", "logoAssetKey": str(asset)}
            bad = client.post("/v1/campaigns", json={**payload, "logoAssetKey": str(uuid.uuid4())}, headers={"Idempotency-Key": "bad-logo"})
            assert bad.status_code == 422
            response = client.post("/v1/campaigns", json=payload, headers={"Idempotency-Key": "logo"})
            assert response.status_code == 201, response.text
            campaign = response.json()
            route = f"/v1/campaigns/{campaign['id']}"
            assert campaign["brief"]["logoAssetKey"] == str(asset)
            first = client.post(route + "/layouts", json={"expectedVersion": 1})
            assert first.status_code == 200, first.text
            old_url = first.json()["outputs"]["feed"]["url"]
            old = client.get(old_url).content
            assert Image.open(io.BytesIO(old)).getpixel((540, 70)) == (0, 0, 255)
            edit = {"expectedVersion": 1, "offer": "Save 15%", "cta": "Shop", "caption": "", "color": "#FFFFFF"}
            # Omitted logo preserves it; explicit null removes it in a new version.
            assert client.patch(route, json=edit).json()["brief"]["logoAssetKey"] == str(asset)
            removed = client.patch(route, json={**edit, "expectedVersion": 2, "logoAssetKey": None})
            assert removed.json()["brief"]["logoAssetKey"] is None
            third = client.post(route + "/layouts", json={"expectedVersion": 3}).json()
            assert Image.open(io.BytesIO(client.get(third["outputs"]["feed"]["url"]).content)).getpixel((540, 35)) == (255, 255, 255)
            assert client.get(old_url).content == old
            with psycopg.connect(URL) as c:
                c.execute("UPDATE app.assets SET verification_state='pending' WHERE asset_key=%s", (asset,))
            assert client.patch(route, json={**edit, "expectedVersion": 3, "logoAssetKey": str(asset)}).status_code == 422
            with psycopg.connect(URL) as c:
                c.execute("UPDATE app.assets SET verification_state='verified' WHERE asset_key=%s", (asset,))
            assert client.patch(route, json={**edit, "expectedVersion": 3, "logoAssetKey": str(asset)}).status_code == 200
            Image.new("RGB", (360, 110), "red").save(source)
            assert client.post(route + "/layouts", json={"expectedVersion": 4}).status_code == 422
            assert client.get(route + "/layouts").json()["state"] == "not_generated"
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT count(*) FROM app.jobs WHERE owner_id=%s", (account,)).fetchone()[0] == 1
            assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone()[0] == 0
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.command_keys WHERE account_id=%s", (account,))
            c.execute("DELETE FROM app.campaigns WHERE owner_id=%s", (account,))
            c.execute("DELETE FROM app.product_images WHERE product_id IN (SELECT id FROM app.products WHERE owner_id=%s)", (account,))
            c.execute("DELETE FROM app.products WHERE owner_id=%s", (account,))
