import os
import uuid
from pathlib import Path

import psycopg
import pytest

from admaker.creative_planning import plan_product
from admaker.media_review import MediaReviewPending
from test_provider_graph import provider_job
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("uncertain", [False, True])
def test_plan_reuses_receipt_and_never_repeats_unknown_call(provider_job, monkeypatch, uncertain):
    _, job, _, _ = provider_job
    run = uuid.uuid4()
    with psycopg.connect(URL) as c:
        c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state,lease_owner,lease_until,fence) VALUES (%s,%s,1,%s,'running','planner',clock_timestamp()+interval '60 seconds',1)", (run, job, str(run)))
        c.execute("UPDATE app.jobs SET active_run_id=%s,state='running' WHERE id=%s", (run, job))
        inflight = c.execute("SELECT count(*) FROM app.media_review_budget WHERE state='unconfirmed'").fetchone()[0]
    for key, value in {"MEDIA_REVIEW_MODEL": "gemini-fixture", "MEDIA_REVIEW_ESTIMATE_MICROUSD": "1",
        "MEDIA_REVIEW_DAILY_BUDGET_MICROUSD": "1000000000", "MEDIA_REVIEW_MAX_CALLS_PER_RUN": "10",
        "MEDIA_REVIEW_MAX_CONCURRENT_CALLS": str(inflight + 1)}.items():
        monkeypatch.setenv(key, value)
    calls = []
    expected = {"product_summary": "Blue product", "creative_direction": "Slow orbit"}
    def invoke(messages, **kwargs):
        calls.append(messages)
        if uncertain:
            raise TimeoutError()
        return expected
    options = (URL, run, "planner", 1, Path(os.environ["LOCAL_ASSET_ROOT"]),
               {"outputKind": "video", "preparedVideoPrompt": "Selected style"})
    try:
        if uncertain:
            for _ in range(2):
                with pytest.raises(MediaReviewPending):
                    plan_product(*options, invoke=invoke)
        else:
            assert plan_product(*options, invoke=invoke) == expected
            assert plan_product(*options, invoke=invoke) == expected
        assert len(calls) == 1
        monkeypatch.setenv("MEDIA_REVIEW_MODEL", "gemini-changed")
        with pytest.raises(MediaReviewPending):
            plan_product(*options, invoke=invoke)
        assert len(calls) == 1
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.media_review_budget WHERE run_id=%s", (run,))
