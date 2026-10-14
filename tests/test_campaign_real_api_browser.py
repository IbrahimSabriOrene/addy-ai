import uuid
import os
import socket
import subprocess
import shutil
import time
from threading import Thread, Event

import pytest
import uvicorn
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from types import SimpleNamespace

import psycopg
from fastapi.testclient import TestClient
from google.genai import types

from admaker import campaign_pack, creative_planning, provider_graph, worker
from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from test_provider_graph import provider_job, allow_review
from test_worker_leases import URL, queued_job


@pytest.mark.skipif(os.environ.get("RUN_REAL_API_BROWSER_TESTS") != "true", reason="Opt-in real API Chromium integration")
def test_browser_campaign_uses_real_api_and_worker(provider_job, monkeypatch):
    account, old_job, reservation, queue = provider_job
    media_root = Path(os.environ["LOCAL_ASSET_ROOT"]).resolve()
    fixture = media_root / "browser-fixture.mp4"
    subprocess.run(["docker", "run", "--rm", "--network", "none", "--mount",
        f"type=bind,source={media_root},target=/media", "mobileadmaker-api", "ffmpeg",
        "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:r=24:d=8",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=8",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-movflags", "+faststart", "-shortest", "/media/browser-fixture.mp4"], check=True, timeout=90)
    for name, value in {"ENABLE_CAMPAIGN_PACKS": "true", "CAMPAIGN_PACK_CREDITS": "3", "CAMPAIGN_PACK_QUEUE": queue}.items():
        monkeypatch.setenv(name, value)
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "merchant@example.com")
    submissions = []
    plans = []
    with psycopg.connect(URL) as c:
        inflight = c.execute("SELECT count(*) FROM app.media_review_budget WHERE state='unconfirmed'").fetchone()[0]
    for name, value in {"ENABLE_STRUCTURED_PLANNING": "true", "MEDIA_REVIEW_MODEL": "gemini-fixture",
        "MEDIA_REVIEW_ESTIMATE_MICROUSD": "1", "MEDIA_REVIEW_DAILY_BUDGET_MICROUSD": "1000000000",
        "MEDIA_REVIEW_MAX_CALLS_PER_RUN": "10", "MEDIA_REVIEW_MAX_CONCURRENT_CALLS": str(inflight + 1)}.items():
        monkeypatch.setenv(name, value)
    original_plan = creative_planning.plan_product
    def plan(messages, **kwargs):
        plans.append(messages)
        return {"product_summary": "Blue product", "creative_direction": "Gentle orbit around the saved product"}
    monkeypatch.setattr(creative_planning, "plan_product", lambda *args: original_plan(*args, invoke=plan))

    def submit(request, **kwargs):
        assert request.image_bytes
        assert "Slow movement" in request.prompt
        assert "20%" not in request.prompt
        submissions.append(request)
        return "operations/" + str(uuid.uuid4())

    def compose(source, root, output_id, platforms):
        path = root / "generated.mp4"
        shutil.copyfile(fixture, path)
        return {"tiktok": {"key": path.name, "mimeType": "video/mp4"}}

    monkeypatch.setattr(provider_graph, "compose_video", compose)
    monkeypatch.setattr(campaign_pack, "validate_video", lambda *args: {"width": 1080, "height": 1920, "duration": 8, "hasAudio": True})
    def overlay(source, destination, brief):
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / "video.mp4"
        shutil.copyfile(source, path)
        return {"path": str(path), "mimeType": "video/mp4", "offer": brief["offer"], "cta": brief["cta"],
                "width": 1080, "height": 1920, "duration": 8, "hasAudio": True}

    monkeypatch.setattr(campaign_pack, "render_campaign_video", overlay)
    service = SimpleNamespace(submit=submit,
        poll=lambda name: types.GenerateVideosOperation(name=name, done=True, response=types.GenerateVideosResponse(generated_videos=[types.GeneratedVideo(video=types.Video(uri="fake://video"))])),
        download=lambda operation, path: Path(path).write_bytes(b"fake raw"))
    server = None
    server_thread = None
    worker_thread = None
    stop = Event()
    failures = []
    listener = socket.socket()
    listener.bind(("127.0.0.1", 8099))
    try:
        with psycopg.connect(URL) as c:
            asset = c.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (old_job,)).fetchone()[0]
            c.execute("INSERT INTO app.credit_ledger(account_id,delta,event_key) VALUES (%s,10,%s)", (account, str(uuid.uuid4())))
            c.execute("SELECT pgmq.archive(%s,msg_id) FROM pgmq.read(%s,vt=>0,qty=>1)", (queue, queue))
        with TestClient(app) as client:
            product = client.post("/v1/products", json={"name": "Saved product", "assetKey": str(asset)}).json()["id"]
            assert client.post(f"/v1/products/{product}/approved-image", json={"assetKey": str(asset), "expectedVersion": 0}).status_code == 200
        def consume():
            try:
                while not stop.is_set():
                    worker.process_one(URL, "browser-fixture", queue, video_service=service,
                                       estimated_cost_microusd=3, video_review=allow_review)
                    stop.wait(0.2)
            except BaseException as error:
                failures.append(error)

        server = uvicorn.Server(uvicorn.Config(CORSMiddleware(app, allow_origins=["http://localhost:8081"],
            allow_methods=["*"], allow_headers=["*"]), log_level="error"))
        server_thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        server_thread.start()
        deadline = time.monotonic() + 10
        while not server.started and server_thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started
        worker_thread = Thread(target=consume, daemon=True)
        worker_thread.start()
        mobile = Path(__file__).resolve().parents[1] / "mobile"
        env = {**os.environ, "RUN_REAL_API_BROWSER_TESTS": "true", "EXPO_PUBLIC_API_URL": "http://localhost:8099",
               "EXPO_PUBLIC_SUPABASE_URL": "http://localhost:8098", "EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY": "fixture-publishable-key"}
        run = subprocess.run([shutil.which("node"), str(mobile / "node_modules/@playwright/test/cli.js"),
            "test", "e2e/campaign-real-api.spec.ts", "--project=chromium"], cwd=mobile, env=env,
            capture_output=True, text=True, timeout=240)
        assert not failures, failures
        with psycopg.connect(URL) as c:
            states = c.execute("SELECT j.id,j.state,r.state,r.next_work_at,r.lease_until,a.state,a.provider_state,a.provider_error,a.next_poll_at,"
                "(SELECT array_agg(stage_key) FROM app.job_stages WHERE run_id=r.id) "
                "FROM app.jobs j LEFT JOIN app.job_runs r ON r.id=j.active_run_id LEFT JOIN app.job_attempts a ON a.run_id=r.id "
                "WHERE j.owner_id=%s AND j.id<>%s", (account, old_job)).fetchall()
        assert run.returncode == 0, run.stdout + run.stderr + repr(states)
        assert len(submissions) == 1 and len(plans) == 1
        assert "Gentle orbit around the saved product" in submissions[0].prompt
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT count(*),sum(delta) FROM app.credit_ledger WHERE account_id=%s AND delta<0", (account,)).fetchone() == (1, -3)
            assert c.execute("SELECT count(*) FROM app.product_images WHERE product_id=%s", (product,)).fetchone() == (1,)
    finally:
        stop.set()
        if worker_thread:
            worker_thread.join(15)
            assert not worker_thread.is_alive()
        if server:
            server.should_exit = True
        if server_thread:
            server_thread.join(15)
            assert not server_thread.is_alive()
        listener.close()
        app.dependency_overrides.pop(authenticated_subject, None)
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.media_review_budget WHERE run_id IN (SELECT r.id FROM app.job_runs r JOIN app.jobs j ON j.id=r.job_id WHERE j.owner_id=%s)", (account,))
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
