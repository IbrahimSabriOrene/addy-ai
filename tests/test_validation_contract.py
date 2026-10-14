import uuid

from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject


def test_validation_errors_use_safe_mobile_contract():
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(uuid.uuid4()), "validation@example.com")
    try:
        with TestClient(app) as client:
            for path, payload in (
                ("/v1/uploads/presign", {"mimeType": "image/png", "sizeBytes": -1}),
                ("/v1/products", {"name": "Private product name", "assetKey": "private-invalid-asset"}),
                ("/v1/campaigns", {"productId": "private-invalid-product", "imageVersion": 0}),
            ):
                response = client.post(path, json=payload)
                assert response.status_code == 422
                body = response.json()
                assert body["code"] == "invalid_request"
                assert body["message"]
                assert body["fields"]
                uuid.UUID(body["traceId"])
                assert "private-invalid" not in response.text
                assert "Private product name" not in response.text
            malformed = client.post("/v1/products", content="{broken", headers={"Content-Type": "application/json"})
            assert malformed.status_code == 422
            assert malformed.json()["code"] == "invalid_request"
            assert "{broken" not in malformed.text
    finally:
        app.dependency_overrides.clear()
