import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from admaker.api import app, CampaignRequest
from admaker.auth import Subject, authenticated_subject
from admaker.brand import BrandProfile
from admaker.campaign_layouts import render_campaign_layouts
from admaker.db import migrate


def test_brand_validation_and_rendered_snapshot(tmp_path):
    with pytest.raises(ValidationError):
        BrandProfile(font="../../font.ttf")
    with pytest.raises(ValidationError):
        BrandProfile(contact="bad\x00contact")
    product = tmp_path / "product.png"
    Image.new("RGB", (80, 120), "blue").save(product)
    brief = {"offer": "15% off", "cta": "Shop", "color": "#FFFFEE"}
    plain = render_campaign_layouts(product, tmp_path / "plain", brief)
    branded = render_campaign_layouts(product, tmp_path / "brand", {**brief, "font": "serif", "contact": "shop.example"})
    assert Image.open(plain["feed"]["path"]).tobytes() != Image.open(branded["feed"]["path"]).tobytes()
    assert branded["story"]["offer"] == "15% off"
    # New optional fields must not change old paid-command request hashes.
    request = CampaignRequest(productId=uuid.uuid4(), imageVersion=1)
    assert "font" not in request.model_dump(exclude_none=True)
    assert "contact" not in request.model_dump(exclude_none=True)


def test_private_brand_and_campaign_snapshots(monkeypatch):
    url = "postgresql://postgres:postgres@localhost:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", url)
    migrate()
    owner = Subject(str(uuid.uuid4()), "brand@example.com")
    other = Subject(str(uuid.uuid4()), "other-brand@example.com")
    assets = [uuid.uuid4(), uuid.uuid4()]
    with psycopg.connect(url) as c:
        for person, asset in zip((owner, other), assets):
            c.execute("INSERT INTO app.accounts(id,email) VALUES (%s,%s)", (person.id, person.email))
            c.execute("INSERT INTO app.assets(asset_key,owner_id,storage_key,mime_type,verification_state) VALUES (%s,%s,%s,'image/png','verified')", (asset, person.id, str(asset)))
    app.dependency_overrides[authenticated_subject] = lambda: owner
    try:
        with TestClient(app) as client:
            assert client.get("/v1/account/brand").json()["version"] == 0
            profile = {"name": "Studio", "font": "serif", "contact": "shop.example", "color": "#123456", "logoAssetKey": str(assets[0])}
            assert client.put("/v1/account/brand", json={**profile, "logoAssetKey": str(assets[1]), "expectedVersion": 0}).status_code == 422
            result = client.put("/v1/account/brand", json={**profile, "expectedVersion": 0})
            assert result.status_code == 200, result.text
            assert client.get("/v1/account/brand").json() == result.json()
            assert client.put("/v1/account/brand", json={**profile, "expectedVersion": 0}).status_code == 409
            product = client.post("/v1/products", json={"name": "Cream", "assetKey": str(assets[0])}).json()["id"]
            client.post(f"/v1/products/{product}/approved-image", json={"assetKey": str(assets[0]), "expectedVersion": 0})
            brief = {key: value for key, value in profile.items() if key != "name"}
            payload = {**brief, "productId": product, "imageVersion": 1, "offer": "20% off"}
            first = client.post("/v1/campaigns", json=payload, headers={"Idempotency-Key": "first"}).json()
            assert first["brief"]["font"] == "serif"
            client.put("/v1/account/brand", json={**profile, "contact": "new.example", "expectedVersion": 1})
            assert client.get(f"/v1/campaigns/{first['id']}").json()["brief"]["contact"] == "shop.example"
            payload["offer"] = "15% off"
            second = client.post("/v1/campaigns", json=payload, headers={"Idempotency-Key": "copy"})
            assert second.status_code == 201
            assert second.json()["id"] != first["id"]
            assert second.json()["assetKey"] == first["assetKey"]
            assert client.post("/v1/campaigns", json=payload, headers={"Idempotency-Key": "copy"}).json() == second.json()
            assert client.get(f"/v1/campaigns/{first['id']}").json()["brief"]["offer"] == "20% off"
            app.dependency_overrides[authenticated_subject] = lambda: other
            assert client.get("/v1/account/brand").json()["version"] == 0
            assert client.get(f"/v1/campaigns/{first['id']}").status_code == 404
            with psycopg.connect(url) as c:
                assert c.execute("SELECT count(*) FROM app.jobs WHERE owner_id=%s", (owner.id,)).fetchone()[0] == 0
                assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (owner.id,)).fetchone()[0] == 0
    finally:
        app.dependency_overrides.clear()
        with psycopg.connect(url) as c:
            for table, column in (("campaigns", "owner_id"), ("command_keys", "account_id"), ("product_images", "owner_id"), ("products", "owner_id"), ("brand_profiles", "account_id"), ("assets", "owner_id"), ("accounts", "id")):
                from psycopg import sql
                c.execute(sql.SQL("DELETE FROM app.{} WHERE {}=ANY(%s::uuid[])").format(sql.Identifier(table), sql.Identifier(column)), ([owner.id, other.id],))
