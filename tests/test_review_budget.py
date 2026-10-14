import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from admaker.review_budget import reserve_review_budget
from test_worker_leases import URL, queued_job


def test_review_budget_caps_are_atomic_and_survive_run_deletion(queued_job, monkeypatch):
    _, job, _, _ = queued_job
    run = uuid.uuid4()
    with psycopg.connect(URL) as c:
        c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state) VALUES (%s,%s,1,%s,'running')", (run, job, str(run)))
        baseline = c.execute("SELECT COALESCE(sum(amount_microusd),0) FROM app.media_review_budget WHERE created_at >= date_trunc('day',clock_timestamp() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'").fetchone()[0]
    monkeypatch.setenv("MEDIA_REVIEW_ESTIMATE_MICROUSD", "10")
    monkeypatch.setenv("MEDIA_REVIEW_DAILY_BUDGET_MICROUSD", str(baseline + 30))
    monkeypatch.setenv("MEDIA_REVIEW_MAX_CALLS_PER_RUN", "20")
    monkeypatch.setenv("MEDIA_REVIEW_MAX_CONCURRENT_CALLS", "20")
    def reserve(_):
        try:
            return reserve_review_budget(URL, run)
        except ValueError:
            return None
    receipts = []
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            receipts = [value for value in pool.map(reserve, range(6)) if value]
        assert len(receipts) == 3
        with pytest.raises(ValueError, match="exhausted"):
            reserve_review_budget(URL, run)
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.job_runs WHERE id=%s", (run,))
            assert c.execute("SELECT count(*),sum(amount_microusd) FROM app.media_review_budget WHERE id=ANY(%s) AND run_id IS NULL", (receipts,)).fetchone() == (3, 30)
        for role in ("anon", "authenticated"):
            with psycopg.connect(URL) as c:
                c.execute(f"SET ROLE {role}")
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    c.execute("SELECT * FROM app.media_review_budget")
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.media_review_budget WHERE id=ANY(%s) OR run_id=%s", (receipts, run))
