from admaker.eligibility import POLICY_VERSION
import uuid
import hashlib
import os
from pathlib import Path
from PIL import Image
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import psycopg
import pytest
from google.genai import types

from admaker.consent import DISCLOSURE_VERSION
from admaker.db import RunLeaseLost, migrate
from admaker.veo import VeoRequest, SubmissionUnknown, SubmissionInProgress, submit_video_attempt, poll_video_attempt
from test_worker_leases import URL, queued_job


@pytest.fixture
def attempt(queued_job, monkeypatch, tmp_path):
    account, job, reservation, queue = queued_job
    run, attempt_id = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("LOCAL_ASSET_ROOT", str(tmp_path))
    Image.new("RGB", (8, 8), "blue").save(tmp_path / "test.png")
    with psycopg.connect(URL) as c:
        c.execute("INSERT INTO app.account_eligibility(account_id,policy_version) VALUES (%s,%s)", (account, POLICY_VERSION))
        c.execute("INSERT INTO app.ai_consent(account_id,disclosure_version,granted) VALUES (%s,%s,true)", (account, DISCLOSURE_VERSION))
        c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state,lease_owner,lease_until,fence) VALUES (%s,%s,1,%s,'running','worker',clock_timestamp()+interval '60 seconds',1)", (run, job, str(run)))
        c.execute("INSERT INTO app.job_attempts(id,run_id,reservation_id,sequence,state,request_hash) VALUES (%s,%s,%s,1,'running','fixture')", (attempt_id, run, reservation))
        c.execute("UPDATE app.jobs SET state='running',active_run_id=%s WHERE id=%s", (run, job))
    try:
        yield account, run, attempt_id, reservation
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.ai_consent WHERE account_id=%s", (account,))


def test_submit_is_single_flight_and_saved_operation_replays_without_post(attempt):
    account, run, attempt_id, reservation = attempt
    entered, release = Event(), Event()
    posts = []
    name = f"operations/{uuid.uuid4()}"

    def submit(request, *, account_id):
        posts.append(request)
        assert account_id == str(account)
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT provider_state,estimated_cost_microusd FROM app.job_attempts WHERE id=%s", (attempt_id,)).fetchone() == ("submitting", 400000)
        entered.set(); assert release.wait(3)
        return name

    service = SimpleNamespace(submit=submit)
    request = VeoRequest("Fixture")
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(submit_video_attempt, URL, attempt_id, "worker", 1, request, 400000, service)
        assert entered.wait(3)
        with pytest.raises(SubmissionInProgress):
            submit_video_attempt(URL, attempt_id, "worker", 1, request, 400000, service)
        release.set()
        assert future.result() == name
    assert submit_video_attempt(URL, attempt_id, "worker", 1, request, 400000, service) == name
    with pytest.raises(ValueError, match="snapshot"):
        submit_video_attempt(URL, attempt_id, "worker", 1, VeoRequest("Changed"), 400000, service)
    assert len(posts) == 1
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone()[0] == "held"
        assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone()[0] == 0


@pytest.mark.parametrize("failure", ["process_crash", "timeout", "late_success"])
def test_uncertain_submission_never_automatically_repeats(attempt, failure):
    account, run, attempt_id, reservation = attempt
    posts = []

    def submit(*args, **kwargs):
        posts.append(1)
        if failure == "process_crash":
            raise KeyboardInterrupt("Simulated process death after provider acceptance")
        if failure == "timeout":
            raise TimeoutError("Response lost")
        with psycopg.connect(URL) as c:
            c.execute("UPDATE app.job_runs SET fence=2,lease_owner='replacement' WHERE id=%s", (run,))
        return f"operations/{uuid.uuid4()}"

    service = SimpleNamespace(submit=submit)
    expected = KeyboardInterrupt if failure == "process_crash" else SubmissionUnknown if failure == "timeout" else RunLeaseLost
    with pytest.raises(expected):
        submit_video_attempt(URL, attempt_id, "worker", 1, VeoRequest("Fixture"), 400000, service)
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.job_runs SET fence=2,lease_owner='replacement',lease_until=clock_timestamp()+interval '60 seconds' WHERE id=%s", (run,))
    for _ in range(2):
        with pytest.raises(SubmissionUnknown):
            submit_video_attempt(URL, attempt_id, "replacement", 2, VeoRequest("Fixture"), 400000, service)
    assert posts == [1]
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT provider_state,operation_name FROM app.job_attempts WHERE id=%s", (attempt_id,)).fetchone() == ("submission_unknown", None)
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone()[0] == "held"


def test_poll_is_due_once_and_timeout_keeps_operation(attempt):
    _, _, attempt_id, _ = attempt
    name = f"operations/{uuid.uuid4()}"
    polls = []
    service = SimpleNamespace(submit=lambda *args, **kwargs: name)
    submit_video_attempt(URL, attempt_id, "worker", 1, VeoRequest("Fixture"), 400000, service)

    def poll(operation):
        polls.append(operation)
        raise TimeoutError("Temporary polling timeout")

    service.poll = poll
    with pytest.raises(TimeoutError):
        poll_video_attempt(URL, attempt_id, "worker", 1, service)
    assert poll_video_attempt(URL, attempt_id, "worker", 1, service) is None
    assert polls == [name]
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT provider_state,operation_name FROM app.job_attempts WHERE id=%s", (attempt_id,)).fetchone() == ("submitted", name)
        c.execute("UPDATE app.job_attempts SET next_poll_at=clock_timestamp()-interval '1 second' WHERE id=%s", (attempt_id,))
    service.poll = lambda _: types.GenerateVideosOperation(done=True, response=types.GenerateVideosResponse(rai_media_filtered_count=1))
    assert poll_video_attempt(URL, attempt_id, "worker", 1, service).done
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT provider_state,provider_error FROM app.job_attempts WHERE id=%s", (attempt_id,)).fetchone() == ("failed", "provider_blocked")


def test_invalid_cost_consent_or_reservation_stops_before_submit(attempt):
    account, _, attempt_id, reservation = attempt
    posts = []
    service = SimpleNamespace(submit=lambda *args, **kwargs: posts.append(1))
    for estimate in [-1, True, 1.5, 1_000_000_001]:
        with pytest.raises(ValueError):
            submit_video_attempt(URL, attempt_id, "worker", 1, VeoRequest("Fixture"), estimate, service)
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.ai_consent SET granted=false WHERE account_id=%s", (account,))
    with pytest.raises(PermissionError):
        submit_video_attempt(URL, attempt_id, "worker", 1, VeoRequest("Fixture"), 400000, service)
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.ai_consent SET granted=true WHERE account_id=%s", (account,))
        c.execute("UPDATE app.credit_reservations SET state='released' WHERE id=%s", (reservation,))
    with pytest.raises(ValueError, match="reservation"):
        submit_video_attempt(URL, attempt_id, "worker", 1, VeoRequest("Fixture"), 400000, service)
    assert posts == []
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT provider_state,provider_request FROM app.job_attempts WHERE id=%s", (attempt_id,)).fetchone() == (None, None)


def test_attempt_binds_exact_verified_bytes_and_replay_needs_no_file(attempt):
    _, _, attempt_id, _ = attempt
    source = Path(os.environ["LOCAL_ASSET_ROOT"]) / "test.png"
    original = source.read_bytes()
    name = f"operations/{uuid.uuid4()}"
    posts = []

    def submit(request, **kwargs):
        source.write_bytes(b"changed after the durable request was prepared")
        assert request.image_path is None
        assert request.image_bytes == original
        with psycopg.connect(URL) as c:
            saved = c.execute("SELECT provider_request FROM app.job_attempts WHERE id=%s", (attempt_id,)).fetchone()[0]
        assert saved["imageSha256"] == hashlib.sha256(original).hexdigest()
        assert saved["imageMimeType"] == "image/png"
        assert saved["imageSizeBytes"] == len(original)
        assert "image_path" not in saved and "image_bytes" not in saved
        posts.append(1)
        return name

    service = SimpleNamespace(submit=submit)
    request = VeoRequest("Fixture")
    assert submit_video_attempt(URL, attempt_id, "worker", 1, request, 400000, service) == name
    source.unlink()
    assert submit_video_attempt(URL, attempt_id, "worker", 1, request, 400000, service) == name
    assert posts == [1]


def test_unverified_foreign_or_substituted_source_never_submits(attempt):
    account, run, attempt_id, _ = attempt
    source = Path(os.environ["LOCAL_ASSET_ROOT"]) / "test.png"
    posts = []
    service = SimpleNamespace(submit=lambda *args, **kwargs: posts.append(1))
    for request in [VeoRequest("Fixture", str(source.parent / "different.png")), VeoRequest("Fixture", image_bytes=source.read_bytes())]:
        with pytest.raises(ValueError):
            submit_video_attempt(URL, attempt_id, "worker", 1, request, 400000, service)
    with psycopg.connect(URL) as c:
        asset = c.execute("SELECT j.source_asset_id FROM app.jobs j JOIN app.job_runs r ON r.job_id=j.id WHERE r.id=%s", (run,)).fetchone()[0]
        c.execute("UPDATE app.assets SET verification_state='pending' WHERE asset_key=%s", (asset,))
    with pytest.raises(ValueError, match="verified"):
        submit_video_attempt(URL, attempt_id, "worker", 1, VeoRequest("Fixture"), 400000, service)
    other = uuid.uuid4()
    try:
        with psycopg.connect(URL) as c:
            c.execute("INSERT INTO app.accounts(id,email) VALUES (%s,'foreign-photo@example.com')", (other,))
            c.execute("UPDATE app.assets SET verification_state='verified',owner_id=%s WHERE asset_key=%s", (other, asset))
        with pytest.raises(ValueError, match="owned"):
            submit_video_attempt(URL, attempt_id, "worker", 1, VeoRequest("Fixture"), 400000, service)
    finally:
        with psycopg.connect(URL) as c:
            c.execute("UPDATE app.assets SET owner_id=%s WHERE asset_key=%s", (account, asset))
            c.execute("DELETE FROM app.accounts WHERE id=%s", (other,))
    assert posts == []
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT provider_state FROM app.job_attempts WHERE id=%s", (attempt_id,)).fetchone()[0] is None
