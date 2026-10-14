import uuid

import psycopg

from admaker.ops_status import operational_snapshot
from test_worker_leases import URL, queued_job


def test_snapshot_queue_and_expired_work_without_mutation(queued_job):
    owner, job, reservation, queue = queued_job
    with psycopg.connect(URL) as c:
        c.execute("UPDATE pgmq." + '"q_' + queue + '"' + " SET enqueued_at=now()-interval '2 minutes'")
        run = uuid.uuid4()
        c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state,lease_until) VALUES (%s,%s,1,%s,'running',now()-interval '3 minutes')", (run, job, str(run)))
        c.execute("UPDATE app.jobs SET active_run_id=%s,state='running' WHERE id=%s", (run, job))
    before = operational_snapshot(URL, queue)
    assert before['queueMessages'] == 1 and before['queueVisibleMessages'] == 1
    assert before['queueOldestAgeSeconds'] >= 120
    assert before['recoverableExpiredRuns'] >= 1 and before['oldestExpiredLeaseSeconds'] >= 180
    assert before['heldCredits'] >= 2
    assert str(owner) not in str(before) and str(job) not in str(before)
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ('held',)
        c.execute("UPDATE app.job_runs SET next_work_at=now()+interval '1 hour' WHERE id=%s", (run,))
    deferred = operational_snapshot(URL, queue)
    assert deferred['recoverableExpiredRuns'] == before['recoverableExpiredRuns'] - 1
    assert deferred['queueMessages'] == 1
