from admaker.eligibility import POLICY_VERSION
import uuid
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from PIL import Image
from google.genai import types

from admaker import provider_graph, worker
from admaker.consent import DISCLOSURE_VERSION
from admaker.veo import VeoRequest
from test_worker_leases import URL, queued_job


def allow_review(root, exports):
    return {"policyAllowed": True, "qualityPassed": True}


class Crash(BaseException):
    pass


@pytest.fixture
def provider_job(queued_job, monkeypatch, tmp_path):
    account, job, reservation, queue = queued_job
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("LOCAL_ASSET_ROOT", str(tmp_path))
    Image.new("RGB", (8, 8), "blue").save(tmp_path / "test.png")
    with psycopg.connect(URL) as c:
        c.execute("INSERT INTO app.account_eligibility(account_id,policy_version) VALUES (%s,%s)", (account, POLICY_VERSION))
        c.execute("INSERT INTO app.ai_consent(account_id,disclosure_version,granted) VALUES (%s,%s,true)", (account, DISCLOSURE_VERSION))
    yield queued_job
    with psycopg.connect(URL) as c:
        c.execute("DELETE FROM app.ai_consent WHERE account_id=%s", (account,))


@pytest.mark.parametrize("boundary", ["checkpoint_before_settlement", "download_before_compose"])
def test_queue_wait_timeout_restart_and_settlement_reuse_one_attempt(provider_job, monkeypatch, boundary):
    account, job, reservation, queue = provider_job
    calls = {"submit": 0, "poll": 0, "download": 0, "compose": 0}
    operation_name = f"operations/{uuid.uuid4()}"

    def submit(request, **kwargs):
        calls["submit"] += 1
        assert request.image_bytes
        return operation_name

    def poll(name):
        assert name == operation_name
        calls["poll"] += 1
        if calls["poll"] == 1:
            return types.GenerateVideosOperation(name=name, done=False)
        if calls["poll"] == 2:
            raise TimeoutError()
        return types.GenerateVideosOperation(name=name, done=True, response=types.GenerateVideosResponse(
            generated_videos=[types.GeneratedVideo(video=types.Video(uri="fake://video"))]))

    def download(operation, path):
        calls["download"] += 1
        Path(path).write_bytes(b"fixture: media validation is tested with real FFmpeg separately")

    def compose(source, root, output_id, platforms):
        assert source.is_file()
        calls["compose"] += 1
        if boundary == "download_before_compose" and calls["compose"] == 1:
            raise Crash()
        return {"tiktok": {"key": f"runs/{output_id}/final.mp4"}}

    monkeypatch.setattr(provider_graph, "compose_video", compose)
    service = SimpleNamespace(submit=submit, poll=poll, download=download)
    options = dict(video_service=service, video_request=VeoRequest("Prepared internal prompt"), estimated_cost_microusd=400000, video_review=allow_review)
    assert worker.process_one(URL, "first", queue, **options)
    assert worker.recover_expired_runs(URL, queue, str(job)) == 0  # not due yet

    def due():
        with psycopg.connect(URL) as c:
            c.execute("UPDATE app.job_runs SET lease_until=clock_timestamp()-interval '1 second',next_work_at=clock_timestamp()-interval '1 second' WHERE job_id=%s", (job,))
            c.execute("UPDATE app.job_attempts SET next_poll_at=clock_timestamp()-interval '1 second' WHERE run_id IN (SELECT id FROM app.job_runs WHERE job_id=%s)", (job,))
        assert worker.recover_expired_runs(URL, queue, str(job)) == 1

    due()
    assert worker.process_one(URL, "second", queue, **options)
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone()[0] == "held"
        assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone()[0] == 0
    original = provider_graph.run_provider_graph

    def crash(*args):
        original(*args)
        raise Crash()

    if boundary == "checkpoint_before_settlement":
        monkeypatch.setattr(provider_graph, "run_provider_graph", crash)
    due()
    with pytest.raises(Crash):
        worker.process_one(URL, "third", queue, **options)
    monkeypatch.setattr(provider_graph, "run_provider_graph", original)
    due()
    assert worker.process_one(URL, "fourth", queue, **options)
    assert calls == {"submit": 1, "poll": 3, "download": 1, "compose": 2 if boundary == "download_before_compose" else 1}
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT state FROM app.jobs WHERE id=%s", (job,)).fetchone()[0] == "delivered"
        assert c.execute("SELECT count(*),sum(delta) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (1, -2)
        assert c.execute("SELECT count(*),max(fence) FROM app.job_runs WHERE job_id=%s", (job,)).fetchone() == (1, 4)
        assert c.execute("SELECT count(*) FROM app.job_attempts WHERE run_id IN (SELECT id FROM app.job_runs WHERE job_id=%s)", (job,)).fetchone()[0] == 1


def test_unknown_submission_is_held_for_review_without_requeue(provider_job):
    account, job, reservation, queue = provider_job
    calls = []

    def submit(*args, **kwargs):
        calls.append(1)
        raise TimeoutError("May have been accepted")

    assert worker.process_one(URL, "first", queue, video_service=SimpleNamespace(submit=submit),
        video_request=VeoRequest("Fixture"), estimated_cost_microusd=400000, video_review=allow_review)
    assert worker.recover_expired_runs(URL, queue, str(job)) == 0
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT state FROM app.job_runs WHERE job_id=%s", (job,)).fetchone()[0] == "review_required"
        state, result = c.execute("SELECT state,result FROM app.jobs WHERE id=%s", (job,)).fetchone()
        assert state == "failed" and result["failure"]["code"] == "submission_unknown"
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone()[0] == "held"
        assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone()[0] == 0
    assert calls == [1]
    from fastapi.testclient import TestClient
    from admaker.api import app
    from admaker.auth import Subject, authenticated_subject

    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "test@example.com")
    try:
        with TestClient(app) as client:
            response = client.get(f"/v1/jobs/{job}")
            assert response.status_code == 200
            assert response.json()["failure"]["code"] == "submission_unknown"
            assert "reserved credits remain held" in response.json()["failure"]["message"]
            assert "provider_request" not in response.text and "operation_name" not in response.text
            app.dependency_overrides[authenticated_subject] = lambda: Subject(str(uuid.uuid4()), "other@example.com")
            assert client.get(f"/v1/jobs/{job}").status_code == 404
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)


def test_blocked_provider_output_never_downloads_or_consumes_credit(provider_job):
    account, job, reservation, queue = provider_job
    service = SimpleNamespace(
        submit=lambda *args, **kwargs: f"operations/{uuid.uuid4()}",
        poll=lambda name: types.GenerateVideosOperation(name=name, done=True,
            response=types.GenerateVideosResponse(rai_media_filtered_count=1)),
    )  # No download method: a blocked result must never reach that boundary.
    assert worker.process_one(URL, "first", queue, video_service=service,
        video_request=VeoRequest("Fixture"), estimated_cost_microusd=400000, video_review=allow_review)
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT state FROM app.jobs WHERE id=%s", (job,)).fetchone()[0] == "failed"
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone()[0] == "released"
        assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone()[0] == 0
