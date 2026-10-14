import io
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
from fastapi.testclient import TestClient
from PIL import Image

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.db import migrate


def test_duplicate_job_command_reserves_once(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:54322/postgres")
    monkeypatch.setenv("LOCAL_ASSET_ROOT", str(tmp_path))
    monkeypatch.setenv("DEV_SEED_CREDITS", "1")
    migrate()
    owner = Subject(str(uuid.uuid4()), "owner@example.com")
    app.dependency_overrides[authenticated_subject] = lambda: owner
    image = io.BytesIO()
    Image.new("RGB", (32, 32), "red").save(image, format="JPEG")
    client = TestClient(app)
    try:
        missing_key = client.post("/v1/jobs", json={"assetKey": str(uuid.uuid4()), "platforms": ["tiktok"], "fastMode": False})
        assert missing_key.json()["code"] == "idempotency_key_is_required"
        presign = client.post("/v1/uploads/presign", json={"mimeType": "image/jpeg", "sizeBytes": len(image.getvalue())}).json()
        client.put(presign["uploadUrl"], content=image.getvalue(), headers={"Content-Type": "image/jpeg"})
        client.post("/v1/uploads/complete", json={"assetKey": presign["assetKey"]})
        payload = {"assetKey": presign["assetKey"], "platforms": ["feed"], "fastMode": False}
        headers = {"Idempotency-Key": "one-command"}
        first = client.post("/v1/jobs", json=payload, headers=headers)
        second = client.post("/v1/jobs", json=payload, headers=headers)
        assert first.status_code == second.status_code == 202
        assert first.json() == second.json()
        assert client.post("/v1/jobs", json={**payload, "platforms": ["reels"]}, headers=headers).status_code == 409
        detail = client.get(f"/v1/jobs/{first.json()['id']}")
        assert detail.status_code == 200
        assert detail.json()["platforms"] == ["feed"]
        with psycopg.connect("postgresql://postgres:postgres@localhost:54322/postgres") as connection:
            assert connection.execute("SELECT settings->'renderPlatforms' FROM app.jobs WHERE id=%s", (first.json()["id"],)).fetchone()[0] == ["feed_square"]
        assert client.post("/v1/jobs", json={**payload, "platforms": ["unknown"]}, headers={"Idempotency-Key": "invalid-platform"}).status_code == 422
        assert detail.json()["candidates"]
        assert client.get("/v1/jobs").json()["items"][0]["title"] == "Product ad"
        style_headers = {"Idempotency-Key": "style-command"}
        style = client.post(f"/v1/jobs/{first.json()['id']}/style-choice", json={"presetId": "pedestal_spin", "expectedVersion": detail.json()["version"]}, headers=style_headers)
        assert style.status_code == 202
        assert client.post(f"/v1/jobs/{first.json()['id']}/style-choice", json={"presetId": "pedestal_spin", "expectedVersion": detail.json()["version"]}, headers=style_headers).json() == style.json()
        app.dependency_overrides[authenticated_subject] = lambda: Subject(str(uuid.uuid4()), "other@example.com")
        assert client.get(f"/v1/jobs/{first.json()['id']}").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_two_concurrent_jobs_cannot_spend_one_credit(monkeypatch) -> None:
    database_url = "postgresql://postgres:postgres@localhost:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", database_url)
    migrate()
    owner_id, asset_key = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(database_url) as connection:
        connection.execute("INSERT INTO app.accounts (id, email) VALUES (%s, 'concurrent@example.com')", (owner_id,))
        connection.execute("INSERT INTO app.assets (asset_key, owner_id, storage_key, mime_type, verification_state) VALUES (%s, %s, %s, 'image/jpeg', 'verified')", (asset_key, owner_id, f"test/{asset_key}.jpg"))
        connection.execute("INSERT INTO app.credit_ledger (account_id, delta, event_key) VALUES (%s, 1, %s)", (owner_id, f"test-credit:{owner_id}"))
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(owner_id), "concurrent@example.com")
    payload = {"assetKey": str(asset_key), "platforms": ["tiktok"], "fastMode": False}
    try:
        def submit(key: str) -> int:
            return TestClient(app).post("/v1/jobs", json=payload, headers={"Idempotency-Key": key}).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(submit, ["concurrent-a", "concurrent-b"]))
        assert sorted(statuses) == [202, 409]
    finally:
        app.dependency_overrides.clear()


def test_regen_reserves_a_new_credit_once(monkeypatch) -> None:
    database_url = "postgresql://postgres:postgres@localhost:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", database_url)
    migrate()
    owner_id, asset_key, job_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(database_url) as connection:
        connection.execute("INSERT INTO app.accounts (id, email) VALUES (%s, 'regen@example.com')", (owner_id,))
        connection.execute("INSERT INTO app.assets (asset_key, owner_id, storage_key, mime_type, verification_state) VALUES (%s, %s, %s, 'image/jpeg', 'verified')", (asset_key, owner_id, f"test/{asset_key}.jpg"))
        connection.execute("INSERT INTO app.jobs (id, owner_id, source_asset_id, state, settings) VALUES (%s, %s, %s, 'delivered', %s)", (job_id, owner_id, asset_key, psycopg.types.json.Jsonb({"platforms": ["tiktok"]})))
        connection.execute("INSERT INTO app.credit_ledger (account_id, delta, event_key) VALUES (%s, 2, %s)", (owner_id, f"regen-credit:{owner_id}"))
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(owner_id), "regen@example.com")
    try:
        headers = {"Idempotency-Key": "regen-command"}
        first = TestClient(app).post(f"/v1/jobs/{job_id}/regen", json={"expectedVersion": 1}, headers=headers)
        second = TestClient(app).post(f"/v1/jobs/{job_id}/regen", json={"expectedVersion": 1}, headers=headers)
        assert first.status_code == second.status_code == 202
        with psycopg.connect(database_url) as connection:
            assert connection.execute("SELECT COUNT(*) FROM app.credit_reservations WHERE job_id=%s AND state='held'", (job_id,)).fetchone()[0] == 1
    finally:
        app.dependency_overrides.clear()


def test_abort_decision_releases_its_held_credit(monkeypatch) -> None:
    database_url = "postgresql://postgres:postgres@localhost:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", database_url)
    migrate()
    owner_id, asset_key, job_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(database_url) as connection:
        connection.execute("INSERT INTO app.accounts (id, email) VALUES (%s, %s)", (owner_id, f"decision-{owner_id}@example.com"))
        connection.execute("INSERT INTO app.assets (asset_key, owner_id, storage_key, mime_type, verification_state) VALUES (%s,%s,%s,'image/jpeg','verified')", (asset_key, owner_id, f"test/{asset_key}.jpg"))
        connection.execute("INSERT INTO app.jobs (id, owner_id, source_asset_id, state, settings) VALUES (%s,%s,%s,'awaiting_user_decision',%s)", (job_id, owner_id, asset_key, psycopg.types.json.Jsonb({"platforms": ["tiktok"]})))
        connection.execute("INSERT INTO app.credit_reservations (id, account_id, job_id, amount, state) VALUES (%s,%s,%s,1,'held')", (uuid.uuid4(), owner_id, job_id))
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(owner_id), "decision@example.com")
    try:
        headers = {"Idempotency-Key": "abort-command"}
        first = TestClient(app).post(f"/v1/jobs/{job_id}/decision", json={"action": "abort", "expectedVersion": 1}, headers=headers)
        second = TestClient(app).post(f"/v1/jobs/{job_id}/decision", json={"action": "abort", "expectedVersion": 1}, headers=headers)
        assert first.status_code == second.status_code == 202
        assert first.json() == second.json()
        with psycopg.connect(database_url) as connection:
            assert connection.execute("SELECT state FROM app.jobs WHERE id=%s", (job_id,)).fetchone()[0] == "aborted"
            assert connection.execute("SELECT state FROM app.credit_reservations WHERE job_id=%s", (job_id,)).fetchone()[0] == "released"
    finally:
        app.dependency_overrides.clear()


def test_accept_decision_consumes_its_held_credit(monkeypatch, tmp_path) -> None:
    database_url = "postgresql://postgres:postgres@localhost:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", database_url)
    migrate()
    import hashlib
    import json
    owner_id, asset_key, job_id, reservation_id = (uuid.uuid4() for _ in range(4))
    monkeypatch.setenv("LOCAL_ASSET_ROOT", str(tmp_path))
    (tmp_path / "test.mp4").write_bytes(b"reviewed fixture")
    exports = {"tiktok": {"key": "test.mp4", "sha256": hashlib.sha256(b"reviewed fixture").hexdigest()}}
    result = {"exports": exports, "candidateValidation": {"technicalPassed": True, "policyAllowed": True,
        "exportsHash": hashlib.sha256(json.dumps(exports, sort_keys=True).encode()).hexdigest(), "reservationId": str(reservation_id)}}
    with psycopg.connect(database_url) as connection:
        connection.execute("INSERT INTO app.accounts (id, email) VALUES (%s,%s)", (owner_id, f"accept-{owner_id}@example.com"))
        connection.execute("INSERT INTO app.assets (asset_key, owner_id, storage_key, mime_type, verification_state) VALUES (%s,%s,%s,'image/jpeg','verified')", (asset_key, owner_id, f"test/{asset_key}.jpg"))
        connection.execute("INSERT INTO app.jobs (id, owner_id, source_asset_id, state, settings, result) VALUES (%s,%s,%s,'awaiting_user_decision',%s,%s)", (job_id, owner_id, asset_key, psycopg.types.json.Jsonb({"platforms": ["tiktok"]}), psycopg.types.json.Jsonb(result)))
        connection.execute("INSERT INTO app.credit_reservations (id, account_id, job_id, amount, state) VALUES (%s,%s,%s,3,'held')", (reservation_id, owner_id, job_id))
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(owner_id), "accept@example.com")
    try:
        assert TestClient(app).post(f"/v1/jobs/{job_id}/decision", json={"action": "accept", "expectedVersion": 1}, headers={"Idempotency-Key": "accept-command"}).status_code == 202
        with psycopg.connect(database_url) as connection:
            assert connection.execute("SELECT state FROM app.credit_reservations WHERE job_id=%s", (job_id,)).fetchone()[0] == "consumed"
            assert connection.execute("SELECT COALESCE(SUM(delta), 0) FROM app.credit_ledger WHERE account_id=%s", (owner_id,)).fetchone()[0] == -3
    finally:
        app.dependency_overrides.clear()
