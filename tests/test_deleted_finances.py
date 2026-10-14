import uuid

import psycopg
from psycopg.types.json import Jsonb

from admaker.account_deletion import request_account_deletion
from admaker.delete_application import delete_requested_application_data
from test_worker_leases import URL, queued_job


def test_purge_retains_costs_without_provider_prompt_or_image(queued_job):
    account, job, reservation, queue = queued_job
    run, attempt = uuid.uuid4(), uuid.uuid4()
    try:
        with psycopg.connect(URL) as c:
            c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state) VALUES (%s,%s,1,%s,'running')", (run, job, str(run)))
            c.execute("INSERT INTO app.job_attempts(id,run_id,reservation_id,sequence,state,request_hash,provider_request,estimated_cost_microusd,actual_cost_microusd,provider_state,operation_name) VALUES (%s,%s,%s,1,'running','hash',%s,400,350,'submitted',%s)", (attempt, run, reservation, Jsonb({"prompt": "private prompt", "image": "private image"}), f"operations/{attempt}"))
            request_account_deletion(c, account)
            c.execute("UPDATE app.account_deletions SET identity_deleted_at=now(),media_deleted_at=now() WHERE account_id=%s", (account,))
        delete_requested_application_data(URL, account)
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT account_id,credits,reservation_state,estimated_cost_microusd,actual_cost_microusd FROM app.deleted_attempt_finances WHERE attempt_id=%s", (attempt,)).fetchone() == (account, 2, "released", 400, 350)
            assert c.execute("SELECT count(*) FROM app.job_attempts WHERE id=%s", (attempt,)).fetchone() == (0,)
            row = c.execute("SELECT row_to_json(f)::text FROM app.deleted_attempt_finances f WHERE attempt_id=%s", (attempt,)).fetchone()[0]
            assert "private prompt" not in row and "private image" not in row
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.deleted_attempt_finances WHERE account_id=%s", (account,))
            c.execute("DELETE FROM app.account_deletions WHERE account_id=%s", (account,))
