import psycopg
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.campaign_failure import campaign_failure
from test_worker_leases import URL, queued_job


def test_incomplete_pack_failure_explains_hold_without_exposing_stored_error(queued_job, monkeypatch):
    account, job, reservation, queue = queued_job
    monkeypatch.setenv("DATABASE_URL", URL)
    result = {"failure": {"code": "campaign_pack_incomplete", "message": "SECRET stack trace and internal path"}}
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.jobs SET state='failed',result=%s WHERE id=%s", (Jsonb(result), job))
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "test@example.com")
    try:
        with TestClient(app) as client:
            response = client.get(f"/v1/jobs/{job}")
            assert response.status_code == 200
            assert response.json()["failure"] == campaign_failure("failed", result)
            assert "not been spent" in response.json()["failure"]["message"]
            assert "remain reserved" in response.json()["failure"]["message"]
            assert "SECRET" not in response.text
        assert campaign_failure("running", result) is None
        assert campaign_failure("failed", {"failure": {"code": "other"}}) is None
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("held",)
            assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
