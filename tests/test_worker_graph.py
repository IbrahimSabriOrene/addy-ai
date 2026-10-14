import pytest
import psycopg

from admaker import graph, worker
from admaker.db import FencedPostgresSaver, RunLeaseLost, postgres_checkpointer
from test_worker_leases import URL, queued_job


class ProcessCrash(BaseException):
    pass


@pytest.mark.parametrize("change", ["graph_version", "settings"])
def test_incompatible_resume_never_renders_or_charges_again(monkeypatch, queued_job, change):
    owner, job, reservation, queue = queued_job
    original = worker.run_worker_graph
    renders = []

    def render(*args):
        renders.append(1)
        return {"tiktok": {"key": "private/fixture.mp4", "caption": ""}}

    def crash(*args):
        original(*args)
        raise ProcessCrash()

    monkeypatch.setattr(worker, "_render_fake", render)
    monkeypatch.setattr(worker, "run_worker_graph", crash)
    with pytest.raises(ProcessCrash):
        worker.process_one(URL, "first", queue)
    monkeypatch.setattr(worker, "run_worker_graph", original)
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.job_runs SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s", (job,))
        if change == "graph_version":
            c.execute("UPDATE app.job_runs SET graph_version='unsupported-future-version' WHERE job_id=%s", (job,))
        else:
            c.execute("UPDATE app.jobs SET settings='{\"direction\":\"changed during run\"}'::jsonb WHERE id=%s", (job,))
    worker.recover_expired_runs(URL, queue, str(job))
    if change == "graph_version":
        assert worker.process_one(URL, "replacement", queue)
        assert not worker.process_one(URL, "replacement", queue)
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT state FROM app.job_runs WHERE job_id=%s", (job,)).fetchone()[0] == "review_required"
            assert c.execute("SELECT state,result->'failure'->>'code' FROM app.jobs WHERE id=%s", (job,)).fetchone() == ("failed", "incompatible_run")
        assert worker.recover_expired_runs(URL, queue, str(job)) == 0
    else:
        with pytest.raises(RuntimeError, match="version"):
            worker.process_one(URL, "replacement", queue)
    assert len(renders) == 1
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone()[0] == "held"
        assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (owner,)).fetchone()[0] == 0


@pytest.mark.parametrize("boundary", ["stage_before_checkpoint", "checkpoint_before_settlement"])
def test_graph_recovers_completed_render_without_repeating_it(monkeypatch, queued_job, boundary):
    owner, job, reservation, queue = queued_job
    renders = []
    crashed = False
    original_build = graph.build_worker_graph
    original_run = worker.run_worker_graph

    def render(source, root, output_id, platforms):
        renders.append(output_id)
        return {"tiktok": {"key": f"runs/{output_id}/final.mp4", "caption": ""}}

    def build(render_stage, checkpointer):
        def stage(state):
            nonlocal crashed
            result = render_stage(state)
            if boundary == "stage_before_checkpoint" and not crashed:
                crashed = True
                raise ProcessCrash()
            return result
        return original_build(stage, checkpointer)

    def run(*args):
        nonlocal crashed
        result = original_run(*args)
        if boundary == "checkpoint_before_settlement" and not crashed:
            crashed = True
            raise ProcessCrash()
        return result

    monkeypatch.setattr(worker, "_render_fake", render)
    monkeypatch.setattr(graph, "build_worker_graph", build)
    monkeypatch.setattr(worker, "run_worker_graph", run)
    with pytest.raises(ProcessCrash):
        worker.process_one(URL, "crashed-worker", queue)
    with psycopg.connect(URL) as c:
        run_id, thread_id = c.execute("SELECT id,thread_id FROM app.job_runs WHERE job_id=%s", (job,)).fetchone()
        assert c.execute("SELECT count(*) FROM app.job_stages WHERE run_id=%s", (run_id,)).fetchone()[0] == 1
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone()[0] == "held"
        assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (owner,)).fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM checkpoints WHERE thread_id=%s", (thread_id,)).fetchone()[0] > 0
        c.execute("UPDATE app.job_runs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (run_id,))
    assert worker.recover_expired_runs(URL, queue, str(job)) == 1
    assert worker.process_one(URL, "replacement", queue)
    assert len(renders) == 1
    with psycopg.connect(URL) as c:
        result = c.execute("SELECT result FROM app.jobs WHERE id=%s AND state='delivered'", (job,)).fetchone()[0]
        assert result["exports"]["tiktok"]["key"] == f"runs/{renders[0]}/final.mp4"
        assert c.execute("SELECT count(*),max(fence) FROM app.job_runs WHERE job_id=%s", (job,)).fetchone() == (1, 2)
        assert c.execute("SELECT count(*),sum(delta) FROM app.credit_ledger WHERE account_id=%s", (owner,)).fetchone() == (1, -2)
    with postgres_checkpointer(URL) as saver:
        checkpoint = saver.get_tuple({"configurable": {"thread_id": thread_id}})
        assert checkpoint.checkpoint["channel_values"]["run_id"] == str(run_id)
        stale = FencedPostgresSaver(saver.conn, run_id, "crashed-worker", 1)
        with pytest.raises(RunLeaseLost):
            stale.put_writes(checkpoint.config, [("exports", {"corrupt": True})], "stale-task")
        with pytest.raises(RunLeaseLost):
            stale.put(checkpoint.config, checkpoint.checkpoint, checkpoint.metadata, {})
        assert saver.get_tuple({"configurable": {"thread_id": thread_id}}).checkpoint == checkpoint.checkpoint
