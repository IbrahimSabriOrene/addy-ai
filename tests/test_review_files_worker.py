from contextlib import contextmanager
from types import SimpleNamespace

import psycopg
from google.genai import types

from admaker import provider_graph, worker
from admaker.media_review import build_media_reviewer
from admaker.veo import VeoRequest
from test_review_files import file_store
from test_provider_graph import provider_job
from test_worker_leases import URL, queued_job


def test_processing_file_defers_then_resumes_same_generation(provider_job, file_store, monkeypatch, tmp_path):
    account, job, reservation, queue = provider_job
    for key, value in {"ENABLE_REAL_MEDIA_REVIEW": "true", "MEDIA_REVIEW_ESTIMATE_MICROUSD": "1",
        "MEDIA_REVIEW_DAILY_BUDGET_MICROUSD": "1000000000", "MEDIA_REVIEW_MAX_CALLS_PER_RUN": "3",
        "MEDIA_REVIEW_MAX_CONCURRENT_CALLS": "10"}.items():
        monkeypatch.setenv(key, value)
    @contextmanager
    def client():
        yield file_store
    monkeypatch.setattr("admaker.media_review.review_file_client", client)
    monkeypatch.setattr("admaker.media_review.validate_video", lambda path: {"hasAudio": True})
    calls, submissions, compositions = [], [], []
    class Model:
        def __init__(self, **kwargs):
            pass
        def with_structured_output(self, *args, **kwargs):
            return self
        def invoke(self, *args, **kwargs):
            calls.append(True)
            return {"policyAllowed": True, "qualityPassed": True, "offerFree": True}
    monkeypatch.setattr("langchain_google_genai.ChatGoogleGenerativeAI", Model)
    def compose(*args):
        compositions.append(True)
        path = tmp_path / "large.mp4"
        path.write_bytes(b"v" * (65 * 1024 * 1024))
        return {"tiktok": {"key": path.name}}
    monkeypatch.setattr(provider_graph, "compose_video", compose)
    def submit(*args, **kwargs):
        submissions.append(True)
        return "operations/fixture-files"
    service = SimpleNamespace(submit=submit,
        poll=lambda name: types.GenerateVideosOperation(name=name, done=True, response=types.GenerateVideosResponse(
            generated_videos=[types.GeneratedVideo(video=types.Video(uri="fake://video"))])), download=lambda *args: None)
    def factory(db, job, run):
        return build_media_reviewer(db, job, run, "gemini-fixture")
    options = dict(video_service=service, video_request=VeoRequest("Fixture"), estimated_cost_microusd=1, video_review_factory=factory)
    file_store.files.processing = True
    assert worker.process_one(URL, "file-processing", queue, **options)
    with psycopg.connect(URL) as connection:
        assert connection.execute("SELECT state FROM app.jobs WHERE id=%s", (job,)).fetchone() == ("running",)
        assert connection.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("held",)
        assert connection.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM app.media_review_budget WHERE run_id IN (SELECT id FROM app.job_runs WHERE job_id=%s)", (job,)).fetchone() == (1,)
        connection.execute("UPDATE app.job_runs SET next_work_at=clock_timestamp()-interval '1 second' WHERE job_id=%s", (job,))
    for remote in file_store.files.objects.values():
        remote.state = types.FileState.ACTIVE
    assert worker.recover_expired_runs(URL, queue, str(job)) == 1
    assert worker.process_one(URL, "file-ready", queue, **options)
    assert submissions == compositions == [True]
    assert len(calls) == 2 and file_store.files.uploads == 1
    with psycopg.connect(URL) as connection:
        assert connection.execute("SELECT state FROM app.jobs WHERE id=%s", (job,)).fetchone() == ("delivered",)
        assert connection.execute("SELECT delta FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchall() == [(-2,)]
