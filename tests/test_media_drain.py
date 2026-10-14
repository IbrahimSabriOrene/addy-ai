from concurrent.futures import ThreadPoolExecutor
from threading import Event

import psycopg
import pytest
from fastapi.testclient import TestClient

from admaker.account_deletion import request_account_deletion
from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.media_drain import AccountDeletionRequested, lock_media_writer, try_lock_media_cleanup
from admaker.worker import process_one
from test_worker_leases import URL, queued_job


def test_cleanup_waits_for_running_writer_and_late_writer_is_rejected(queued_job, monkeypatch, tmp_path):
    account, job, reservation, queue = queued_job
    entered, finish = Event(), Event()
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("LOCAL_ASSET_ROOT", str(tmp_path))

    def render(*args):
        entered.set()
        assert finish.wait(10)
        (tmp_path / "late.png").write_bytes(b"written by an already running renderer")
        return {"tiktok": {"key": "late.png"}}

    monkeypatch.setattr("admaker.worker._render_fake", render)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            writing = pool.submit(process_one, URL, "writer", queue)
            try:
                assert entered.wait(5)
                with psycopg.connect(URL) as c:
                    request_account_deletion(c, account)
                with psycopg.connect(URL) as c:
                    assert try_lock_media_cleanup(c, account) is False
            finally:
                finish.set()
            assert writing.result(timeout=10)
        with psycopg.connect(URL) as c:
            assert try_lock_media_cleanup(c, account) is True
            assert c.execute("SELECT state FROM app.jobs WHERE id=%s", (job,)).fetchone() == ("aborted",)
            assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
        with psycopg.connect(URL) as c, pytest.raises(AccountDeletionRequested):
            lock_media_writer(c, account)
        assert (tmp_path / "late.png").is_file()  # Safe cleanup can now remove this, never while the writer runs.
        app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "owner@example.com")
        with psycopg.connect(URL) as c:
            asset = c.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (job,)).fetchone()[0]
        with TestClient(app) as client:
            assert client.put(f"/v1/uploads/{asset}", content=b"late bytes", headers={"Content-Type": "image/png"}).status_code == 410
            assert client.post("/v1/uploads/complete", json={"assetKey": str(asset)}).status_code == 410
    finally:
        finish.set()
        app.dependency_overrides.pop(authenticated_subject, None)
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.account_deletions WHERE account_id=%s", (account,))
