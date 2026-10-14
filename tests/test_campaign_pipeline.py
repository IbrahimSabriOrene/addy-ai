import uuid
from pathlib import Path
from types import SimpleNamespace

import psycopg
from fastapi.testclient import TestClient
from google.genai import types

from admaker import campaign_pack, provider_graph, worker
from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from test_provider_graph import provider_job, allow_review
from test_worker_leases import URL, queued_job


def test_api_worker_pack_and_offer_edit_share_one_paid_video(provider_job, monkeypatch):
    account, old_job, reservation, queue = provider_job
    for name, value in {"ENABLE_CAMPAIGN_PACKS": "true", "CAMPAIGN_PACK_CREDITS": "3", "CAMPAIGN_PACK_QUEUE": queue}.items():
        monkeypatch.setenv(name, value)
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "merchant@example.com")
    submissions = []

    def submit(request, **kwargs):
        assert request.image_bytes
        assert "Slow movement" in request.prompt
        assert "20%" not in request.prompt
        submissions.append(request)
        return "operations/" + str(uuid.uuid4())

    def compose(source, root, output_id, platforms):
        path = root / "generated.mp4"
        path.write_bytes(b"Injected video bytes; actual MP4 validation has separate Docker tests")
        return {"tiktok": {"key": path.name, "mimeType": "video/mp4"}}

    monkeypatch.setattr(provider_graph, "compose_video", compose)
    monkeypatch.setattr(campaign_pack, "validate_video", lambda *args: {"width": 1080, "height": 1920, "duration": 8, "hasAudio": True})
    def overlay(source, destination, brief):
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / "video.mp4"
        path.write_bytes(brief["offer"].encode())
        return {"path": str(path), "mimeType": "video/mp4", "offer": brief["offer"], "cta": brief["cta"],
                "width": 1080, "height": 1920, "duration": 8, "hasAudio": True}
    monkeypatch.setattr(campaign_pack, "render_campaign_video", overlay)
    monkeypatch.setattr("admaker.campaign_video.render_campaign_video", overlay)
    service = SimpleNamespace(submit=submit,
        poll=lambda name: types.GenerateVideosOperation(name=name, done=True, response=types.GenerateVideosResponse(generated_videos=[types.GeneratedVideo(video=types.Video(uri="fake://video"))])),
        download=lambda operation, path: Path(path).write_bytes(b"fake raw"))
    try:
        with psycopg.connect(URL) as c:
            asset = c.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (old_job,)).fetchone()[0]
            c.execute("INSERT INTO app.credit_ledger(account_id,delta,event_key) VALUES (%s,10,%s)", (account, str(uuid.uuid4())))
            c.execute("SELECT pgmq.archive(%s,msg_id) FROM pgmq.read(%s,vt=>0,qty=>1)", (queue, queue))
        with TestClient(app) as client:
            product = client.post("/v1/products", json={"name": "Saved product", "assetKey": str(asset)}).json()["id"]
            assert client.post(f"/v1/products/{product}/approved-image", json={"assetKey": str(asset), "expectedVersion": 0}).status_code == 200
            base = {"productId": product, "imageVersion": 1, "templateId": "pedestal_spin", "templateVersion": 1}
            campaign = client.post("/v1/campaigns", json={**base, "offer": "20% off", "instructions": "Slow movement", "caption": "Caption", "cta": "Shop"}, headers={"Idempotency-Key": "campaign"}).json()["id"]
            path = f"/v1/campaigns/{campaign}"
            assert client.get(path + "/generation-quote").json()["priceCredits"] == 3
            accepted = client.post(path + "/generate", json={"expectedVersion": 1, "confirmedCredits": 3}, headers={"Idempotency-Key": "generate"})
            assert accepted.status_code == 202
            assert worker.process_one(URL, "pipeline", queue, video_service=service, estimated_cost_microusd=3,
                video_review=lambda root, exports: {"policyAllowed": True, "qualityPassed": True, "offerFree": "tiktok" in exports})
            result = client.get(path + "/generations/1").json()
            assert result["state"] == "delivered"
            assert set(result["outputs"]) == {"cleanImage", "video", "story", "feed", "copy"}
            assert all(item["state"] == "ready" for item in result["outputs"].values())
            before_video = client.get(result["outputs"]["video"]["url"]).content
            for kind in ("cleanImage", "story", "feed"):
                assert client.get(result["outputs"][kind]["url"]).status_code == 200
            edited = client.patch(path, json={"expectedVersion": 1, "offer": "15% off", "caption": "New caption", "cta": "Explore", "color": "#FFFFFF"})
            assert edited.status_code == 200
            layouts = client.post(path + "/layouts", json={"expectedVersion": 2}).json()
            assert layouts["outputs"]["story"]["offer"] == "15% off"
            video_edit = client.post(path + "/video-layout", json={"expectedVersion": 2, "sourceVersion": 1})
            assert video_edit.status_code == 200, video_edit.text
            assert client.get(video_edit.json()["outputs"]["video"]["url"]).content == b"15% off"
            assert client.get(path + "/generations/1").json()["outputs"]["story"]["offer"] == "20% off"
            assert client.get(result["outputs"]["video"]["url"]).content == before_video
            second = client.post("/v1/campaigns", json=base, headers={"Idempotency-Key": "second-campaign"}).json()
            assert second["brief"]["offer"] == "" and second["assetKey"] == str(asset)
        assert len(submissions) == 1
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT count(*),sum(delta) FROM app.credit_ledger WHERE account_id=%s AND delta<0", (account,)).fetchone() == (1, -3)
            assert c.execute("SELECT count(*) FROM app.product_images WHERE product_id=%s", (product,)).fetchone() == (1,)
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.campaign_generations WHERE campaign_id IN (SELECT id FROM app.campaigns WHERE owner_id=%s)", (account,))
            c.execute("UPDATE app.jobs SET active_run_id=NULL WHERE owner_id=%s AND id<>%s", (account, old_job))
            c.execute("DELETE FROM app.job_attempts WHERE run_id IN (SELECT id FROM app.job_runs WHERE job_id IN (SELECT id FROM app.jobs WHERE owner_id=%s AND id<>%s))", (account, old_job))
            c.execute("DELETE FROM app.job_runs WHERE job_id IN (SELECT id FROM app.jobs WHERE owner_id=%s AND id<>%s)", (account, old_job))
            c.execute("DELETE FROM app.credit_reservations WHERE account_id=%s AND job_id<>%s", (account, old_job))
            c.execute("DELETE FROM app.jobs WHERE owner_id=%s AND id<>%s", (account, old_job))
            c.execute("DELETE FROM app.command_keys WHERE account_id=%s", (account,))
            c.execute("DELETE FROM app.campaigns WHERE owner_id=%s", (account,))
            c.execute("DELETE FROM app.product_images WHERE owner_id=%s", (account,))
            c.execute("DELETE FROM app.products WHERE owner_id=%s", (account,))
