import uuid
from types import SimpleNamespace

import psycopg
import pytest
from fastapi import HTTPException

from admaker.api import get_job
from test_worker_leases import URL, queued_job


def test_progress_is_owned_active_run_only_and_terminal_state_wins(queued_job, monkeypatch):
    account, job, reservation, _ = queued_job
    monkeypatch.setenv("DATABASE_URL", URL)
    old, active, attempt = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    subject = SimpleNamespace(id=account)
    with psycopg.connect(URL) as c:
        for sequence, run in enumerate((old, active), 1):
            c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state) VALUES (%s,%s,%s,%s,'running')", (run, job, sequence, str(run)))
        c.execute("UPDATE app.jobs SET state='running',active_run_id=%s WHERE id=%s", (active, job))
        c.execute("INSERT INTO app.job_stages(run_id,stage_key,request_hash,result,fence) VALUES (%s,'candidate_review','private','{}',0)", (old,))
    assert get_job(job, subject)["stage"] is None
    for key, expected in (("creative_plan_request", "planning"), ("input_media", "input_review")):
        with psycopg.connect(URL) as c:
            c.execute("INSERT INTO app.job_stages(run_id,stage_key,request_hash,result,fence) VALUES (%s,%s,'private','{}',0)", (active, key))
        assert get_job(job, subject)["stage"] == expected
    with psycopg.connect(URL) as c:
        c.execute("INSERT INTO app.job_attempts(id,run_id,reservation_id,sequence,state,request_hash,provider_state) VALUES (%s,%s,%s,1,'running','private','submitted')", (attempt, active, reservation))
    assert get_job(job, subject)["stage"] == "generating"
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.job_attempts SET provider_state='ready' WHERE id=%s", (attempt,))
    assert get_job(job, subject)["stage"] == "generated"
    for key, expected in (("provider_compose", "composed"), ("candidate_review", "reviewed")):
        with psycopg.connect(URL) as c:
            c.execute("INSERT INTO app.job_stages(run_id,stage_key,request_hash,result,fence) VALUES (%s,%s,'private','{}',0)", (active, key))
        assert get_job(job, subject)["stage"] == expected
    with pytest.raises(HTTPException) as denied:
        get_job(job, SimpleNamespace(id=uuid.uuid4()))
    assert denied.value.status_code == 404
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.jobs SET state='failed' WHERE id=%s", (job,))
    assert get_job(job, subject)["stage"] is None
