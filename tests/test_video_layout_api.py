import hashlib
import json
import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient
from PIL import Image

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("cloud", [False, True])
def test_video_edits_bind_review_and_version_and_replay_without_charge(queued_job, monkeypatch, tmp_path, cloud):
    account, job, _, _ = queued_job
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("LOCAL_ASSET_ROOT", str(tmp_path))
    monkeypatch.setenv("PUBLISH_PRIVATE_OUTPUTS", "false")
    Image.new("RGB", (32, 32), "blue").save(tmp_path / "test.png")
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "video-layout@test.example")
    renders = []
    class Store:
        origin, bucket = "https://video-edit.test", "private"
        objects = {}
        lost = True
        uploads = 0
        def upload(self, key, content, content_type):
            self.objects[key] = content
            self.uploads += 1
            if self.lost and content_type == "video/mp4":
                self.lost = False
                raise OSError("Lost video upload acknowledgement")
        def download(self, key, max_bytes=None):
            return self.objects.get(key)
        def signed_download(self, key, expires_in):
            return f"https://video-edit.test/{key}?token=fixture"
    store = Store()
    monkeypatch.setattr("admaker.cloud_objects.configured_cloud_storage", lambda: store)
    def render(source, destination, brief):
        renders.append(brief["offer"])
        destination.mkdir(parents=True)
        path = destination / "video.mp4"
        path.write_bytes(brief["offer"].encode())
        return {"path": str(path), "mimeType": "video/mp4", "offer": brief["offer"], "cta": brief["cta"], "width": 1080, "height": 1920, "hasAudio": True, "duration": 8}
    monkeypatch.setattr("admaker.campaign_video.render_campaign_video", render)
    try:
        with psycopg.connect(URL) as c:
            asset = str(c.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (job,)).fetchone()[0])
        with TestClient(app) as client:
            product = client.post("/v1/products", json={"name": "Bottle", "assetKey": asset}).json()["id"]
            assert client.post(f"/v1/products/{product}/approved-image", json={"assetKey": asset, "expectedVersion": 0}).status_code == 200
            campaign = client.post("/v1/campaigns", json={"productId": product, "imageVersion": 1, "offer": "20%"}, headers={"Idempotency-Key": "video-edit"}).json()["id"]
            run = uuid.uuid4()
            source = tmp_path / "original.mp4"
            source.write_bytes(b"reviewed source; fake codec boundary")
            exports = {"tiktok": {"key": source.name}}
            pack = {"video": {"key": "old-offer.mp4"}}
            review = {"offerFree": False, "policyAllowed": True, "technicalPassed": True,
                      "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                      "exportsHash": hashlib.sha256(json.dumps(exports, sort_keys=True).encode()).hexdigest()}
            with psycopg.connect(URL) as c:
                c.execute("UPDATE app.jobs SET state='delivered',settings=%s,result=%s WHERE id=%s", (Jsonb({"generationKind": "campaign_pack", "productId": product, "imageVersion": 1, "campaignBrief": {}}), Jsonb({"exports": pack}), job))
                c.execute("INSERT INTO app.campaign_generations(campaign_id,campaign_version,job_id,price_credits) VALUES (%s,1,%s,2)", (campaign, job))
                c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state,lease_owner,lease_until,fence) VALUES (%s,%s,1,%s,'running','fixture',clock_timestamp()+interval '1 minute',1)", (run, job, str(run)))
                for stage, value in (("campaign_pack_compose", pack), ("provider_compose", exports), ("candidate_review", review)):
                    c.execute("INSERT INTO app.job_stages(run_id,stage_key,request_hash,result,fence) VALUES (%s,%s,'fixture',%s,1)", (run, stage, Jsonb(value)))
            route = f"/v1/campaigns/{campaign}/video-layout"
            body = {"expectedVersion": 1, "sourceVersion": 1}
            assert client.post(route, json=body).status_code == 409  # Images first.
            assert client.post(f"/v1/campaigns/{campaign}/layouts", json={"expectedVersion": 1}).status_code == 200
            assert client.post(route, json=body).status_code == 409  # No trusted offer-free proof.
            assert not renders
            review["offerFree"] = True
            with psycopg.connect(URL) as c:
                c.execute("UPDATE app.job_stages SET result=%s WHERE run_id=%s AND stage_key='candidate_review'", (Jsonb(review), run))
            first = client.post(route, json=body)
            if cloud:
                # Enable after a committed local render, then lose its upload response.
                monkeypatch.setenv("PUBLISH_PRIVATE_OUTPUTS", "true")
                assert client.post(route, json=body).status_code == 503
                assert renders == ["20%"]
                first = client.post(route, json=body)
                assert store.uploads == 3  # Story/feed/video, including recovered video.
            assert first.status_code == 200, first.text
            assert client.post(route, json=body).json() == first.json()
            video = first.json()["outputs"]["video"]
            download = client.get(video["url"], follow_redirects=False)
            assert download.status_code == (302 if cloud else 200)
            if not cloud:
                assert download.headers["content-type"] == "video/mp4"
            assert "key" not in first.text and "original.mp4" not in first.text
            assert client.post(route, json={**body, "sourceVersion": 2}).status_code == 409
            edit = {"expectedVersion": 1, "offer": "15%", "cta": "Shop", "caption": "", "color": "#FFFFFF"}
            assert client.patch(f"/v1/campaigns/{campaign}", json=edit).status_code == 200
            assert client.post(route, json=body).status_code == 409
            assert client.post(f"/v1/campaigns/{campaign}/layouts", json={"expectedVersion": 2}).status_code == 200
            original = source.read_bytes()
            source.write_bytes(b"changed speech")
            assert client.post(route, json={**body, "expectedVersion": 2}).status_code == 503
            source.write_bytes(original)
            second = client.post(route, json={**body, "expectedVersion": 2})
            assert second.status_code == 200, second.text
            assert second.json()["outputs"]["video"]["offer"] == "15%"
            if cloud:
                assert client.get(video["url"], follow_redirects=False).status_code == 302
                with psycopg.connect(URL) as c:
                    manifest = c.execute("SELECT manifest FROM app.campaign_layouts WHERE campaign_id=%s AND version=1", (campaign,)).fetchone()[0]
                    remote = c.execute("SELECT object_key FROM app.cloud_objects WHERE account_id=%s AND local_key=%s", (account, manifest["video"]["key"])).fetchone()[0]
                assert store.objects[remote] == b"20%"
                assert store.uploads == 6
            else:
                assert client.get(video["url"]).content == b"20%"
            assert renders == ["20%", "15%"]
            app.dependency_overrides[authenticated_subject] = lambda: Subject(str(uuid.uuid4()), "other@test.example")
            assert client.post(route, json={**body, "expectedVersion": 2}).status_code == 404
            assert client.get(video["url"]).status_code == 404
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT count(*) FROM app.jobs WHERE owner_id=%s", (account,)).fetchone() == (1,)
            assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.cloud_objects WHERE account_id=%s", (account,))
            c.execute("DELETE FROM app.campaign_generations WHERE job_id=%s", (job,))
            c.execute("DELETE FROM app.command_keys WHERE account_id=%s", (account,))
            c.execute("DELETE FROM app.campaigns WHERE owner_id=%s", (account,))
            c.execute("DELETE FROM app.product_images WHERE owner_id=%s", (account,))
            c.execute("DELETE FROM app.products WHERE owner_id=%s", (account,))
