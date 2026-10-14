import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.db import migrate


def test_parallel_job_replay_and_cross_job_key_conflict(monkeypatch):
    url = "postgresql://postgres:postgres@localhost:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", url)
    migrate()
    owner, asset = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(url) as c:
        c.execute("INSERT INTO app.accounts(id,email) VALUES (%s,'race@example.com')", (owner,))
        c.execute("INSERT INTO app.assets(asset_key,owner_id,storage_key,mime_type,verification_state) VALUES (%s,%s,%s,'image/png','verified')", (asset, owner, str(asset)))
        c.execute("INSERT INTO app.credit_ledger(account_id,delta,event_key) VALUES (%s,2,%s)", (owner, str(owner)))
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(owner), "race@example.com")
    payload = {"assetKey": str(asset), "platforms": ["reels"], "fastMode": False}
    try:
        with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: client.post("/v1/jobs", json=payload, headers={"Idempotency-Key": "same"}), range(2)))
            assert [r.status_code for r in results] == [202, 202]
            assert results[0].json() == results[1].json()
            first = results[0].json()["id"]
            second = client.post("/v1/jobs", json=payload, headers={"Idempotency-Key": "second"}).json()["id"]
            with psycopg.connect(url) as c:
                c.execute("UPDATE app.jobs SET state='awaiting_user_decision' WHERE owner_id=%s", (owner,))
            route = f"/v1/jobs/{first}/decision"
            version = client.get(f"/v1/jobs/{first}").json()["version"]
            assert client.post(route, json={"action": "abort", "expectedVersion": version}, headers={"Idempotency-Key": "abort"}).status_code == 202
            assert client.post(f"/v1/jobs/{second}/decision", json={"action": "abort", "expectedVersion": version}, headers={"Idempotency-Key": "abort"}).status_code == 409
            with psycopg.connect(url) as c:
                assert c.execute("SELECT count(*) FROM app.credit_reservations WHERE account_id=%s", (owner,)).fetchone()[0] == 2
    finally:
        app.dependency_overrides.clear()
        with psycopg.connect(url) as c:
            c.execute("DELETE FROM app.command_keys WHERE account_id=%s", (owner,))
            c.execute("DELETE FROM app.credit_reservations WHERE account_id=%s", (owner,))
            c.execute("DELETE FROM app.jobs WHERE owner_id=%s", (owner,))
            c.execute("DELETE FROM app.credit_ledger WHERE account_id=%s", (owner,))
            c.execute("DELETE FROM app.assets WHERE owner_id=%s", (owner,))
            c.execute("DELETE FROM app.accounts WHERE id=%s", (owner,))
