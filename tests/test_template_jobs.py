import uuid

from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject


def test_invalid_template_requests_never_open_database(monkeypatch):
    def no_database():
        raise AssertionError("Invalid selection reached database/credits")

    monkeypatch.setattr("admaker.api._connection", no_database)
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(uuid.uuid4()), "template@example.com")
    base = {"assetKey": str(uuid.uuid4()), "platforms": ["reels"], "fastMode": False}
    try:
        with TestClient(app) as client:
            for extra in ({"outputKind": "photo"}, {"templateId": "pedestal_spin"},
                          {"templateId": "missing", "templateVersion": 1},
                          {"templateId": "pedestal_spin", "templateVersion": 99}):
                assert client.post("/v1/jobs", json={**base, **extra}, headers={"Idempotency-Key": "test"}).status_code == 422
    finally:
        app.dependency_overrides.clear()
