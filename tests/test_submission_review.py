from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import uuid
import subprocess
import sys

import psycopg
import pytest
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.submission_review import resolve_submission
from admaker.veo import VeoRequest
from admaker.worker import process_one, recover_expired_runs
from test_provider_graph import provider_job, queued_job, URL, allow_review


@pytest.mark.parametrize("decision,cost", [("verified_no_output", 0), ("goodwill_release", None)])
def test_review_resolution_is_atomic_idempotent_private_and_never_requeues(provider_job, decision, cost, tmp_path):
    account, job, reservation, queue = provider_job

    def submit(*args, **kwargs):
        raise TimeoutError()

    assert process_one(URL, "worker", queue, video_service=SimpleNamespace(submit=submit),
                       video_request=VeoRequest("Fixture"), estimated_cost_microusd=400000, video_review=allow_review)
    with psycopg.connect(URL) as c:
        attempt, due_in_future = c.execute("SELECT s.attempt_id,s.review_due_at>clock_timestamp() FROM app.submission_reviews s JOIN app.job_attempts a ON a.id=s.attempt_id JOIN app.job_runs r ON r.id=a.run_id WHERE r.job_id=%s", (job,)).fetchone()
        assert due_in_future
    for role in ("anon", "authenticated"):
        with psycopg.connect(URL) as c:
            c.execute(f"SET LOCAL ROLE {role}")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("SELECT * FROM app.submission_reviews")
            c.rollback()
    args = (URL, attempt, "operator-1", decision, "Reviewed the case and authorized release.", cost)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda _: resolve_submission(*args), range(2))) == [True, True]
    with pytest.raises(ValueError, match="different resolution"):
        resolve_submission(URL, attempt, "operator-2", decision, "Different decision", cost)
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone()[0] == "released"
        assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone()[0] == 0
        assert c.execute("SELECT state,actual_cost_microusd FROM app.job_attempts WHERE id=%s", (attempt,)).fetchone() == ("failed", cost)
        assert c.execute("SELECT provider_state FROM app.job_attempts WHERE id=%s", (attempt,)).fetchone() == ("failed" if decision == "verified_no_output" else "submission_unknown",)
        assert c.execute("SELECT operator,decision,reason,actual_cost_microusd,resolved_at IS NOT NULL FROM app.submission_reviews WHERE attempt_id=%s", (attempt,)).fetchone() == (*args[2:], True)
    assert recover_expired_runs(URL, queue, str(job)) == 0
    reason_file = tmp_path / "review reason.txt"
    reason_file.write_text(args[4], encoding="utf-8")
    command = [sys.executable, "-m", "admaker.submission_review", "resolve", str(attempt),
               "--operator", args[2], "--decision", decision, "--reason-file", str(reason_file)]
    if cost is not None:
        command += ["--actual-cost-microusd", str(cost)]
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=15)
    assert "reserved credits released" in result.stdout
    pending = subprocess.run([sys.executable, "-m", "admaker.submission_review", "list"],
                             check=True, capture_output=True, text=True, timeout=15)
    assert str(attempt) not in pending.stdout
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "test@example.com")
    try:
        with TestClient(app) as client:
            response = client.get(f"/v1/jobs/{job}")
            assert response.json()["failure"]["code"] == "generation_closed"
            assert "credits have been released" in response.json()["failure"]["message"]
            assert "operator-1" not in response.text and args[4] not in response.text
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)


def test_review_rejects_invalid_cost_and_changed_reservation_without_partial_resolution(provider_job):
    account, job, reservation, queue = provider_job

    def submit(*args, **kwargs):
        raise TimeoutError()

    process_one(URL, "worker", queue, video_service=SimpleNamespace(submit=submit),
                video_request=VeoRequest("Fixture"), estimated_cost_microusd=400000, video_review=allow_review)
    with psycopg.connect(URL) as c:
        attempt = c.execute("SELECT a.id FROM app.job_attempts a JOIN app.job_runs r ON r.id=a.run_id WHERE r.job_id=%s", (job,)).fetchone()[0]
        c.execute("UPDATE app.credit_reservations SET state='consumed' WHERE id=%s", (reservation,))
    for cost in (True, -1, 1.5, 1_000_000_001):
        with pytest.raises(ValueError, match="Actual cost"):
            resolve_submission(URL, attempt, "operator", "goodwill_release", "Reviewed", cost)
    with pytest.raises(ValueError, match="no longer held"):
        resolve_submission(URL, attempt, "operator", "goodwill_release", "Reviewed")
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT resolved_at,decision FROM app.submission_reviews WHERE attempt_id=%s", (attempt,)).fetchone() == (None, None)
        assert c.execute("SELECT state FROM app.job_runs WHERE job_id=%s", (job,)).fetchone()[0] == "review_required"
    assert not resolve_submission(URL, uuid.uuid4(), "operator", "goodwill_release", "Reviewed")
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.credit_reservations SET state='held' WHERE id=%s", (reservation,))
        c.execute("UPDATE app.job_attempts SET actual_cost_microusd=125000 WHERE id=%s", (attempt,))
    with pytest.raises(ValueError, match="conflicts"):
        resolve_submission(URL, attempt, "operator", "goodwill_release", "Reviewed", 0)
    assert resolve_submission(URL, attempt, "operator", "goodwill_release", "Reviewed")
    assert resolve_submission(URL, attempt, "operator", "goodwill_release", "Reviewed")
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT actual_cost_microusd FROM app.submission_reviews WHERE attempt_id=%s", (attempt,)).fetchone()[0] == 125000
        assert c.execute("SELECT actual_cost_microusd FROM app.job_attempts WHERE id=%s", (attempt,)).fetchone()[0] == 125000
