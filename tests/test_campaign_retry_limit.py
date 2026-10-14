import uuid
from types import SimpleNamespace

import psycopg
from google.genai import types
from psycopg.types.json import Jsonb

from admaker import campaign_worker, provider_graph, worker
from admaker.veo import VeoRequest
from test_provider_graph import provider_job, allow_review
from test_worker_leases import URL, queued_job


def test_three_pack_failures_pause_without_resubmission_or_debit(provider_job, monkeypatch):
    account, job, reservation, queue = provider_job
    calls = {"submit": 0, "pack": 0}
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.jobs SET settings=%s WHERE id=%s", (Jsonb({"generationKind": "campaign_pack", "campaignBrief": {}}), job))

    def submit(*args, **kwargs):
        calls["submit"] += 1
        return "operations/" + str(uuid.uuid4())

    def pack(*args):
        calls["pack"] += 1
        raise OSError("Persistent local storage failure")

    service = SimpleNamespace(submit=submit,
        poll=lambda name: types.GenerateVideosOperation(name=name, done=True, response=types.GenerateVideosResponse(
            generated_videos=[types.GeneratedVideo(video=types.Video(uri="fake://video"))])),
        download=lambda *args: None)
    monkeypatch.setattr(provider_graph, "compose_video", lambda *args: {"tiktok": {"key": "video.mp4"}})
    monkeypatch.setattr(campaign_worker, "compose_campaign_pack", pack)
    for index in range(3):
        if index:
            with psycopg.connect(URL) as c:
                c.execute("UPDATE app.job_runs SET lease_until=clock_timestamp()-interval '1 second',next_work_at=clock_timestamp()-interval '1 second' WHERE job_id=%s", (job,))
            assert worker.recover_expired_runs(URL, queue, str(job)) == 1
        assert worker.process_one(URL, f"worker-{index}", queue, video_service=service,
            video_request=VeoRequest("Fixture"), estimated_cost_microusd=3, video_review=allow_review)
    assert calls == {"submit": 1, "pack": 3}
    assert worker.recover_expired_runs(URL, queue, str(job)) == 0
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT state FROM app.job_runs WHERE job_id=%s", (job,)).fetchone() == ("review_required",)
        state, result = c.execute("SELECT state,result FROM app.jobs WHERE id=%s", (job,)).fetchone()
        assert state == "failed" and result["failure"]["code"] == "campaign_pack_incomplete"
        assert "reserved credits remain held" in result["failure"]["message"]
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("held",)
        assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
        assert c.execute("SELECT result FROM app.job_stages WHERE run_id IN (SELECT id FROM app.job_runs WHERE job_id=%s) AND stage_key='campaign_pack_failures'", (job,)).fetchone() == ({"count": 3},)
        assert c.execute("SELECT count(*) FROM app.job_stages WHERE run_id IN (SELECT id FROM app.job_runs WHERE job_id=%s) AND stage_key='provider_compose'", (job,)).fetchone() == (1,)
