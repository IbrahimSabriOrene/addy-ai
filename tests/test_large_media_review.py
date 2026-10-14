import hashlib
import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

from admaker.media_review import MediaReviewPending, build_media_reviewer
from admaker.review_files import MAX_REVIEW_FILE_BYTES
from test_provider_graph import provider_job
from test_worker_leases import URL, queued_job


def test_large_review_preserves_full_bytes_and_rejects_aggregate_overflow(provider_job, monkeypatch, tmp_path):
    _, job, _, _ = provider_job
    for key, value in {
        "ENABLE_REAL_MEDIA_REVIEW": "true", "MEDIA_REVIEW_ESTIMATE_MICROUSD": "1",
        "MEDIA_REVIEW_DAILY_BUDGET_MICROUSD": "1000000000",
        "MEDIA_REVIEW_MAX_CALLS_PER_RUN": "3", "MEDIA_REVIEW_MAX_CONCURRENT_CALLS": "10",
    }.items():
        monkeypatch.setenv(key, value)
    verdict = {"policyAllowed": True, "qualityPassed": True, "offerFree": False}
    observed = []
    video = tmp_path / "large.mp4"
    # The codec is a separate tested boundary; exercise real SDK conversion on
    # a payload larger than the former 12 MiB ceiling without a live model call.
    video.write_bytes(b"video-with-audio" * (1024 * 1024))
    expected = hashlib.sha256(video.read_bytes()).hexdigest()

    class Model:
        def __init__(self, **kwargs):
            assert kwargs["max_retries"] == 0

        def with_structured_output(self, *args, **kwargs):
            return self

        def invoke(self, messages, config):
            from langchain_google_genai.chat_models import _convert_to_parts
            blobs = [part.inline_data for part in _convert_to_parts(messages[1][1]) if part.inline_data]
            assert [blob.mime_type for blob in blobs] == ["image/png", "video/mp4"]
            assert hashlib.sha256(blobs[1].data).hexdigest() == expected
            assert len(blobs[1].data) == video.stat().st_size
            assert sum(4 * ((len(blob.data) + 2) // 3) for blob in blobs) < 100_000_000
            observed.append(True)
            return verdict

    monkeypatch.setattr("langchain_google_genai.ChatGoogleGenerativeAI", Model)
    monkeypatch.setattr("admaker.media_review.validate_video", lambda path: {"hasAudio": True})
    run = uuid.uuid4()
    exports = {"video": {"key": video.name}}
    with psycopg.connect(URL) as connection:
        connection.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state) VALUES (%s,%s,1,%s,'running')", (run, job, str(run)))
        connection.execute("INSERT INTO app.job_stages(run_id,stage_key,request_hash,result,fence) VALUES (%s,'provider_compose','large-fixture',%s,1)", (run, Jsonb(exports)))
    try:
        review = build_media_reviewer(URL, job, run, "gemini-fixture")
        assert review(tmp_path, exports) == verdict
        assert review(tmp_path, exports) == verdict
        assert observed == [True]  # The persisted verdict still prevents another paid call.
        with video.open("wb") as stream:
            stream.truncate(MAX_REVIEW_FILE_BYTES + 1)
        # Oversized media is rejected before any transfer or paid review receipt.
        with pytest.raises(MediaReviewPending, match="file limit"):
            review(tmp_path, exports)
        assert observed == [True]
        with psycopg.connect(URL) as connection:
            assert connection.execute("SELECT count(*) FROM app.media_review_budget WHERE run_id=%s", (run,)).fetchone() == (1,)
    finally:
        with psycopg.connect(URL) as connection:
            connection.execute("DELETE FROM app.media_review_budget WHERE run_id=%s", (run,))
