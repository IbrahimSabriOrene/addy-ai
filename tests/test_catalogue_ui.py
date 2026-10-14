from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject


def test_fixture_ui_is_opt_in_and_never_advertises_live_generation(monkeypatch):
    app.dependency_overrides[authenticated_subject] = lambda: Subject("00000000-0000-0000-0000-000000000001", "test@example.com")
    try:
        client = TestClient(app)
        monkeypatch.delenv("ENABLE_LOCAL_FIXTURE_UI", raising=False)
        monkeypatch.delenv("ENABLE_REAL_VEO", raising=False)
        catalogue = client.get("/v1/catalogue").json()
        assert not catalogue["generationEnabled"]
        assert catalogue["executionMode"] == "fixture"
        assert catalogue["prices"] == {"photo": 1, "video": 1}
        monkeypatch.setenv("ENABLE_LOCAL_FIXTURE_UI", "true")
        assert client.get("/v1/catalogue").json()["generationEnabled"]
        monkeypatch.setenv("ENABLE_REAL_VEO", "true")
        assert not client.get("/v1/catalogue").json()["generationEnabled"]
    finally:
        app.dependency_overrides.clear()


def test_catalogue_separates_provider_permission_and_fixture_modes(monkeypatch):
    from admaker.catalogue_execution import catalogue_execution
    monkeypatch.setenv("ENABLE_LOCAL_FIXTURE_UI", "true")
    monkeypatch.setenv("ENABLE_REAL_VEO", "true")
    monkeypatch.setenv("ENABLE_REAL_PHOTO", "false")
    monkeypatch.setenv("ENABLE_REAL_MEDIA_REVIEW", "false")
    modes = catalogue_execution()
    assert modes["video"] == {"executionMode": "google", "generationEnabled": False, "requiresAiConsent": True}
    assert modes["photo"] == {"executionMode": "fixture", "generationEnabled": True, "requiresAiConsent": False}
    monkeypatch.setattr("admaker.provider_worker.provider_worker_configuration", lambda: ("fixture", "video", "gemini-fixture", 1))
    assert catalogue_execution()["video"] == {"executionMode": "google", "generationEnabled": True, "requiresAiConsent": True}
