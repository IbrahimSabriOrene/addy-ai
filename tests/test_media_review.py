import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

from admaker.media_review import build_media_reviewer, MediaReviewPending
from test_provider_graph import provider_job
from test_worker_leases import URL, queued_job


def test_owned_audiovisual_review_has_strict_verdict_and_no_retry(provider_job, monkeypatch, tmp_path):
    account, job, _, _ = provider_job
    with pytest.raises(ValueError, match="disabled"):
        build_media_reviewer(URL, job, uuid.uuid4(), "gemini-fixture")
    monkeypatch.setenv("ENABLE_REAL_MEDIA_REVIEW", "true")
    monkeypatch.setenv("MEDIA_REVIEW_ESTIMATE_MICROUSD", "1")
    monkeypatch.setenv("MEDIA_REVIEW_DAILY_BUDGET_MICROUSD", "1000000000")
    monkeypatch.setenv("MEDIA_REVIEW_MAX_CALLS_PER_RUN", "2")
    monkeypatch.setenv("MEDIA_REVIEW_MAX_CONCURRENT_CALLS", "10")
    calls, configurations = [], []
    result = {"policyAllowed": True, "qualityPassed": True, "offerFree": True}
    class Model:
        def __init__(self, **kwargs):
            configurations.append(kwargs)
        def with_structured_output(self, schema, **kwargs):
            assert kwargs == {"method": "json_schema"}
            return self
        def invoke(self, messages, config):
            calls.append(messages)
            assert config == {"callbacks": []}
            return result
    monkeypatch.setattr("langchain_google_genai.ChatGoogleGenerativeAI", Model)
    monkeypatch.setattr("admaker.media_review.validate_video", lambda path: {"hasAudio": True})
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video includes audio: injected codec boundary")
    exports = {"tiktok": {"key": video.name}}
    run = uuid.uuid4()
    with psycopg.connect(URL) as c:
        c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state) VALUES (%s,%s,1,%s,'running')", (run, job, str(run)))
        c.execute("INSERT INTO app.job_stages(run_id,stage_key,request_hash,result,fence) VALUES (%s,'provider_compose','fixture',%s,1)", (run, Jsonb(exports)))
    review = build_media_reviewer(URL, job, run, "gemini-fixture")
    assert configurations[0]["vertexai"] is False and configurations[0]["max_retries"] == 0
    assert configurations[0]["max_output_tokens"] == 512 and configurations[0]["timeout"] == 60
    assert review(tmp_path, exports) == result
    media = [part for part in calls[0][1][1] if part["type"] == "media"]
    assert media[0]["mime_type"] == "image/png" and media[0]["data"] == (tmp_path / "test.png").read_bytes()
    assert media[1]["mime_type"] == "video/mp4" and media[1]["data"] == video.read_bytes()
    from langchain_google_genai.chat_models import _convert_to_parts
    converted = _convert_to_parts(calls[0][1][1])
    blobs = [part.inline_data for part in converted if part.inline_data is not None]
    assert [blob.mime_type for blob in blobs] == ["image/png", "video/mp4"]
    assert blobs[1].data == video.read_bytes()
    with pytest.raises(MediaReviewPending, match="Owned"):
        review(tmp_path, {"tiktok": {"key": "foreign.mp4"}})
    assert len(calls) == 1
    assert review(tmp_path, exports) == result
    assert len(calls) == 1  # Persisted exact-byte result skips the model.
    video.write_bytes(b"different video to review")
    result = {"policyAllowed": "true", "qualityPassed": True, "offerFree": True}
    with pytest.raises(MediaReviewPending, match="valid verdict"):
        review(tmp_path, exports)
    assert len(calls) == 2
    with pytest.raises(MediaReviewPending):
        review(tmp_path, exports)
    assert len(calls) == 2  # Exhausted cap stops before invoking the SDK.
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT count(*) FROM app.media_review_budget WHERE run_id=%s", (run,)).fetchone() == (2,)
        c.execute("DELETE FROM app.media_review_budget WHERE run_id=%s", (run,))
        c.execute("UPDATE app.ai_consent SET granted=false WHERE account_id=%s", (account,))
    with pytest.raises(PermissionError):
        review(tmp_path, exports)
    assert len(calls) == 2
