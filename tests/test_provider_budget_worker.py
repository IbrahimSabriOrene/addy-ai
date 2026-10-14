from types import SimpleNamespace

import psycopg
import pytest

from admaker import worker
from admaker.veo import VeoRequest
from test_provider_graph import provider_job, allow_review
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("budget", ["1", "0", "invalid"])
def test_budget_rejection_releases_credit_without_provider_submission(provider_job, monkeypatch, budget):
    account, job, reservation, queue = provider_job
    monkeypatch.setenv("VEO_DAILY_BUDGET_MICROUSD", budget)
    calls = []

    def submit(*args, **kwargs):
        calls.append("submit")
        raise AssertionError("Budget rejection must precede provider submission")

    options = dict(video_service=SimpleNamespace(submit=submit),
        video_request=VeoRequest("Fixture"), estimated_cost_microusd=2,
        video_review=allow_review)
    assert worker.process_one(URL, "budget-test", queue, **options)
    assert calls == []
    assert worker.recover_expired_runs(URL, queue, str(job)) == 0
    assert not worker.process_one(URL, "budget-test-again", queue, **options)
    with psycopg.connect(URL) as connection:
        assert connection.execute("SELECT state FROM app.jobs WHERE id=%s", (job,)).fetchone() == ("failed",)
        assert connection.execute("SELECT state FROM app.job_runs WHERE job_id=%s", (job,)).fetchone() == ("failed",)
        assert connection.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("released",)
        assert connection.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM app.provider_budget_holds h JOIN app.job_attempts a ON a.id=h.attempt_id JOIN app.job_runs r ON r.id=a.run_id WHERE r.job_id=%s", (job,)).fetchone() == (0,)
