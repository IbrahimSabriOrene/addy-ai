import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from test_worker_leases import URL, queued_job


def test_concurrent_admission_is_bounded_and_replay_does_not_need_capacity(queued_job, monkeypatch):
    account, original_job, _, _ = queued_job
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("MAX_OUTSTANDING_JOBS_PER_ACCOUNT", "2")
    with psycopg.connect(URL) as c:
        asset = c.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (original_job,)).fetchone()[0]
        c.execute("INSERT INTO app.credit_ledger(account_id,delta,event_key) VALUES (%s,50,%s)", (account, str(uuid.uuid4())))
        # Unknown/held failures still occupy capacity despite their public state.
        c.execute("UPDATE app.jobs SET state='failed' WHERE id=%s", (original_job,))
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "capacity@example.test")
    body = {"assetKey": str(asset), "platforms": ["tiktok"], "fastMode": False}
    try:
        with TestClient(app) as client:
            def submit(index):
                return index, client.post("/v1/jobs", json=body, headers={"Idempotency-Key": f"capacity-{index}"})
            with ThreadPoolExecutor(max_workers=6) as pool:
                responses = list(pool.map(submit, range(6)))
            assert sorted(response.status_code for _, response in responses) == [202, 429, 429, 429, 429, 429]
            index, accepted = next(item for item in responses if item[1].status_code == 202)
            monkeypatch.setenv("MAX_OUTSTANDING_JOBS_PER_ACCOUNT", "1")
            assert client.post("/v1/jobs", json=body, headers={"Idempotency-Key": f"capacity-{index}"}).json() == accepted.json()
            with psycopg.connect(URL) as c:
                assert c.execute("SELECT count(*) FROM app.jobs WHERE owner_id=%s", (account,)).fetchone()[0] == 2
                assert c.execute("SELECT count(*) FROM app.credit_reservations WHERE account_id=%s AND state='held'", (account,)).fetchone()[0] == 2
                assert c.execute("SELECT count(*) FROM app.command_keys WHERE account_id=%s AND route='jobs'", (account,)).fetchone()[0] == 1
                c.execute("UPDATE app.credit_reservations SET state='released' WHERE job_id=%s", (accepted.json()["id"],))
                c.execute("UPDATE app.jobs SET state='delivered' WHERE id=%s", (accepted.json()["id"],))
            detail = client.get(f"/v1/jobs/{accepted.json()['id']}").json()
            assert client.post(f"/v1/jobs/{accepted.json()['id']}/regen", json={"expectedVersion": detail["version"]}, headers={"Idempotency-Key": "regen-cap"}).status_code == 429
            with psycopg.connect(URL) as c:
                c.execute("UPDATE app.credit_reservations SET state='released' WHERE job_id=%s", (original_job,))
            assert client.post("/v1/jobs", json=body, headers={"Idempotency-Key": "capacity-after-close"}).status_code == 202
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.command_keys WHERE account_id=%s", (account,))
            c.execute("DELETE FROM app.credit_reservations WHERE account_id=%s AND job_id<>%s", (account, original_job))
            c.execute("DELETE FROM app.jobs WHERE owner_id=%s AND id<>%s", (account, original_job))
