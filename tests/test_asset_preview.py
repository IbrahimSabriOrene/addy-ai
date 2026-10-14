import io
import uuid

import psycopg
from fastapi.testclient import TestClient
from PIL import Image

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.db import migrate


def test_private_preview_requires_verified_owned_image(monkeypatch, tmp_path):
    database_url = "postgresql://postgres:postgres@localhost:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LOCAL_ASSET_ROOT", str(tmp_path))
    migrate()
    owner, other = str(uuid.uuid4()), str(uuid.uuid4())
    current = owner
    app.dependency_overrides[authenticated_subject] = lambda: Subject(current, "preview@example.com")
    image = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(image, "PNG")
    try:
        client = TestClient(app)
        asset = client.post("/v1/uploads/presign", json={"mimeType": "image/png", "sizeBytes": len(image.getvalue())}).json()
        path = f"/v1/assets/{asset['assetKey']}"
        assert client.get(path).status_code == 404
        assert client.put(asset["uploadUrl"], content=image.getvalue(), headers=asset["headers"]).status_code == 204
        assert client.get(path).status_code == 404
        assert client.post("/v1/uploads/complete", json={"assetKey": asset["assetKey"]}).status_code == 200
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.headers["cache-control"] == "private, no-store"
        assert Image.open(io.BytesIO(response.content)).size == (10, 10)
        current = other
        assert client.get(path).status_code == 404
    finally:
        app.dependency_overrides.clear()
        with psycopg.connect(database_url) as connection:
            connection.execute("DELETE FROM app.assets WHERE owner_id=%s", (owner,))
            connection.execute("DELETE FROM app.accounts WHERE id=%s", (owner,))
