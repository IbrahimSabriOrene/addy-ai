import uuid
import hashlib

import psycopg
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from test_worker_leases import URL, queued_job


def test_campaign_outputs_are_private_versioned_and_incomplete_on_file_loss(queued_job, monkeypatch, tmp_path):
    account, job, reservation, queue = queued_job
    product, campaign = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("LOCAL_ASSET_ROOT", str(tmp_path))
    (tmp_path / "private.png").write_bytes(b"fixture image")
    (tmp_path / "private.mp4").write_bytes(b"fixture video")
    manifest = {kind: {"key": "private.png", "mimeType": "image/png", "width": 1080, "privatePrompt": "secret"} for kind in ("cleanImage", "story", "feed")}
    manifest.update(video={"key": "private.mp4", "mimeType": "video/mp4", "hasAudio": True}, copy={"caption": "Caption", "cta": "Shop"})
    manifest["video"]["sha256"] = hashlib.sha256(b"fixture video").hexdigest()
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "test@example.com")
    try:
        with psycopg.connect(URL) as c:
            asset = c.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (job,)).fetchone()[0]
            c.execute("INSERT INTO app.products(id,owner_id,name,source_asset_id) VALUES (%s,%s,'Fixture',%s)", (product, account, asset))
            c.execute("INSERT INTO app.product_images(product_id,owner_id,version,asset_key) VALUES (%s,%s,1,%s)", (product, account, asset))
            c.execute("INSERT INTO app.campaigns(id,owner_id,product_id,image_version,brief) VALUES (%s,%s,%s,1,'{}')", (campaign, account, product))
            c.execute("INSERT INTO app.campaign_generations(campaign_id,campaign_version,job_id,price_credits) VALUES (%s,1,%s,3)", (campaign, job))
            c.execute("UPDATE app.jobs SET state='delivered',result=%s WHERE id=%s", (Jsonb({"exports": manifest}), job))
        url = f"/v1/campaigns/{campaign}/generations/1"
        with TestClient(app) as client:
            response = client.get(url)
            assert response.status_code == 200
            assert response.json()["state"] == "delivered"
            assert len(response.json()["outputs"]) == 5
            assert "private.png" not in response.text and "secret" not in response.text
            for kind in ("cleanImage", "video", "story", "feed"):
                downloaded = client.get(response.json()["outputs"][kind]["url"])
                assert downloaded.status_code == 200
                assert downloaded.headers["cache-control"] == "private, no-store"
            assert client.get(url + "/copy").status_code == 404
            (tmp_path / "private.mp4").write_bytes(b"changed")
            assert client.get(url + "/video").status_code == 503
            (tmp_path / "private.mp4").write_bytes(b"fixture video")
            assert client.get(url.replace("/1", "/2")).status_code == 404
            app.dependency_overrides[authenticated_subject] = lambda: Subject(str(uuid.uuid4()), "other@example.com")
            assert client.get(url).status_code == 404
            assert client.get(url + "/video").status_code == 404
            app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "test@example.com")
            (tmp_path / "private.mp4").unlink()
            assert client.get(url).json()["state"] == "incomplete"
            assert client.get(url).json()["outputs"]["video"]["state"] == "unavailable"
            assert client.get(url + "/video").status_code == 404
            with psycopg.connect(URL) as c:
                c.execute("UPDATE app.jobs SET state='running' WHERE id=%s", (job,))
            assert all(item["state"] == "pending" for item in client.get(url).json()["outputs"].values())
            assert client.get(url + "/story").status_code == 404
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.campaign_generations WHERE campaign_id=%s", (campaign,))
            c.execute("DELETE FROM app.campaigns WHERE id=%s", (campaign,))
            c.execute("DELETE FROM app.product_images WHERE product_id=%s", (product,))
            c.execute("DELETE FROM app.products WHERE id=%s", (product,))
