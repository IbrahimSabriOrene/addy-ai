import base64
import hashlib
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

import psycopg
import pytest
from google.genai import errors, types
from psycopg.types.json import Jsonb

from admaker.media_drain import AccountDeletionRequested
from admaker.media_review import MediaReviewPending, build_media_reviewer
from admaker.review_files import delete_requested_review_files, stage_review_file
from test_provider_graph import provider_job
from test_worker_leases import URL, queued_job


class Files:
    def __init__(self):
        self.objects = {}
        self.uploads = self.gets = self.deletes = 0
        self.lose_upload = self.lose_delete = False
        self.processing = False

    def get(self, *, name):
        self.gets += 1
        if name not in self.objects:
            raise errors.ClientError(404, {"error": {"code": 404, "message": "missing"}})
        return self.objects[name]

    def upload(self, *, file, config):
        self.uploads += 1
        data = file.read()
        result = types.File(name=config.name, mime_type=config.mime_type, size_bytes=len(data),
            sha256_hash=base64.b64encode(hashlib.sha256(data).digest()).decode(),
            uri=f"https://generativelanguage.googleapis.com/v1beta/{config.name}",
            state=types.FileState.PROCESSING if self.processing else types.FileState.ACTIVE)
        self.objects[config.name] = result
        if self.lose_upload:
            raise OSError("fixture lost upload response")
        return result

    def delete(self, *, name):
        self.deletes += 1
        self.objects.pop(name, None)
        if self.lose_delete:
            raise OSError("fixture lost delete response")


@pytest.fixture
def file_store(provider_job):
    account = provider_job[0]
    store = SimpleNamespace(files=Files(), credential_hash="a" * 64)
    yield store
    with psycopg.connect(URL) as connection:
        connection.execute("DELETE FROM app.review_files WHERE account_id=%s", (account,))
        connection.execute("DELETE FROM app.account_deletions WHERE account_id=%s", (account,))
        connection.execute("DELETE FROM app.media_review_budget WHERE run_id IN (SELECT id FROM app.job_runs WHERE job_id=%s)", (provider_job[1],))


def test_upload_receipt_loss_and_processing_reuse_named_file(provider_job, file_store):
    account, job, _, _ = provider_job
    file_store.files.lose_upload = True
    with pytest.raises(OSError):
        stage_review_file(URL, job, b"full video", "video/mp4", store=file_store)
    with psycopg.connect(URL) as connection:
        assert connection.execute("SELECT state FROM app.review_files WHERE account_id=%s", (account,)).fetchone() == ("pending",)
    uri = stage_review_file(URL, job, b"full video", "video/mp4", store=file_store)
    assert uri.endswith(next(iter(file_store.files.objects)))
    assert file_store.files.uploads == 1
    file_store.files.lose_upload = False
    file_store.files.processing = True
    with pytest.raises(OSError, match="processing"):
        stage_review_file(URL, job, b"second video", "video/mp4", store=file_store)
    for remote in file_store.files.objects.values():
        remote.state = types.FileState.ACTIVE
    stage_review_file(URL, job, b"second video", "video/mp4", store=file_store)
    assert file_store.files.uploads == 2
    with pytest.raises(ValueError, match="destination"):
        stage_review_file(URL, job, b"full video", "video/mp4", store=SimpleNamespace(files=file_store.files, credential_hash="b" * 64))
    with pytest.raises(ValueError, match="unavailable"):
        stage_review_file(URL, uuid.uuid4(), b"full video", "video/mp4", store=file_store)


def test_unknown_missing_upload_is_not_repeated_or_forgotten(provider_job, file_store):
    account, job, _, _ = provider_job
    file_store.files.lose_upload = True
    with pytest.raises(OSError):
        stage_review_file(URL, job, b"unknown video", "video/mp4", store=file_store)
    file_store.files.objects.clear()  # Provider outcome cannot be established.
    with pytest.raises(OSError, match="unconfirmed"):
        stage_review_file(URL, job, b"unknown video", "video/mp4", store=file_store)
    assert file_store.files.uploads == 1
    with psycopg.connect(URL) as connection:
        connection.execute("INSERT INTO app.account_deletions(account_id) VALUES (%s)", (account,))
    with pytest.raises(AccountDeletionRequested):
        stage_review_file(URL, job, b"new video", "video/mp4", store=file_store)
    with pytest.raises(OSError, match="Unconfirmed"):
        delete_requested_review_files(URL, account, store=file_store)
    with psycopg.connect(URL) as connection:
        assert connection.execute("SELECT count(*) FROM app.review_files WHERE account_id=%s", (account,)).fetchone() == (1,)


def test_deletion_recovers_lost_reply_after_unconfirmed_upload(provider_job, file_store):
    account, job, _, _ = provider_job
    file_store.files.lose_upload = file_store.files.lose_delete = True
    with pytest.raises(OSError):
        stage_review_file(URL, job, b"owned video", "video/mp4", store=file_store)
    with psycopg.connect(URL) as connection:
        connection.execute("INSERT INTO app.account_deletions(account_id) VALUES (%s)", (account,))
    with pytest.raises(OSError, match="lost delete"):
        delete_requested_review_files(URL, account, store=file_store)
    assert delete_requested_review_files(URL, account, store=file_store) == {"state": "review_files_removed"}
    assert not file_store.files.objects and file_store.files.deletes == 1


@pytest.mark.parametrize("unknown", [False, True])
def test_full_large_review_uses_verified_file_and_does_not_repeat_model(provider_job, file_store, monkeypatch, tmp_path, unknown):
    _, job, _, _ = provider_job
    for key, value in {"ENABLE_REAL_MEDIA_REVIEW": "true", "MEDIA_REVIEW_ESTIMATE_MICROUSD": "1",
        "MEDIA_REVIEW_DAILY_BUDGET_MICROUSD": "1000000000", "MEDIA_REVIEW_MAX_CALLS_PER_RUN": "3",
        "MEDIA_REVIEW_MAX_CONCURRENT_CALLS": "10"}.items():
        monkeypatch.setenv(key, value)
    @contextmanager
    def client():
        yield file_store
    monkeypatch.setattr("admaker.media_review.review_file_client", client)
    monkeypatch.setattr("admaker.media_review.validate_video", lambda path: {"hasAudio": True})
    calls = []
    verdict = {"policyAllowed": True, "qualityPassed": True, "offerFree": False}
    class Model:
        def __init__(self, **kwargs):
            pass
        def with_structured_output(self, *args, **kwargs):
            return self
        def invoke(self, messages, config):
            from langchain_google_genai.chat_models import _convert_to_parts
            parts = _convert_to_parts(messages[1][1])
            assert any(part.inline_data and part.inline_data.mime_type == "image/png" for part in parts)
            files = [part.file_data for part in parts if part.file_data]
            assert len(files) == 1 and files[0].mime_type == "video/mp4"
            assert files[0].file_uri == next(iter(file_store.files.objects.values())).uri
            calls.append(True)
            if unknown:
                raise TimeoutError("model outcome unknown")
            return verdict
    monkeypatch.setattr("langchain_google_genai.ChatGoogleGenerativeAI", Model)
    video = tmp_path / "large.mp4"
    video.write_bytes(b"v" * (65 * 1024 * 1024))
    exports = {"video": {"key": video.name}}
    run = uuid.uuid4()
    with psycopg.connect(URL) as connection:
        connection.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state) VALUES (%s,%s,1,%s,'running')", (run, job, str(run)))
        connection.execute("INSERT INTO app.job_stages(run_id,stage_key,request_hash,result,fence) VALUES (%s,'provider_compose','files-fixture',%s,1)", (run, Jsonb(exports)))
    review = build_media_reviewer(URL, job, run, "gemini-fixture")
    for _ in range(2):
        if unknown:
            with pytest.raises(MediaReviewPending):
                review(tmp_path, exports)
        else:
            assert review(tmp_path, exports) == verdict
    assert calls == [True] and file_store.files.uploads == 1 and file_store.files.gets == 1
    remote = next(iter(file_store.files.objects.values()))
    assert remote.size_bytes == video.stat().st_size
    assert remote.sha256_hash == base64.b64encode(hashlib.sha256(video.read_bytes()).digest()).decode()
