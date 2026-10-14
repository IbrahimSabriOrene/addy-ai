import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
from fastapi import HTTPException
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject
from admaker.db import migrate
from admaker.rate_limit import enforce_account_rate_limit
from test_worker_leases import URL


def test_shared_limit_http_recovery_and_deleted_account(monkeypatch):
    migrate(URL)
    owners = [str(uuid.uuid4()), str(uuid.uuid4())]
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("API_REQUESTS_PER_MINUTE", "3")
    monkeypatch.setattr("admaker.auth.verify_access_token", lambda token: Subject(token, ""))
    try:
        def request(_):
            try:
                enforce_account_rate_limit(owners[0])
                return 200
            except HTTPException as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(request, range(8)))
        assert results.count(200) == 3 and results.count(429) == 5
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {owners[0]}"}
            response = client.get("/v1/campaign-pack/quote", headers=headers)
            assert response.status_code == 429
            assert 1 <= int(response.headers["Retry-After"]) <= 60
            assert set(response.json()) == {"code", "message", "traceId"}
            assert client.get("/v1/campaign-pack/quote", headers={"Authorization": f"Bearer {owners[1]}"}).status_code == 200
            assert client.get("/v1/campaign-pack/quote").status_code == 401
            with psycopg.connect(URL) as c:
                c.execute("UPDATE app.api_rate_limits SET window_started_at=clock_timestamp()-interval '61 seconds' WHERE account_id=%s", (owners[0],))
            assert client.get("/v1/campaign-pack/quote", headers=headers).status_code == 200
            with psycopg.connect(URL) as c:
                assert c.execute("SELECT requests FROM app.api_rate_limits WHERE account_id=%s", (owners[0],)).fetchone() == (1,)
                c.execute("INSERT INTO app.account_deletions(account_id) VALUES (%s)", (owners[0],))
            assert client.get("/v1/campaign-pack/quote", headers=headers).status_code == 410
            try:
                enforce_account_rate_limit(owners[0])
                assert False, "Late insert/update must reject a deleted account"
            except psycopg.errors.CheckViolation:
                pass
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.api_rate_limits WHERE account_id=ANY(%s::uuid[])", (owners,))
            c.execute("DELETE FROM app.account_deletions WHERE account_id=ANY(%s::uuid[])", (owners,))
