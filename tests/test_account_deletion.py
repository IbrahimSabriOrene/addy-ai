import uuid

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject
from admaker.consent import DISCLOSURE_VERSION, require_ai_consent
from admaker.db import RunLeaseLost, lock_run_lease
from admaker.worker import process_one, recover_expired_runs
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("running", [False, True])
def test_deletion_replay_blocks_access_and_fences_pending_jobs(queued_job, monkeypatch, running):
    account, job, reservation, queue = queued_job
    run, attempt = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setenv("DATABASE_URL", URL)

    def identity(token):
        if token != "owner-token":
            raise HTTPException(401, "invalid token")
        return Subject(str(account), "owner@example.com")

    monkeypatch.setattr("admaker.auth.verify_access_token", identity)
    with psycopg.connect(URL) as c:
        c.execute("INSERT INTO app.ai_consent(account_id,disclosure_version,granted) VALUES (%s,%s,true)", (account, DISCLOSURE_VERSION))
        if running:
            c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state,lease_owner,lease_until,fence) VALUES (%s,%s,1,%s,'running','old-worker',clock_timestamp()+interval '60 seconds',1)", (run, job, str(run)))
            c.execute("INSERT INTO app.job_attempts(id,run_id,reservation_id,sequence,state,request_hash) VALUES (%s,%s,%s,1,'running','fixture')", (attempt, run, reservation))
            c.execute("UPDATE app.jobs SET state='running',active_run_id=%s WHERE id=%s", (run, job))
    try:
        with TestClient(app) as client:
            assert client.post("/v1/account/deletion", json={"confirmation": "DELETE"}).status_code == 401
            headers = {"Authorization": "Bearer owner-token"}
            assert client.post("/v1/account/deletion", headers=headers, json={"confirmation": "no"}).status_code == 422
            for _ in range(2):
                response = client.post("/v1/account/deletion", headers=headers, json={"confirmation": "DELETE"})
                assert response.status_code == 202 and response.json() == {"state": "requested"}
            for path in ("/v1/account", "/v1/products", f"/v1/jobs/{job}"):
                assert client.get(path, headers=headers).status_code == 410
        with pytest.raises(PermissionError):
            require_ai_consent(str(account))
        assert recover_expired_runs(URL, queue, str(job)) == 0
        assert process_one(URL, "after-deletion", queue)  # Archives the old message without rendering.
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT state FROM app.jobs WHERE id=%s", (job,)).fetchone() == ("aborted",)
            assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("released",)
            assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
            if running:
                assert c.execute("SELECT fence,state FROM app.job_runs WHERE id=%s", (run,)).fetchone() == (2, "aborted")
                with pytest.raises(RunLeaseLost):
                    lock_run_lease(c, run, "old-worker", 1)
            c.execute("SET LOCAL ROLE authenticated")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("SELECT * FROM app.account_deletions")
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.ai_consent WHERE account_id=%s", (account,))
            c.execute("DELETE FROM app.account_deletions WHERE account_id=%s", (account,))
