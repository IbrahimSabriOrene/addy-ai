import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from admaker.review_budget import reserve_review_budget
from admaker.review_reconciliation import resolve_review_receipt
from test_worker_leases import URL, queued_job


def test_terminal_review_resolution_is_audited_and_does_not_refund_or_resubmit(queued_job, monkeypatch):
    account, job, _, _ = queued_job
    run = uuid.uuid4()
    with psycopg.connect(URL) as c:
        c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state) VALUES (%s,%s,1,%s,'running')", (run, job, str(run)))
    for key, value in {"MEDIA_REVIEW_ESTIMATE_MICROUSD": "10", "MEDIA_REVIEW_DAILY_BUDGET_MICROUSD": "1000000000",
                       "MEDIA_REVIEW_MAX_CALLS_PER_RUN": "2", "MEDIA_REVIEW_MAX_CONCURRENT_CALLS": "100"}.items():
        monkeypatch.setenv(key, value)
    receipts = []
    try:
        first = reserve_review_budget(URL, run, "a" * 64)
        receipts.append(first)
        resolution = uuid.uuid4()
        args = (URL, first, resolution, "operator", "Restricted provider terminal-call ticket")
        with pytest.raises(ValueError, match="Verified"):
            resolve_review_receipt(*args, verified_terminal=False)
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(lambda _: resolve_review_receipt(*args, verified_terminal=True), range(2))) == [False, True]
        with pytest.raises(ValueError, match="differs"):
            resolve_review_receipt(URL, first, resolution, "operator", "Changed evidence", verified_terminal=True)
        second = reserve_review_budget(URL, run, "a" * 64)
        receipts.append(second)
        assert second != first
        assert not resolve_review_receipt(*args, verified_terminal=True)
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT state,verdict FROM app.media_review_budget WHERE id=%s", (second,)).fetchone() == ("unconfirmed", None)
            assert c.execute("SELECT sum(amount_microusd) FROM app.media_review_budget WHERE run_id=%s", (run,)).fetchone() == (20,)
            assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
            c.execute("DELETE FROM app.job_runs WHERE id=%s", (run,))
        assert resolve_review_receipt(URL, second, uuid.uuid4(), "operator", "Verified terminal call after account cleanup", verified_terminal=True)
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.media_review_budget WHERE id=ANY(%s)", (receipts,))
