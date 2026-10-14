import base64
import hashlib
import io
import json

import httpx
from google import genai
from google.genai import types

from admaker.review_files import get_review_file, review_file_client, verified_review_file


def test_installed_sdk_named_upload_get_and_delete_use_mocked_http(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-review-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "fixture-review-key")
    name = "files/addy-" + "a" * 32
    data = b"complete audiovisual bytes"
    checksum = hashlib.sha256(data).hexdigest()
    remote = {"name": name, "mimeType": "video/mp4", "sizeBytes": str(len(data)),
        "sha256Hash": base64.b64encode(bytes.fromhex(checksum)).decode(),
        "uri": f"https://generativelanguage.googleapis.com/v1beta/{name}", "state": "ACTIVE"}
    present, requests = [], []

    def respond(request):
        assert request.url.host == "generativelanguage.googleapis.com"
        requests.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json=remote) if present else httpx.Response(404, json={"error": {"code": 404, "message": "missing"}})
        if request.url.path == "/upload/v1beta/files":
            assert json.loads(request.content)["file"]["name"] == name
            assert request.headers["x-goog-upload-protocol"] == "resumable"
            return httpx.Response(200, headers={"x-goog-upload-url": "https://generativelanguage.googleapis.com/upload/session"})
        if request.url.path == "/upload/session":
            assert request.content == data
            assert "finalize" in request.headers["x-goog-upload-command"]
            present.append(True)
            return httpx.Response(200, headers={"x-goog-upload-status": "final"}, json={"file": remote})
        assert request.method == "DELETE"
        present.clear()
        return httpx.Response(200, json={})

    original = genai.Client
    def client(**kwargs):
        options = kwargs["http_options"]
        assert kwargs["vertexai"] is False and options.retry_options.attempts == 1
        assert options.timeout == 60000 and options.api_version == "v1beta"
        options.client_args = {"transport": httpx.MockTransport(respond)}
        return original(**kwargs)
    monkeypatch.setattr("admaker.review_files.genai.Client", client)
    with review_file_client() as store:
        assert get_review_file(store, name) is None
        result = store.files.upload(file=io.BytesIO(data), config=types.UploadFileConfig(name=name, mime_type="video/mp4"))
        assert verified_review_file(result, name, checksum, len(data), "video/mp4")
        assert verified_review_file(get_review_file(store, name), name, checksum, len(data), "video/mp4")
        store.files.delete(name=name)
        assert get_review_file(store, name) is None
    assert [method for method, _ in requests] == ["GET", "POST", "POST", "GET", "DELETE", "GET"]
