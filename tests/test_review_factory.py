import uuid
from types import SimpleNamespace

import psycopg
from google.genai import types

from admaker import provider_graph, worker
from admaker.media_review import build_media_reviewer
from admaker.veo import VeoRequest
from test_provider_graph import provider_job
from test_worker_leases import URL, queued_job


def test_worker_uses_owned_run_factory_with_durable_review_and_one_settlement(provider_job, monkeypatch, tmp_path):
    account, job, _, queue = provider_job
    for key, value in {"ENABLE_REAL_MEDIA_REVIEW": "true", "MEDIA_REVIEW_ESTIMATE_MICROUSD": "1",
                       "MEDIA_REVIEW_DAILY_BUDGET_MICROUSD": "1000000000", "MEDIA_REVIEW_MAX_CALLS_PER_RUN": "2",
                       "MEDIA_REVIEW_MAX_CONCURRENT_CALLS": "100"}.items():
        monkeypatch.setenv(key, value)
    calls, bindings = [], []
    class Model:
        def __init__(self, **kwargs):
            pass
        def with_structured_output(self, *args, **kwargs):
            return self
        def invoke(self, messages, config):
            calls.append(messages)
            return {"policyAllowed": True, "qualityPassed": True, "offerFree": True}
    monkeypatch.setattr("langchain_google_genai.ChatGoogleGenerativeAI", Model)
    monkeypatch.setattr("admaker.media_review.validate_video", lambda *args: {"hasAudio": True})
    def compose(*args):
        path = tmp_path / "video.mp4"
        path.write_bytes(b"fixture codec boundary")
        return {"tiktok": {"key": path.name}}
    monkeypatch.setattr(provider_graph, "compose_video", compose)
    def factory(database_url, bound_job, run):
        assert database_url == URL and str(bound_job) == str(job)
        bindings.append(run)
        return build_media_reviewer(database_url, bound_job, run, "gemini-fixture")
    service = SimpleNamespace(submit=lambda *args, **kwargs: "operations/" + str(uuid.uuid4()),
        poll=lambda name: types.GenerateVideosOperation(name=name, done=True, response=types.GenerateVideosResponse(
            generated_videos=[types.GeneratedVideo(video=types.Video(uri="fake://video"))])), download=lambda *args: None)
    try:
        assert worker.process_one(URL, "factory", queue, video_service=service, video_request=VeoRequest("Fixture"),
                                  estimated_cost_microusd=1, video_review_factory=factory)
        assert len(calls) == 2 and len(bindings) == 1  # Input gate, then generated output review.
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT state FROM app.jobs WHERE id=%s", (job,)).fetchone() == ("delivered",)
            assert c.execute("SELECT state,verdict->>'offerFree' FROM app.media_review_budget WHERE run_id=%s", (bindings[0],)).fetchall() == [("finished", "true"), ("finished", "true")]
            assert c.execute("SELECT count(*),sum(delta) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (1, -2)
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.media_review_budget WHERE run_id IN (SELECT id FROM app.job_runs WHERE job_id=%s)", (job,))
