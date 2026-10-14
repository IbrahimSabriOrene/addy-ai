import hashlib
import json
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker import worker
from test_worker_leases import URL, queued_job


@pytest.fixture
def decision_job(queued_job, monkeypatch, tmp_path):
    account, job, reservation, queue = queued_job
    run, attempt = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("LOCAL_ASSET_ROOT", str(tmp_path))
    (tmp_path / "private").mkdir()
    (tmp_path / "private/candidate.mp4").write_bytes(b"reviewed fixture")
    exports = {"tiktok": {"key": "private/candidate.mp4", "sha256": hashlib.sha256(b"reviewed fixture").hexdigest()}}
    validation = {"technicalPassed": True, "policyAllowed": True, "reservationId": str(reservation),
                  "exportsHash": hashlib.sha256(json.dumps(exports, sort_keys=True).encode()).hexdigest()}
    with psycopg.connect(URL) as c:
        c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state) VALUES (%s,%s,1,%s,'awaiting_user_decision')", (run, job, str(run)))
        c.execute("INSERT INTO app.job_attempts(id,run_id,reservation_id,sequence,state,request_hash,provider_state) VALUES (%s,%s,%s,1,'running','fixture','ready')", (attempt, run, reservation))
        c.execute("UPDATE app.jobs SET state='awaiting_user_decision',active_run_id=%s,result=%s WHERE id=%s", (run, Jsonb({"exports": exports, "candidateValidation": validation}), job))
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "decision@example.com")
    try:
        with TestClient(app) as client:
            yield client, account, job, reservation, queue, run, attempt
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.command_keys WHERE account_id=%s", (account,))
            c.execute("DELETE FROM pgmq.q_commands WHERE message->>'jobId'=%s", (str(job),))


@pytest.mark.parametrize("balance", [0, 2])
def test_spend_more_closes_prior_attempt_and_worker_uses_new_reservation(decision_job, monkeypatch, balance):
    client, account, job, reservation, queue, run, attempt = decision_job
    with psycopg.connect(URL) as c:
        c.execute("INSERT INTO app.credit_ledger(account_id,delta,event_key) VALUES (%s,%s,%s)", (account, balance, str(uuid.uuid4())))
    version = client.get(f"/v1/jobs/{job}").json()["version"]
    payload = {"action": "spend_more", "expectedVersion": version}
    headers = {"Idempotency-Key": "new-attempt"}
    response = client.post(f"/v1/jobs/{job}/decision", json=payload, headers=headers)
    if balance == 0:
        assert response.status_code == 409
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone()[0] == "held"
            assert c.execute("SELECT state FROM app.job_runs WHERE id=%s", (run,)).fetchone()[0] == "awaiting_user_decision"
            assert c.execute("SELECT count(*) FROM app.command_keys WHERE account_id=%s", (account,)).fetchone()[0] == 0
        return
    assert response.status_code == 202
    assert client.post(f"/v1/jobs/{job}/decision", json=payload, headers=headers).json() == response.json()
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone()[0] == "released"
        assert c.execute("SELECT state FROM app.job_attempts WHERE id=%s", (attempt,)).fetchone()[0] == "failed"
        assert c.execute("SELECT state FROM app.job_runs WHERE id=%s", (run,)).fetchone()[0] == "failed"
    monkeypatch.setattr(worker, "_render_fake", lambda *args: {"tiktok": {"key": "new/result.mp4"}})
    assert worker.process_one(URL, "replacement", queue)
    with psycopg.connect(URL) as c:
        rows = c.execute("SELECT a.reservation_id,a.state FROM app.job_attempts a JOIN app.job_runs r ON r.id=a.run_id WHERE r.job_id=%s ORDER BY r.sequence", (job,)).fetchall()
        assert rows[0] == (reservation, "failed") and rows[1][0] != reservation and rows[1][1] == "delivered"
        assert c.execute("SELECT delta FROM app.credit_ledger WHERE account_id=%s AND delta<0", (account,)).fetchall() == [(-1,)]


@pytest.mark.parametrize("field,value", [("technicalPassed", False), ("policyAllowed", False), ("exportsHash", "changed"), ("reservationId", "other")])
def test_accept_rejects_unvalidated_or_wrong_attempt_candidate(decision_job, field, value):
    client, account, job, reservation, queue, run, attempt = decision_job
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.jobs SET result=jsonb_set(result,%s,%s) WHERE id=%s", (["candidateValidation", field], Jsonb(value), job))
    version = client.get(f"/v1/jobs/{job}").json()["version"]
    assert client.post(f"/v1/jobs/{job}/decision", json={"action": "accept", "expectedVersion": version}, headers={"Idempotency-Key": "accept"}).status_code == 409
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone()[0] == "held"
        assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone()[0] == 0


def test_accept_settles_bound_attempt_and_exact_amount_once(decision_job):
    client, account, job, reservation, queue, run, attempt = decision_job
    version = client.get(f"/v1/jobs/{job}").json()["version"]
    payload = {"action": "accept", "expectedVersion": version}
    for _ in range(2):
        assert client.post(f"/v1/jobs/{job}/decision", json=payload, headers={"Idempotency-Key": "accept"}).status_code == 202
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT state FROM app.job_attempts WHERE id=%s", (attempt,)).fetchone()[0] == "delivered"
        assert c.execute("SELECT state FROM app.job_runs WHERE id=%s", (run,)).fetchone()[0] == "delivered"
        assert c.execute("SELECT delta FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchall() == [(-2,)]


@pytest.mark.parametrize("problem", ["uncertain", "duplicate_reservation", "wrong_attempt"])
def test_unreconciled_decision_cannot_release_or_spend(decision_job, problem):
    client, account, job, reservation, queue, run, attempt = decision_job
    with psycopg.connect(URL) as c:
        if problem == "uncertain":
            c.execute("UPDATE app.job_attempts SET provider_state='submission_unknown' WHERE id=%s", (attempt,))
        else:
            extra = uuid.uuid4()
            c.execute("INSERT INTO app.credit_reservations(id,account_id,job_id,amount,state) VALUES (%s,%s,%s,1,'held')", (extra, account, job))
            if problem == "wrong_attempt":
                c.execute("UPDATE app.credit_reservations SET state='released' WHERE id=%s", (reservation,))
        before = c.execute("SELECT id,state FROM app.credit_reservations WHERE job_id=%s ORDER BY id", (job,)).fetchall()
    version = client.get(f"/v1/jobs/{job}").json()["version"]
    for action in ("accept", "spend_more", "abort"):
        assert client.post(f"/v1/jobs/{job}/decision", json={"action": action, "expectedVersion": version}, headers={"Idempotency-Key": action}).status_code == 409
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT id,state FROM app.credit_reservations WHERE job_id=%s ORDER BY id", (job,)).fetchall() == before
        assert c.execute("SELECT count(*) FROM app.command_keys WHERE account_id=%s", (account,)).fetchone()[0] == 0
