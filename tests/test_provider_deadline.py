from types import SimpleNamespace

import psycopg
import pytest
from google.genai import types

from admaker import worker
from admaker.submission_review import resolve_submission
from admaker.veo import VeoRequest
from test_provider_graph import provider_job, allow_review
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("ready", [False, True])
def test_expired_output_wait_stops_calls_and_allows_audited_release(provider_job, ready):
    account, job, reservation, queue = provider_job
    calls = []

    def submit(*args, **kwargs):
        calls.append("submit")
        return "operations/deadline-test"

    def poll(name):
        calls.append("poll")
        return types.GenerateVideosOperation(name=name, done=False)

    options = dict(video_service=SimpleNamespace(submit=submit, poll=poll),
                   video_request=VeoRequest("Fixture"), estimated_cost_microusd=400000,
                   video_review=allow_review)
    assert worker.process_one(URL, "initial", queue, **options)
    with psycopg.connect(URL) as c:
        run, attempt = c.execute("SELECT run_id,id FROM app.job_attempts WHERE run_id IN (SELECT id FROM app.job_runs WHERE job_id=%s)", (job,)).fetchone()
        c.execute("UPDATE app.job_attempts SET created_at=clock_timestamp()-interval '25 hours',provider_state=%s,next_poll_at=clock_timestamp()-interval '1 second' WHERE id=%s", ("ready" if ready else "submitted", attempt))
        c.execute("UPDATE app.job_runs SET lease_until=clock_timestamp()-interval '1 second',next_work_at=clock_timestamp()-interval '1 second' WHERE id=%s", (run,))
    assert worker.recover_expired_runs(URL, queue, str(job)) == 1
    assert worker.process_one(URL, "expired", queue, **options)
    assert calls == ["submit", "poll"]
    assert worker.recover_expired_runs(URL, queue, str(job)) == 0
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT state FROM app.job_runs WHERE id=%s", (run,)).fetchone() == ("review_required",)
        assert c.execute("SELECT operation_name,provider_error,next_poll_at FROM app.job_attempts WHERE id=%s", (attempt,)).fetchone() == ("operations/deadline-test", "wait_deadline_exceeded", None)
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("held",)
    assert resolve_submission(URL, attempt, "test-operator", "goodwill_release", "Output wait exceeded local deadline")
    assert resolve_submission(URL, attempt, "test-operator", "goodwill_release", "Output wait exceeded local deadline")
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("released",)
        assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
