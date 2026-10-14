import json
import logging
import uuid

from fastapi.testclient import TestClient

from admaker import api


def test_unexpected_error_has_safe_envelope_and_correlated_log(monkeypatch, caplog):
    secret = "private-provider-token-fixture"
    def fail(*args, **kwargs):
        raise RuntimeError(secret)
    monkeypatch.setattr(api, "database_ready", fail)
    with caplog.at_level(logging.ERROR), TestClient(api.app, raise_server_exceptions=True) as client:
        response = client.get("/health/ready")
    assert response.status_code == 500
    body = response.json()
    assert set(body) == {"code", "message", "traceId"}
    assert body["code"] == "request_failed"
    uuid.UUID(body["traceId"])
    assert response.headers["cache-control"] == "no-store"
    assert secret not in response.text and secret not in caplog.text
    events = [json.loads(record.message) for record in caplog.records if record.message.startswith('{"event": "api_request_failed"')]
    assert events == [{"event": "api_request_failed", "traceId": body["traceId"], "errorType": "RuntimeError"}]
