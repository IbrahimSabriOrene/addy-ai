import uuid

import psycopg

from test_worker_leases import URL, queued_job


def test_events_are_atomic_deduplicated_private_and_deleted_with_job(queued_job):
    _, job, _, _ = queued_job
    run = uuid.uuid4()
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT detail->>'state' FROM app.job_events WHERE job_id=%s", (job,)).fetchall() == [("submitted",)]
        c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state) VALUES (%s,%s,1,%s,'running')", (run, job, str(run)))
        c.execute("UPDATE app.jobs SET state='running',active_run_id=%s WHERE id=%s", (run, job))
        c.execute("UPDATE app.jobs SET state='running' WHERE id=%s", (job,))
        for _ in range(2):
            c.execute("INSERT INTO app.job_stages(run_id,stage_key,request_hash,result,fence) VALUES (%s,'provider_compose','secret-hash','{\"prompt\":\"private\"}',0) ON CONFLICT DO NOTHING", (run,))
        events = c.execute("SELECT detail FROM app.job_events WHERE job_id=%s ORDER BY occurred_at", (job,)).fetchall()
        assert len(events) == 3
        assert events[-1][0] == {"kind": "stage_recorded", "stage": "provider_compose"}
        assert c.execute("SELECT has_table_privilege('authenticated','app.job_events','SELECT')").fetchone() == (False,)
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.jobs SET state='failed' WHERE id=%s", (job,))
        c.rollback()
        assert c.execute("SELECT count(*) FROM app.job_events WHERE job_id=%s", (job,)).fetchone() == (3,)
        c.execute("UPDATE app.jobs SET active_run_id=NULL WHERE id=%s", (job,))
        c.execute("DELETE FROM app.job_runs WHERE id=%s", (run,))
        assert c.execute("SELECT count(*) FROM app.job_events WHERE run_id=%s", (run,)).fetchone() == (0,)
    # The shared fixture deletes the job and checks FK cleanup on exit.
