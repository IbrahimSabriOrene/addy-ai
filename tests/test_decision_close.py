import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from test_worker_leases import URL, queued_job


def test_close_serializes_with_decision_and_preserves_credits(queued_job, monkeypatch):
    account, job, reservation, queue = queued_job
    monkeypatch.setenv("DATABASE_URL", URL)
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "fixture@example.test")
    path = f"/v1/jobs/{job}/decision"
    payload = {"action": "abort", "expectedVersion": 1}
    try:
        with psycopg.connect(URL) as c:
            c.execute("UPDATE app.jobs SET state='awaiting_user_decision' WHERE id=%s", (job,))
        with TestClient(app) as client:
            headers = {"Idempotency-Key": "closed-decision"}
            assert client.post(path + "/close", json=payload, headers=headers).json() == {"state": "cancelled"}
            assert client.post(path, json=payload, headers=headers).status_code == 409
            assert client.post(path + "/close", json={**payload, "action": "accept"}, headers=headers).status_code == 409
            assert client.post(f"/v1/jobs/{uuid.uuid4()}/decision/close", json=payload, headers={"Idempotency-Key": "missing"}).status_code == 404
            with psycopg.connect(URL) as c:
                assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ('held',)
            headers = {"Idempotency-Key": "race-decision"}
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(lambda suffix: client.post(path + suffix, json=payload, headers=headers), ["", "/close"]))
            decision, closed = responses
            assert closed.status_code == 200
            if closed.json()['state'] == 'cancelled':
                assert decision.status_code == 409
            else:
                assert decision.status_code == 202 and decision.json() == closed.json()
            with psycopg.connect(URL) as c:
                assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.command_keys WHERE account_id=%s", (account,))
