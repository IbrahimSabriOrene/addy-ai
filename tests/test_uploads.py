import io
import uuid

from fastapi.testclient import TestClient
from PIL import Image

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.db import migrate


def _image() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (32, 32), "red").save(output, format="JPEG")
    return output.getvalue()


def test_upload_is_private_and_verified(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:54322/postgres")
    monkeypatch.setenv("LOCAL_ASSET_ROOT", str(tmp_path))
    migrate()
    owner = Subject(str(uuid.uuid4()), "owner@example.com")
    other = Subject(str(uuid.uuid4()), "other@example.com")
    app.dependency_overrides[authenticated_subject] = lambda: owner
    client = TestClient(app)
    try:
        response = client.post("/v1/uploads/presign", json={"mimeType": "image/jpeg", "sizeBytes": len(_image())})
        assert response.status_code == 201
        asset_key = response.json()["assetKey"]
        assert client.put(f"/v1/uploads/{asset_key}", content=_image(), headers={"Content-Type": "image/jpeg"}).status_code == 204
        app.dependency_overrides[authenticated_subject] = lambda: other
        assert client.post("/v1/uploads/complete", json={"assetKey": asset_key}).status_code == 404
        app.dependency_overrides[authenticated_subject] = lambda: owner
        assert client.post("/v1/uploads/complete", json={"assetKey": asset_key}).json()["state"] == "verified"
    finally:
        app.dependency_overrides.clear()


def test_invalid_token_is_rejected() -> None:
    assert TestClient(app).get("/v1/account").status_code == 401
