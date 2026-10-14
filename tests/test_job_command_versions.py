import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from fastapi.testclient import TestClient

from admaker.api import app, STYLE_CANDIDATES
from admaker.job_prompts import snapshot_styles
from psycopg.types.json import Jsonb
from admaker.auth import Subject, authenticated_subject
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("route,state,choice", [
    ("style-choice", "awaiting_style_choice", {"presetId": "pedestal_spin"}),
    ("decision", "awaiting_user_decision", {"action": "abort"}),
    ("regen", "delivered", {}),
])
def test_stale_gate_replay_and_concurrent_commands(queued_job, monkeypatch, route, state, choice):
    account, job, reservation, queue = queued_job
    monkeypatch.setenv("DATABASE_URL", URL)
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.jobs SET state=%s,settings=%s WHERE id=%s", (state, Jsonb({"styleOptions": snapshot_styles(STYLE_CANDIDATES)}), job))
        c.execute("INSERT INTO app.credit_ledger(account_id,delta,event_key) VALUES (%s,10,%s)", (account, str(uuid.uuid4())))
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "version@example.com")
    try:
        with TestClient(app) as client:
            url = f"/v1/jobs/{job}/{route}"
            detail = client.get(f"/v1/jobs/{job}").json()
            version = detail["version"]
            assert detail["gate"] == (None if state == "delivered" else state)
            for invalid in (None, 0, True, "1"):
                payload = choice if invalid is None else {**choice, "expectedVersion": invalid}
                assert client.post(url, json=payload, headers={"Idempotency-Key": "invalid"}).status_code == 422
            with psycopg.connect(URL) as c:
                c.execute("UPDATE app.jobs SET state='running' WHERE id=%s", (job,))
                c.execute("UPDATE app.jobs SET state=%s WHERE id=%s", (state, job))
            payload = {**choice, "expectedVersion": version}
            assert client.post(url, json=payload, headers={"Idempotency-Key": "stale"}).status_code == 409
            with psycopg.connect(URL) as c:
                assert c.execute("SELECT count(*) FROM app.credit_reservations WHERE job_id=%s", (job,)).fetchone()[0] == 1
                assert c.execute("SELECT count(*) FROM app.command_keys WHERE account_id=%s", (account,)).fetchone()[0] == 0
            payload["expectedVersion"] = client.get(f"/v1/jobs/{job}").json()["version"]
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(lambda key: client.post(url, json=payload, headers={"Idempotency-Key": key}), ["one", "two"]))
            assert sorted(response.status_code for response in responses) == [202, 409]
            accepted_index = next(i for i, response in enumerate(responses) if response.status_code == 202)
            key = ["one", "two"][accepted_index]
            assert client.post(url, json=payload, headers={"Idempotency-Key": key}).json() == responses[accepted_index].json()
            assert client.post(url, json=payload, headers={"Idempotency-Key": "third"}).status_code == 409
            with psycopg.connect(URL) as c:
                assert c.execute("SELECT count(*) FROM app.credit_reservations WHERE job_id=%s", (job,)).fetchone()[0] == (2 if route == "regen" else 1)
            app.dependency_overrides[authenticated_subject] = lambda: Subject(str(uuid.uuid4()), "other@example.com")
            assert client.post(url, json=payload, headers={"Idempotency-Key": "foreign"}).status_code == 404
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.command_keys WHERE account_id=%s", (account,))
            c.execute("DELETE FROM pgmq.q_commands WHERE message->>'jobId'=%s", (str(job),))
