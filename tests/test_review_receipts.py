import uuid

import psycopg
import pytest

from admaker.review_budget import reserve_review_budget, finish_review_receipt
from test_worker_leases import URL, queued_job


def test_unknown_review_blocks_duplicate_and_capacity_even_after_run_deletion(queued_job, monkeypatch):
    _, job, _, _ = queued_job
    first, second = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(URL) as c:
        for sequence, run in enumerate((first, second), 1):
            c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state) VALUES (%s,%s,%s,%s,'running')", (run, job, sequence, str(run)))
        inflight = c.execute("SELECT count(*) FROM app.media_review_budget WHERE state='unconfirmed'").fetchone()[0]
    for name, value in {"MEDIA_REVIEW_ESTIMATE_MICROUSD": "1", "MEDIA_REVIEW_DAILY_BUDGET_MICROUSD": "1000000000",
                        "MEDIA_REVIEW_MAX_CALLS_PER_RUN": "10", "MEDIA_REVIEW_MAX_CONCURRENT_CALLS": str(inflight + 1)}.items():
        monkeypatch.setenv(name, value)
    receipts = []
    try:
        receipt = reserve_review_budget(URL, first, "a" * 64)
        receipts.append(receipt)
        with pytest.raises(ValueError, match="unconfirmed"):
            reserve_review_budget(URL, first, "a" * 64)
        with pytest.raises(ValueError, match="exhausted"):
            reserve_review_budget(URL, second, "b" * 64)
        verdict = {"policyAllowed": True, "qualityPassed": False, "offerFree": False}
        finish_review_receipt(URL, receipt, verdict)
        finish_review_receipt(URL, receipt, verdict)
        with pytest.raises(ValueError, match="conflicts"):
            finish_review_receipt(URL, receipt, {**verdict, "qualityPassed": True})
        assert reserve_review_budget(URL, first, "a" * 64) == verdict
        receipts.append(reserve_review_budget(URL, second, "b" * 64))
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.job_runs WHERE id=%s", (second,))
        with pytest.raises(ValueError, match="exhausted"):
            reserve_review_budget(URL, first, "c" * 64)
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT count(*) FROM app.media_review_budget WHERE id=ANY(%s)", (receipts,)).fetchone() == (2,)
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.media_review_budget WHERE id=ANY(%s)", (receipts,))
