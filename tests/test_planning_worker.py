import uuid
from pathlib import Path
from types import SimpleNamespace

import psycopg
from google.genai import types
from psycopg.types.json import Jsonb

from admaker import creative_planning, provider_graph, worker
from test_provider_graph import provider_job, allow_review
from test_worker_leases import URL, queued_job


def test_worker_resume_keeps_one_plan_submission_and_debit(provider_job, monkeypatch):
    account, job, _, queue = provider_job
    calls = {"plan": 0, "submit": 0, "poll": 0}
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.jobs SET settings=%s WHERE id=%s", (Jsonb({"outputKind": "video", "structuredPlanning": True, "preparedVideoPrompt": "Selected style"}), job))
        inflight = c.execute("SELECT count(*) FROM app.media_review_budget WHERE state='unconfirmed'").fetchone()[0]
    for key, value in {"MEDIA_REVIEW_MODEL": "gemini-fixture", "MEDIA_REVIEW_ESTIMATE_MICROUSD": "1",
        "MEDIA_REVIEW_DAILY_BUDGET_MICROUSD": "1000000000", "MEDIA_REVIEW_MAX_CALLS_PER_RUN": "10",
        "MEDIA_REVIEW_MAX_CONCURRENT_CALLS": str(inflight + 1)}.items():
        monkeypatch.setenv(key, value)
    original = creative_planning.plan_product
    def plan(messages, **kwargs):
        calls["plan"] += 1
        return {"product_summary": "Blue product", "creative_direction": "Slow orbit"}
    monkeypatch.setattr(creative_planning, "plan_product", lambda *args: original(*args, invoke=plan))
    def submit(request, **kwargs):
        calls["submit"] += 1
        assert request.prompt == "Selected style Product summary: Blue product Creative adaptation: Slow orbit"
        return "operations/" + str(uuid.uuid4())
    def poll(name):
        calls["poll"] += 1
        return types.GenerateVideosOperation(name=name, done=calls["poll"] > 1,
            response=types.GenerateVideosResponse(generated_videos=[types.GeneratedVideo(video=types.Video(uri="fake://video"))]) if calls["poll"] > 1 else None)
    monkeypatch.setattr(provider_graph, "compose_video", lambda source, root, output_id, platforms: {"tiktok": {"key": source.relative_to(root).as_posix()}})
    service = SimpleNamespace(submit=submit, poll=poll, download=lambda operation, path: Path(path).write_bytes(b"fixture"))
    options = {"video_service": service, "estimated_cost_microusd": 1, "video_review": allow_review}
    try:
        assert worker.process_one(URL, "planner-first", queue, **options)
        with psycopg.connect(URL) as c:
            c.execute("UPDATE app.job_runs SET lease_until=now()-interval '1 second',next_work_at=now()-interval '1 second' WHERE job_id=%s", (job,))
            c.execute("UPDATE app.job_attempts SET next_poll_at=now()-interval '1 second' WHERE run_id IN (SELECT id FROM app.job_runs WHERE job_id=%s)", (job,))
        assert worker.recover_expired_runs(URL, queue, str(job)) == 1
        assert worker.process_one(URL, "planner-resume", queue, **options)
        assert calls == {"plan": 1, "submit": 1, "poll": 2}
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT state FROM app.jobs WHERE id=%s", (job,)).fetchone() == ("delivered",)
            assert c.execute("SELECT count(*),sum(delta) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (1, -2)
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.media_review_budget WHERE run_id IN (SELECT id FROM app.job_runs WHERE job_id=%s)", (job,))
