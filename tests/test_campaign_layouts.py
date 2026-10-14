import hashlib
import io
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from test_worker_leases import URL, queued_job


def test_layout_font_and_bounded_long_text(tmp_path):
    import pytest
    from admaker.campaign_layouts import render_campaign_layouts

    source = tmp_path / "product.png"
    Image.new("RGB", (80, 120), "blue").save(source)
    brief = {"offer": "W" * 300, "cta": "Şimdi keşfet " * 7, "color": "#FFFFFF"}
    outputs = render_campaign_layouts(source, tmp_path / "outputs", brief)
    assert Image.open(outputs["feed"]["path"]).size == (1080, 1080)
    assert outputs["story"]["offer"] == brief["offer"]
    with pytest.raises(ValueError):
        render_campaign_layouts(source, tmp_path / "invalid", {**brief, "offer": "too\x00long"})


def test_layout_versions_reuse_approved_image_and_never_generate_video(queued_job, monkeypatch, tmp_path):
    account, job, reservation, queue = queued_job
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("LOCAL_ASSET_ROOT", str(tmp_path))
    source = tmp_path / "test.png"
    product = Image.new("RGB", (300, 420), "white")
    ImageDraw.Draw(product).rounded_rectangle((85, 40, 215, 390), radius=24, fill="#2865a3")
    product.save(source)
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    with psycopg.connect(URL) as c:
        asset = c.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (job,)).fetchone()[0]
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "layout@example.com")
    try:
        with TestClient(app) as client:
            saved = client.post("/v1/products", json={"name": "Bottle", "assetKey": str(asset)}).json()
            assert client.post(f"/v1/products/{saved['id']}/approved-image", json={"assetKey": str(asset), "expectedVersion": 0}).status_code == 200
            brief = {"productId": saved["id"], "imageVersion": 1, "offer": "Yaza özel\n%20 indirim", "cta": "Hemen keşfet", "caption": "Campaign caption", "color": "#25B99A"}
            campaign = client.post("/v1/campaigns", json=brief, headers={"Idempotency-Key": "layout-campaign"}).json()
            route = f"/v1/campaigns/{campaign['id']}/layouts"
            assert client.get(route).json()["state"] == "not_generated"
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(lambda _: client.post(route, json={"expectedVersion": 1}), range(2)))
            first = responses[0]
            assert first.status_code == 200, first.text
            assert responses[1].json() == first.json()
            assert client.get(route).json() == first.json()
            assert client.post(route, json={"expectedVersion": 1}).json() == first.json()
            assert "key" not in str(first.json()) and str(tmp_path) not in first.text
            old_bytes = {}
            for kind, height in (("story", 1920), ("feed", 1080)):
                output = first.json()["outputs"][kind]
                assert output["offer"] == brief["offer"] and output["cta"] == brief["cta"]
                response = client.get(output["url"])
                assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
                assert Image.open(io.BytesIO(response.content)).size == (1080, height)
                old_bytes[kind] = response.content
            updated = {"expectedVersion": 1, "offer": "%15 indirim", "cta": brief["cta"], "caption": brief["caption"], "color": brief["color"]}
            assert client.patch(f"/v1/campaigns/{campaign['id']}", json=updated).status_code == 200
            assert client.post(route, json={"expectedVersion": 1}).status_code == 409
            second = client.post(route, json={"expectedVersion": 2}).json()
            assert client.get(second["outputs"]["story"]["url"]).content != old_bytes["story"]
            assert client.get(first.json()["outputs"]["story"]["url"]).content == old_bytes["story"]
            assert hashlib.sha256(source.read_bytes()).hexdigest() == checksum
            assert client.patch(f"/v1/campaigns/{campaign['id']}", json={**updated, "expectedVersion": 2, "offer": "\U0010ffff"}).status_code == 200
            assert client.post(route, json={"expectedVersion": 3}).status_code == 422
            assert client.get(route).json()["state"] == "not_generated"
            app.dependency_overrides[authenticated_subject] = lambda: Subject(str(uuid.uuid4()), "other@example.com")
            assert client.post(route, json={"expectedVersion": 2}).status_code == 404
            assert client.get(first.json()["outputs"]["story"]["url"]).status_code == 404
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
