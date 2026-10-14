from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from admaker.review_files import stage_review_file
from test_review_files import file_store
from test_provider_graph import provider_job
from test_worker_leases import URL, queued_job


def test_concurrent_staging_uploads_once(provider_job, file_store):
    job = provider_job[1]
    def stage(_):
        try:
            return stage_review_file(URL, job, b"same concurrent video", "video/mp4", store=file_store)
        except OSError:
            return None  # A caller racing ahead of the inserter may observe an unknown upload.
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(stage, range(6)))
    uri = stage_review_file(URL, job, b"same concurrent video", "video/mp4", store=file_store)
    assert uri in results and file_store.files.uploads == 1
    assert all(result in {None, uri} for result in results)


def test_forged_provider_metadata_and_public_table_access_are_rejected(provider_job, file_store, monkeypatch):
    account, job, _, _ = provider_job
    original = file_store.files.upload
    def forged(**kwargs):
        result = original(**kwargs)
        result.sha256_hash = "not-the-uploaded-content"
        result.uri = "https://foreign.example/media"
        return result
    monkeypatch.setattr(file_store.files, "upload", forged)
    with pytest.raises(ValueError, match="identity"):
        stage_review_file(URL, job, b"private content", "video/mp4", store=file_store)
    with psycopg.connect(URL) as connection:
        assert connection.execute("SELECT state FROM app.review_files WHERE account_id=%s", (account,)).fetchone() == ("pending",)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with psycopg.connect(URL) as connection:
            connection.execute("SET LOCAL ROLE authenticated")
            connection.execute("SELECT * FROM app.review_files")
