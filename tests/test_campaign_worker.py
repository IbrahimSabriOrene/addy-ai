import uuid
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from google.genai import types
from psycopg.types.json import Jsonb

from admaker import campaign_worker, provider_graph, worker
from admaker.veo import VeoRequest
from test_provider_graph import provider_job, Crash
from test_worker_leases import URL, queued_job


def test_pack_retry_and_crash_reuse_video_before_one_settlement(provider_job, monkeypatch):
    account, job, reservation, queue = provider_job
    calls = {"submit": 0, "pack": 0, "review": 0}
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.jobs SET settings=%s WHERE id=%s", (Jsonb({"generationKind": "campaign_pack", "campaignBrief": {"offer": "20%"}}), job))
    with pytest.raises(ValueError, match="configured provider worker"):
        worker.process_one(URL, "fixture", queue)

    def submit(*args, **kwargs):
        calls["submit"] += 1
        return "operations/" + str(uuid.uuid4())

    def pack(*args):
        calls["pack"] += 1
        if calls["pack"] == 1:
            raise OSError("Temporary layout storage failure")
        manifest = {"cleanImage": {"key": "test.png"}, "video": {"key": "video.mp4"},
                "story": {"key": "story.png"}, "feed": {"key": "feed.png"}, "copy": {"caption": "Caption", "cta": "Shop"}}
        for kind in ("cleanImage", "video", "story", "feed"):
            path = Path(os.environ["LOCAL_ASSET_ROOT"]) / manifest[kind]["key"]
            if not path.exists():
                path.write_bytes(b"fixture output")
            manifest[kind]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        return manifest

    def review(*args):
        calls["review"] += 1
        return {"policyAllowed": True, "qualityPassed": True}

    service = SimpleNamespace(submit=submit,
        poll=lambda name: types.GenerateVideosOperation(name=name, done=True, response=types.GenerateVideosResponse(
            generated_videos=[types.GeneratedVideo(video=types.Video(uri="fake://video"))])),
        download=lambda *args: None)
    monkeypatch.setattr(provider_graph, "compose_video", lambda *args: {"tiktok": {"key": "video.mp4"}})
    monkeypatch.setattr(campaign_worker, "compose_campaign_pack", pack)
    options = dict(video_service=service, video_request=VeoRequest("Fixture"), estimated_cost_microusd=3, video_review=review)
    assert worker.process_one(URL, "first", queue, **options)
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT state FROM app.jobs WHERE id=%s", (job,)).fetchone() == ("running",)
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("held",)
        assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)

    def due():
        with psycopg.connect(URL) as c:
            c.execute("UPDATE app.job_runs SET lease_until=clock_timestamp()-interval '1 second',next_work_at=clock_timestamp()-interval '1 second' WHERE job_id=%s", (job,))
        assert worker.recover_expired_runs(URL, queue, str(job)) == 1

    original = campaign_worker.finish_campaign_pack

    def crash(*args):
        original(*args)
        raise Crash()

    due()
    monkeypatch.setattr(campaign_worker, "finish_campaign_pack", crash)
    with pytest.raises(Crash):
        worker.process_one(URL, "second", queue, **options)
    monkeypatch.setattr(campaign_worker, "finish_campaign_pack", original)
    due()
    assert worker.process_one(URL, "third", queue, **options)
    assert calls == {"submit": 1, "pack": 2, "review": 2}
    with psycopg.connect(URL) as c:
        state, result = c.execute("SELECT state,result FROM app.jobs WHERE id=%s", (job,)).fetchone()
        assert state == "delivered"
        assert set(result["exports"]) == {"cleanImage", "video", "story", "feed", "copy"}
        assert c.execute("SELECT count(*),sum(delta) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (1, -2)
        assert c.execute("SELECT count(*) FROM app.job_attempts WHERE run_id IN (SELECT id FROM app.job_runs WHERE job_id=%s)", (job,)).fetchone() == (1,)
