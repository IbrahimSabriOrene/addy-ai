import hashlib
import io
import uuid

import psycopg
from fastapi.testclient import TestClient
from PIL import Image

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.db import migrate


def test_verified_source_survives_late_incoming_write(monkeypatch, tmp_path):
    database_url = "postgresql://postgres:postgres@localhost:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LOCAL_ASSET_ROOT", str(tmp_path))
    migrate()
    owner = Subject(str(uuid.uuid4()), "immutable@example.com")
    output = io.BytesIO()
    Image.new("RGB", (32, 32), "red").save(output, format="JPEG")
    data = output.getvalue()
    app.dependency_overrides[authenticated_subject] = lambda: owner
    try:
        with TestClient(app) as client:
            upload = client.post("/v1/uploads/presign", json={"mimeType": "image/jpeg", "sizeBytes": len(data)}).json()
            key = upload["assetKey"]
            assert client.put(upload["uploadUrl"], content=data, headers=upload["headers"]).status_code == 204
            assert client.post("/v1/uploads/complete", json={"assetKey": key}).status_code == 200
            with psycopg.connect(database_url) as connection:
                stored_key, checksum = connection.execute("SELECT storage_key, checksum FROM app.assets WHERE asset_key=%s", (key,)).fetchone()
            # A PUT that read pending state before completion can finish later.
            (tmp_path / f"incoming/{owner.id}/{key}.jpg").write_bytes(b"late overwrite")
            assert stored_key == f"verified/{owner.id}/{key}.jpg"
            assert hashlib.sha256((tmp_path / stored_key).read_bytes()).hexdigest() == checksum
            assert client.put(upload["uploadUrl"], content=data, headers=upload["headers"]).status_code == 409
            assert client.post("/v1/uploads/complete", json={"assetKey": key}).status_code == 200
    finally:
        app.dependency_overrides.clear()
        with psycopg.connect(database_url) as connection:
            connection.execute("DELETE FROM app.assets WHERE owner_id=%s", (owner.id,))
            connection.execute("DELETE FROM app.credit_ledger WHERE account_id=%s", (owner.id,))
            connection.execute("DELETE FROM app.accounts WHERE id=%s", (owner.id,))
