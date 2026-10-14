import psycopg
from psycopg import sql
import pytest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import uuid

from admaker import worker
from admaker.run_compatibility import pause_incompatible_run, resume_compatible_run
from test_worker_leases import URL, queued_job


def test_compatible_resume_preserves_attempt_and_audits_one_wake(monkeypatch, queued_job):
    account, job, reservation, queue = queued_job
    original = worker.run_worker_graph

    def crash(*args):
        raise RuntimeError("test process stopped")

    monkeypatch.setattr(worker, "run_worker_graph", crash)
    with pytest.raises(RuntimeError, match="test process"):
        worker.process_one(URL, "old-worker", queue)
    with psycopg.connect(URL) as connection:
        run, fence = connection.execute("SELECT id,fence FROM app.job_runs WHERE job_id=%s", (job,)).fetchone()
        message = connection.execute(sql.SQL("SELECT msg_id FROM pgmq.{}").format(sql.Identifier("q_" + queue))).fetchone()[0]
    assert pause_incompatible_run(URL, run, "old-worker", fence, "wrong-worker", queue, message)
    with pytest.raises(ValueError, match="cannot resume"):
        resume_compatible_run(URL, run, fence, "operator", "Reviewed", "provider", queue)
    with pytest.raises(ValueError, match="no longer"):
        resume_compatible_run(URL, run, fence + 1, "operator", "Reviewed", "fixture", queue)
    assert resume_compatible_run(URL, run, fence, "operator", "Reviewed", "fixture", queue)
    assert not resume_compatible_run(URL, run, fence, "operator", "Reviewed", "fixture", queue)
    with pytest.raises(ValueError, match="replay differs"):
        resume_compatible_run(URL, run, fence, "different", "Reviewed", "fixture", queue)
    with psycopg.connect(URL) as connection:
        assert connection.execute(sql.SQL("SELECT count(*) FROM pgmq.{}").format(sql.Identifier("q_" + queue))).fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM app.job_attempts WHERE run_id=%s", (run,)).fetchone()[0] == 1
        assert connection.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone()[0] == "held"
    monkeypatch.setattr(worker, "run_worker_graph", original)
    monkeypatch.setattr(worker, "_render_fake", lambda *args: {"tiktok": {"key": "test.mp4", "caption": ""}})
    assert worker.process_one(URL, "compatible-worker", queue)
    with psycopg.connect(URL) as connection:
        assert connection.execute("SELECT id,state FROM app.job_runs WHERE job_id=%s", (job,)).fetchone() == (run, "delivered")
        assert connection.execute("SELECT count(*) FROM app.run_resume_audit WHERE run_id=%s", (run,)).fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone()[0] == 1


def test_resume_queue_failure_rolls_back_and_concurrent_requests_enqueue_once(monkeypatch, queued_job):
    account, job, reservation, queue = queued_job

    def crash(*args):
        raise RuntimeError("stopped before graph")

    monkeypatch.setattr(worker, "run_worker_graph", crash)
    with pytest.raises(RuntimeError, match="stopped before"):
        worker.process_one(URL, "worker", queue)
    with psycopg.connect(URL) as connection:
        run, fence = connection.execute("SELECT id,fence FROM app.job_runs WHERE job_id=%s", (job,)).fetchone()
        message = connection.execute(sql.SQL("SELECT msg_id FROM pgmq.{}").format(sql.Identifier("q_" + queue))).fetchone()[0]
    assert pause_incompatible_run(URL, run, "worker", fence, "different-worker", queue, message)
    with pytest.raises(psycopg.Error):
        resume_compatible_run(URL, run, fence, "operator", "Reviewed compatible build", "fixture", "missing_" + uuid.uuid4().hex)
    with psycopg.connect(URL) as connection:
        assert connection.execute("SELECT state FROM app.jobs WHERE id=%s", (job,)).fetchone()[0] == "failed"
        assert connection.execute("SELECT state FROM app.job_runs WHERE id=%s", (run,)).fetchone()[0] == "review_required"
        assert connection.execute("SELECT count(*) FROM app.run_resume_audit WHERE run_id=%s", (run,)).fetchone()[0] == 0
    barrier = Barrier(2)

    def resume():
        barrier.wait(timeout=5)
        return resume_compatible_run(URL, run, fence, "operator", "Reviewed compatible build", "fixture", queue)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=10) for future in [pool.submit(resume), pool.submit(resume)]]
    assert sorted(results) == [False, True]
    with psycopg.connect(URL) as connection:
        assert connection.execute(sql.SQL("SELECT count(*) FROM pgmq.{}").format(sql.Identifier("q_" + queue))).fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM app.run_resume_audit WHERE run_id=%s", (run,)).fetchone()[0] == 1
        assert connection.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone()[0] == "held"
        assert connection.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone()[0] == 0
    for role in ("anon", "authenticated"):
        with psycopg.connect(URL) as connection:
            connection.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT * FROM app.run_resume_audit")
