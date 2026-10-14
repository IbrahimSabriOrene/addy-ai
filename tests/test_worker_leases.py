import uuid
from threading import Event, enumerate as threads

import psycopg
import pytest
from psycopg.types.json import Jsonb

from admaker.db import migrate
from admaker.worker import process_one, recover_expired_runs, renew_run_lease, run_heartbeat

URL = "postgresql://postgres:postgres@localhost:54322/postgres"


@pytest.fixture
def queued_job():
    migrate(URL)
    owner, asset, job, reservation = (uuid.uuid4() for _ in range(4))
    queue = f"leases_{uuid.uuid4().hex}"
    with psycopg.connect(URL) as c:
        c.execute("SELECT pgmq.create(%s)", (queue,))
        c.execute("INSERT INTO app.accounts(id,email) VALUES (%s,'leases@example.com')", (owner,))
        c.execute("INSERT INTO app.assets(asset_key,owner_id,storage_key,mime_type,verification_state) VALUES (%s,%s,'test.png','image/png','verified')", (asset, owner))
        c.execute("INSERT INTO app.jobs(id,owner_id,source_asset_id,state) VALUES (%s,%s,%s,'submitted')", (job, owner, asset))
        c.execute("INSERT INTO app.credit_reservations(id,account_id,job_id,amount,state) VALUES (%s,%s,%s,2,'held')", (reservation, owner, job))
        c.execute("SELECT pgmq.send(%s,%s)", (queue, Jsonb({"jobId": str(job)})))
    try:
        yield owner, job, reservation, queue
    finally:
        with psycopg.connect(URL) as c:
            c.execute("SELECT pgmq.drop_queue(%s)", (queue,))
            c.execute("UPDATE app.jobs SET active_run_id=NULL WHERE id=%s", (job,))
            c.execute("DELETE FROM app.job_attempts WHERE run_id IN (SELECT id FROM app.job_runs WHERE job_id=%s)", (job,))
            c.execute("DELETE FROM app.job_runs WHERE job_id=%s", (job,))
            c.execute("DELETE FROM app.credit_reservations WHERE job_id=%s", (job,))
            c.execute("DELETE FROM app.credit_ledger WHERE account_id=%s", (owner,))
            c.execute("DELETE FROM app.jobs WHERE id=%s", (job,))
            c.execute("DELETE FROM app.assets WHERE asset_key=%s", (asset,))
            c.execute("DELETE FROM app.accounts WHERE id=%s", (owner,))


@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.parametrize("takeover_during_render", [False, True])
def test_expired_worker_cannot_settle_or_overwrite_new_worker(monkeypatch, queued_job, fail, takeover_during_render):
    owner, job, reservation, queue = queued_job
    paths = []

    def render(source, root, output_id, platforms):
        paths.append(output_id)
        if len(paths) == 1:
            with psycopg.connect(URL) as c:
                run = c.execute("UPDATE app.job_runs SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s RETURNING id", (job,)).fetchone()[0]
            assert not renew_run_lease(URL, run, "old-worker", 1), "An expired lease cannot be revived"
            if takeover_during_render:
                assert recover_expired_runs(URL, queue, str(job)) == 1
                assert process_one(URL, "new-worker", queue)
            if fail:
                raise OSError("Old renderer failed after lease expiry")
        return {"tiktok": {"key": f"runs/{output_id}/final.mp4", "caption": ""}}

    monkeypatch.setattr("admaker.worker._render_fake", render)
    assert process_one(URL, "old-worker", queue)
    if not takeover_during_render:
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT state,result FROM app.jobs WHERE id=%s", (job,)).fetchone() == ("running", {})
            assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone()[0] == "held"
            assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (owner,)).fetchone()[0] == 0
        assert recover_expired_runs(URL, queue, str(job)) == 1
        assert recover_expired_runs(URL, queue, str(job)) == 0
        assert process_one(URL, "new-worker", queue)
    with psycopg.connect(URL) as c:
        state, result = c.execute("SELECT state,result FROM app.jobs WHERE id=%s", (job,)).fetchone()
        assert state == "delivered"
        assert result["exports"]["tiktok"]["key"] == f"runs/{paths[1]}/final.mp4"
        assert paths[0] != paths[1]
        assert c.execute("SELECT count(*),max(fence) FROM app.job_runs WHERE job_id=%s", (job,)).fetchone() == (1, 2)
        assert c.execute("SELECT count(*) FROM app.job_attempts WHERE reservation_id=%s", (reservation,)).fetchone()[0] == 1
        assert c.execute("SELECT count(*),sum(delta) FROM app.credit_ledger WHERE account_id=%s", (owner,)).fetchone() == (1, -2)


def test_heartbeat_renews_live_lease_then_stops_on_fence_loss(monkeypatch, queued_job):
    _, job, _, _ = queued_job
    run = uuid.uuid4()
    with psycopg.connect(URL) as c:
        c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state,lease_owner,lease_until,fence) VALUES (%s,%s,1,%s,'running','worker',clock_timestamp()+interval '5 seconds',1)", (run, job, str(run)))
        c.execute("UPDATE app.jobs SET state='running',active_run_id=%s WHERE id=%s", (run, job))
    pulse = Event()

    def renewal(*args):
        result = renew_run_lease(*args)
        pulse.set()
        return result

    monkeypatch.setattr("admaker.worker.renew_run_lease", renewal)
    with run_heartbeat(URL, run, "worker", 1, interval=0.02) as lost:
        assert pulse.wait(3)
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT lease_until > clock_timestamp()+interval '50 seconds' FROM app.job_runs WHERE id=%s", (run,)).fetchone()[0]
        assert recover_expired_runs(URL, job_id=str(job)) == 0
        assert not renew_run_lease(URL, run, "wrong-worker", 1)
        with psycopg.connect(URL) as c:
            c.execute("UPDATE app.job_runs SET fence=2 WHERE id=%s", (run,))
        assert lost.wait(3)
    assert not any(thread.name == "run-heartbeat" for thread in threads())
