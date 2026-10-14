import base64
import io
import json
from types import SimpleNamespace

import httpx
import pytest
from google import genai
from google.genai import types
from PIL import Image

from admaker.photo_provider import PHOTO_MODEL, PhotoOutputRejected, PhotoRequest, generate_product_photo
from admaker.veo import SubmissionUnknown


def png(color):
    stream = io.BytesIO()
    Image.new("RGB", (32, 32), color).save(stream, format="PNG")
    return stream.getvalue()


def test_photo_sdk_sends_reference_and_keeps_returned_image_exact(monkeypatch):
    monkeypatch.setenv("ENABLE_REAL_PHOTO", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-photo-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "fixture-photo-key")
    consent, calls = [], []
    monkeypatch.setattr("admaker.photo_provider.require_ai_consent", consent.append)
    source, output = png("red"), png("blue")
    def respond(request):
        calls.append(request)
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.url.path == f"/v1beta/models/{PHOTO_MODEL}:generateContent"
        payload = json.loads(request.content)
        parts = payload["contents"][0]["parts"]
        assert json.loads(parts[0]["text"])["creativeDirection"] == "White background, soft light"
        assert base64.urlsafe_b64decode(parts[1]["inlineData"]["data"]) == source
        assert payload["generationConfig"]["responseModalities"] == ["IMAGE"]
        assert payload["generationConfig"]["imageConfig"] == {"aspectRatio": "9:16", "imageSize": "1K"}
        assert payload["generationConfig"]["candidateCount"] == 1
        assert "tools" not in payload and "Keep the whole product visible" in str(payload["systemInstruction"])
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"role": "model", "parts": [
            {"thought": True, "inlineData": {"mimeType": "image/png", "data": base64.b64encode(source).decode()}},
            {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(output).decode()}},
        ]}}]})
    original = genai.Client
    def client(**kwargs):
        options = kwargs["http_options"]
        assert kwargs["vertexai"] is False and options.timeout == 120000
        assert options.retry_options.attempts == 1
        options.client_args = {"transport": httpx.MockTransport(respond)}
        return original(**kwargs)
    monkeypatch.setattr("admaker.photo_provider.genai.Client", client)
    assert generate_product_photo(PhotoRequest("White background, soft light", source, "9:16"), account_id="owner") == output
    assert len(calls) == 1 and consent == ["owner", "owner"]


def test_photo_input_and_consent_guards_run_before_sdk(monkeypatch):
    calls = []
    sdk = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: calls.append(kwargs)))
    request = PhotoRequest("Clean background", png("red"))
    monkeypatch.delenv("ENABLE_REAL_PHOTO", raising=False)
    with pytest.raises(ValueError, match="disabled"):
        generate_product_photo(request, account_id="owner", client=sdk)
    monkeypatch.setenv("ENABLE_REAL_PHOTO", "true")
    with pytest.raises(ValueError):
        generate_product_photo(PhotoRequest("", request.image_bytes), account_id="owner", client=sdk)
    with pytest.raises(ValueError):
        generate_product_photo(PhotoRequest("Clean", request.image_bytes, "16:9"), account_id="owner", client=sdk)
    with pytest.raises(ValueError):
        generate_product_photo(PhotoRequest("Clean", b"not an image"), account_id="owner", client=sdk)
    def deny(account):
        raise PermissionError("No current consent")
    monkeypatch.setattr("admaker.photo_provider.require_ai_consent", deny)
    with pytest.raises(PermissionError):
        generate_product_photo(request, account_id="owner", client=sdk)
    assert not calls


@pytest.mark.parametrize("outcome", ["timeout", "blocked", "missing", "multiple", "wrong_mime"])
def test_photo_unknown_and_unusable_outputs_are_not_retried(monkeypatch, outcome):
    monkeypatch.setenv("ENABLE_REAL_PHOTO", "true")
    monkeypatch.setattr("admaker.photo_provider.require_ai_consent", lambda account: None)
    data, calls = png("red"), []
    def generate(**kwargs):
        calls.append(True)
        if outcome == "timeout":
            raise httpx.ReadTimeout("private upstream response")
        parts = [] if outcome == "missing" else [types.Part.from_bytes(data=data, mime_type="image/jpeg" if outcome == "wrong_mime" else "image/png")]
        if outcome == "multiple":
            parts *= 2
        return types.GenerateContentResponse(candidates=[types.Candidate(finish_reason="SAFETY" if outcome == "blocked" else "STOP", content=types.Content(parts=parts))])
    sdk = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    with pytest.raises(SubmissionUnknown if outcome == "timeout" else PhotoOutputRejected):
        generate_product_photo(PhotoRequest("Soft light", data), account_id="owner", client=sdk)
    assert calls == [True]
