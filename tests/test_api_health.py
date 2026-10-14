from fastapi.testclient import TestClient

from admaker.api import app


def test_live_does_not_need_database() -> None:
    response = TestClient(app).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_requires_database_configuration(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    response = TestClient(app).get("/health/ready")

    assert response.status_code == 503


def test_account_and_credits_match_mobile_contract(monkeypatch) -> None:
    from admaker.auth import Subject, authenticated_subject

    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:54322/postgres")
    app.dependency_overrides[authenticated_subject] = lambda: Subject("00000000-0000-0000-0000-000000000001", "merchant@example.com")
    try:
        client = TestClient(app)
        assert client.get("/v1/account").json() == {"name": "merchant", "email": "merchant@example.com", "initial": "M"}
        assert client.get("/v1/credits").json()["pack"] is None
    finally:
        app.dependency_overrides.clear()


def test_job_list_uses_owner_scoped_cursor(monkeypatch) -> None:
    import uuid
    import psycopg
    from admaker.auth import Subject, authenticated_subject
    from admaker.db import migrate

    database_url = "postgresql://postgres:postgres@localhost:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", database_url)
    migrate()
    owner_id, asset_key = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(database_url) as connection:
        connection.execute("INSERT INTO app.accounts (id, email) VALUES (%s,%s)", (owner_id, f"cursor-{owner_id}@example.com"))
        connection.execute("INSERT INTO app.assets (asset_key, owner_id, storage_key, mime_type, verification_state) VALUES (%s,%s,%s,'image/jpeg','verified')", (asset_key, owner_id, f"test/{asset_key}.jpg"))
        for offset in range(3):
            connection.execute("INSERT INTO app.jobs (id, owner_id, source_asset_id, state, created_at) VALUES (%s,%s,%s,'delivered',now() - %s * interval '1 second')", (uuid.uuid4(), owner_id, asset_key, offset))
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(owner_id), "cursor@example.com")
    try:
        client = TestClient(app)
        first = client.get("/v1/jobs?limit=2").json()
        second = client.get(f"/v1/jobs?limit=2&cursor={first['nextCursor']}").json()
        assert len(first["items"]) == 2
        assert len(second["items"]) == 1
        assert {job["id"] for job in first["items"]}.isdisjoint(job["id"] for job in second["items"])
        assert client.get("/v1/jobs?cursor=bad").status_code == 422
    finally:
        app.dependency_overrides.clear()
