import hashlib
import json
import uuid
import psycopg
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient
from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from test_worker_leases import URL, queued_job


def test_report_binds_owned_archived_snapshot(queued_job, monkeypatch, capsys):
    owner, job, *_ = queued_job
    run = uuid.uuid4()
    snapshot = {"exports": {"video": {"key": "old.mp4"}}}
    monkeypatch.setenv("DATABASE_URL", URL)
    with psycopg.connect(URL) as c:
        c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state) VALUES (%s,%s,1,%s,'delivered')", (run, job, str(run)))
        c.execute("UPDATE app.jobs SET result=%s WHERE id=%s", (Jsonb({"exports": {"video": {"key": "new.mp4"}}, "runs": {"1": snapshot}}), job))
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(owner), "fixture@example.test")
    try:
        with TestClient(app) as client:
            body = {"attemptSequence": 1, "reason": "rights", "expectedResultVersion": hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()}
            path = f"/v1/jobs/{job}/reports"
            first = client.post(path, json=body, headers={"Idempotency-Key": "archive"})
            assert first.status_code == 201
            assert client.post(path, json=body, headers={"Idempotency-Key": "archive"}).json() == first.json()
            assert client.post(path, json={**body, "attemptSequence": 2}, headers={"Idempotency-Key": "missing"}).status_code == 404
            from admaker.reports import main
            monkeypatch.setattr("sys.argv", ["reports", "show", first.json()["id"]])
            main()
            shown = json.loads(capsys.readouterr().out)
            assert shown["reported_exports"] == snapshot["exports"]
            assert shown["run_id"] == str(run) and shown["attempt_sequence"] == 1
            assert shown["owner_id"] == str(owner) and shown["status"] == "open"
            with psycopg.connect(URL) as c:
                assert c.execute("SELECT run_id,result_snapshot FROM app.result_reports WHERE job_id=%s", (job,)).fetchall() == [(run, snapshot)]
                assert c.execute("SELECT status,assignee FROM app.result_reports WHERE job_id=%s", (job,)).fetchone() == ("open", None)
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.result_reports WHERE job_id=%s", (job,))
            c.execute("DELETE FROM app.command_keys WHERE account_id=%s", (owner,))
