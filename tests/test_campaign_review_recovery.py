from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import psycopg
import pytest
from psycopg import sql

from admaker import campaign_worker, worker
from admaker.campaign_review import review_campaign_pack
from admaker.veo import VeoRequest
from test_campaign_retry_limit import test_three_pack_failures_pause_without_resubmission_or_debit as prepare_paused_pack
from test_provider_graph import provider_job, allow_review
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("conflicting_decisions", [False, True])
def test_operator_race_and_resume_reuse_completed_provider_graph(provider_job, monkeypatch, conflicting_decisions):
    # Exercise the real three-failure worker path, including its no-debit assertions.
    prepare_paused_pack(provider_job, monkeypatch)
    account, job, reservation, queue = provider_job
    with psycopg.connect(URL) as c:
        run, fence = c.execute("SELECT id,fence FROM app.job_runs WHERE job_id=%s", (job,)).fetchone()
    barrier = Barrier(2)

    def review(index):
        decision = "release" if conflicting_decisions and index else "resume"
        barrier.wait(timeout=10)
        try:
            return decision, review_campaign_pack(URL, run, fence, "operator", "Local storage repaired", decision, queue if decision == "resume" else None)
        except ValueError as error:
            assert "replay differs" in str(error)
            return decision, "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(review, [0, 1]))
    assert sum(outcome is True for _, outcome in results) == 1
    if conflicting_decisions:
        assert sum(outcome == "conflict" for _, outcome in results) == 1
    else:
        assert sum(outcome is False for _, outcome in results) == 1
    winner = next(decision for decision, outcome in results if outcome is True)
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT count(*) FROM app.campaign_review_audit WHERE run_id=%s", (run,)).fetchone() == (1,)
        queued = c.execute(sql.SQL("SELECT count(*) FROM pgmq.{}").format(sql.Identifier("q_" + queue))).fetchone()[0]
        assert queued == (1 if winner == "resume" else 0)
    if winner == "resume":
        manifest = {"cleanImage": {"key": "test.png"}, "video": {"key": "video.mp4"},
                    "story": {"key": "story.png"}, "feed": {"key": "feed.png"}, "copy": {"caption": "Caption", "cta": "Shop"}}
        monkeypatch.setattr(campaign_worker, "compose_campaign_pack", lambda *args: manifest)
        for kind in ("cleanImage", "video", "story", "feed"):
            path = Path(os.environ["LOCAL_ASSET_ROOT"]) / manifest[kind]["key"]
            if not path.exists():
                path.write_bytes(b"fixture output")
            manifest[kind]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        # No submit/poll/download methods: any repeated external work fails this test.
        assert worker.process_one(URL, "repaired-worker", queue, video_service=SimpleNamespace(),
            video_request=VeoRequest("Fixture"), estimated_cost_microusd=3, video_review=allow_review)
        with psycopg.connect(URL) as c:
            state, result = c.execute("SELECT state,result FROM app.jobs WHERE id=%s", (job,)).fetchone()
            assert state == "delivered" and result["exports"] == manifest
            assert "failure" not in result
            assert c.execute("SELECT count(*),sum(delta) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (1, -2)
            assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("consumed",)
            assert c.execute("SELECT count(*) FROM app.job_attempts WHERE run_id=%s", (run,)).fetchone() == (1,)
    else:
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("released",)
            assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
        assert worker.recover_expired_runs(URL, queue, str(job)) == 0
