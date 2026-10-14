import asyncio
import io
import uuid
from datetime import datetime, timezone

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from starlette.requests import Request

from admaker.api import app, upload_bytes
from admaker.auth import Subject, authenticated_subject
from admaker.db import migrate


def test_upload_deadline_before_during_and_after_upload(monkeypatch, tmp_path):
    url = "postgresql://postgres:postgres@localhost:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("LOCAL_ASSET_ROOT", str(tmp_path))
    migrate(url)
    subject = Subject(str(uuid.uuid4()), "expiry@example.com")
    app.dependency_overrides[authenticated_subject] = lambda: subject
    output = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(output, "PNG")
    content = output.getvalue()
    client = TestClient(app)

    def start():
        response = client.post("/v1/uploads/presign", json={"mimeType": "image/png", "sizeBytes": len(content)})
        assert response.status_code == 201
        result = response.json()
        assert 890 < (datetime.fromisoformat(result["expiresAt"]) - datetime.now(timezone.utc)).total_seconds() <= 905
        return result

    def expire(key):
        with psycopg.connect(url) as c:
            c.execute("UPDATE app.assets SET created_at=clock_timestamp()-interval '16 minutes' WHERE asset_key=%s", (key,))

    try:
        first = start()
        expire(first["assetKey"])
        assert client.put(first["uploadUrl"], content=content, headers=first["headers"]).status_code == 410
        assert client.post("/v1/uploads/complete", json={"assetKey": first["assetKey"]}).status_code == 410

        second = start()
        assert client.put(second["uploadUrl"], content=content, headers=second["headers"]).status_code == 204
        expire(second["assetKey"])
        assert client.post("/v1/uploads/complete", json={"assetKey": second["assetKey"]}).status_code == 410

        third = start()
        async def receive():
            expire(third["assetKey"])
            return {"type": "http.request", "body": content, "more_body": False}

        request = Request({"type": "http", "headers": [(b"content-type", b"image/png")]}, receive)
        with pytest.raises(HTTPException) as error:
            asyncio.run(upload_bytes(uuid.UUID(third["assetKey"]), request, subject))
        assert error.value.status_code == 410
        assert not (tmp_path / f"incoming/{subject.id}/{third['assetKey']}.png").exists()

        fourth = start()
        assert client.put(fourth["uploadUrl"], content=content, headers=fourth["headers"]).status_code == 204
        assert client.post("/v1/uploads/complete", json={"assetKey": fourth["assetKey"]}).status_code == 200
        expire(fourth["assetKey"])
        assert client.post("/v1/uploads/complete", json={"assetKey": fourth["assetKey"]}).status_code == 200
        assert client.get(f"/v1/assets/{fourth['assetKey']}").status_code == 200
    finally:
        app.dependency_overrides.clear()
        with psycopg.connect(url) as c:
            c.execute("DELETE FROM app.assets WHERE owner_id=%s", (subject.id,))
            c.execute("DELETE FROM app.credit_ledger WHERE account_id=%s", (subject.id,))
            c.execute("DELETE FROM app.accounts WHERE id=%s", (subject.id,))
