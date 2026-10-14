import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest
from google import genai
from google.genai import types
from PIL import Image

from admaker.veo import FAST_MODEL, VeoRequest, VeoService


def test_submit_uses_fast_model_real_image_type_and_bounded_request(monkeypatch, tmp_path):
    monkeypatch.setattr("admaker.consent.require_ai_consent", lambda _: None)
    calls = []
    service = object.__new__(VeoService)
    service.model = FAST_MODEL
    service.client = SimpleNamespace(models=SimpleNamespace(generate_videos=lambda **kwargs: calls.append(kwargs) or types.GenerateVideosOperation(name="operations/fixture")))
    photo = tmp_path / "product.png"
    Image.new("RGB", (10, 10), "red").save(photo)
    assert service.submit(VeoRequest("Keep the product label", str(photo)), account_id="fixture") == "operations/fixture"
    assert calls[0]["source"].image.mime_type == "image/png"
    assert calls[0]["model"] == FAST_MODEL
    assert calls[0]["config"].duration_seconds == 8
    assert calls[0]["config"].resolution == "1080p"
    assert calls[0]["config"].aspect_ratio == "9:16"
    for request in [VeoRequest(""), VeoRequest("x" * 4001), VeoRequest("valid", model="unapproved-model")]:
        with pytest.raises(ValueError):
            service.submit(request, account_id="fixture")
    photo.write_bytes(b"not an image")
    with pytest.raises(OSError):
        service.submit(VeoRequest("Valid", str(photo)), account_id="fixture")
    assert len(calls) == 1, "Invalid requests must fail before a provider call"
    monkeypatch.setenv("ENABLE_REAL_VEO", "true")
    monkeypatch.setenv("VEO_MODEL", "unapproved-model")
    with pytest.raises(ValueError, match="Fast"):
        VeoService()


def test_sdk_does_not_retry_generation_http_failure(monkeypatch):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            requests.append(self.path)
            body = json.dumps({"error": {"code": 503, "message": "fixture temporary failure", "status": "UNAVAILABLE"}}).encode()
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_client = genai.Client

    def local_client(**kwargs):
        assert kwargs["vertexai"] is False
        assert kwargs["http_options"].retry_options.attempts == 1
        assert kwargs["http_options"].timeout == 60_000
        kwargs["http_options"].base_url = f"http://127.0.0.1:{server.server_port}"
        return original_client(**kwargs)

    monkeypatch.setenv("ENABLE_REAL_VEO", "true")
    monkeypatch.setenv("VEO_MODEL", FAST_MODEL)
    monkeypatch.setenv("GEMINI_API_KEY", "local-fixture-key")
    monkeypatch.setattr(genai, "Client", local_client)
    monkeypatch.setattr("admaker.consent.require_ai_consent", lambda _: None)
    service = VeoService()
    try:
        with pytest.raises(genai.errors.ServerError):
            service.submit(VeoRequest("Local fixture"), account_id="fixture")
        assert len(requests) == 1, "SDK retries must not repeat a non-idempotent generation POST"
        assert "predictLongRunning" in requests[0]
    finally:
        service.client.close()
        server.shutdown()
        server.server_close()
        thread.join()


def test_poll_and_download_validate_results_and_preserve_existing_file(tmp_path):
    service = object.__new__(VeoService)
    polled = []
    calls = []
    destination = tmp_path / "final.mp4"
    destination.write_bytes(b"original")

    def download(**kwargs):
        calls.append(kwargs)
        kwargs["destination"].write_bytes(b"new-output")

    service.client = SimpleNamespace(operations=SimpleNamespace(get=lambda operation: polled.append(operation.name)), files=SimpleNamespace(download=download))
    for value in ["", "https://untrusted.invalid/operations/1", "operations/../1", "operations/a?key=bad"]:
        with pytest.raises(ValueError):
            service.poll(value)
    service.poll("operations/fixture")
    assert polled == ["operations/fixture"]
    for operation in [types.GenerateVideosOperation(done=False), types.GenerateVideosOperation(done=True, error={"code": 500}),
                      types.GenerateVideosOperation(done=True, response=types.GenerateVideosResponse()),
                      types.GenerateVideosOperation(done=True, response=types.GenerateVideosResponse(rai_media_filtered_count=1))]:
        with pytest.raises(ValueError):
            service.download(operation, str(destination))
    assert calls == [] and destination.read_bytes() == b"original"
    ready = types.GenerateVideosOperation(done=True, response=types.GenerateVideosResponse(generated_videos=[types.GeneratedVideo(video=types.Video(uri="https://provider.invalid/fixture"))]))
    service.download(ready, str(destination))
    assert destination.read_bytes() == b"new-output"

    def partial_failure(**kwargs):
        kwargs["destination"].write_bytes(b"incomplete")
        raise OSError("connection lost")

    service.client.files.download = partial_failure
    with pytest.raises(OSError):
        service.download(ready, str(destination))
    assert destination.read_bytes() == b"new-output"
    assert not list(tmp_path.glob("*.part"))
