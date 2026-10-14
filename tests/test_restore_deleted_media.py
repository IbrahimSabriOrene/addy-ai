from datetime import datetime, timezone
import importlib.util
from pathlib import Path

import httpx
import psycopg

from admaker.account_deletion import request_account_deletion
from admaker.deletion_runner import run_account_deletion
from admaker.restore_deletions import apply_deletions
from test_worker_leases import URL, queued_job


def test_restored_file_is_removed_despite_old_completed_media_phase(queued_job, tmp_path, monkeypatch):
    account, job, _, _ = queued_job
    spec = importlib.util.spec_from_file_location("restore_media_fixture", Path(__file__).parents[1] / "tools/rehearse_media_restore.py")
    media = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(media)
    source = tmp_path / "source"
    source.mkdir()
    (source / "test.png").write_bytes(b"private original bytes")
    manifest = media.backup_media(source, tmp_path / "media.zip")
    media.restore_media(tmp_path / "media.zip", tmp_path / "restored", manifest)
    restored = tmp_path / "restored" / "test.png"
    monkeypatch.setenv("SUPABASE_URL", "https://identity.example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fixture-key")
    calls = []
    def identity(request):
        calls.append(request.method)
        assert not restored.exists()
        return httpx.Response(404, json={"code": "user_not_found"})
    try:
        with psycopg.connect(URL) as c:
            request_account_deletion(c, account)
            c.execute("UPDATE app.account_deletions SET media_deleted_at=now(),identity_deleted_at=now() WHERE account_id=%s", (account,))
        assert restored.exists()
        apply_deletions(URL, {"version": 1, "exportedAt": datetime.now(timezone.utc).isoformat(), "accounts": [str(account)]})
        with httpx.Client(transport=httpx.MockTransport(identity)) as client:
            for _ in range(2):
                assert run_account_deletion(URL, account, tmp_path / "restored", client=client) == {"state": "retention_pending"}
        assert calls == ["DELETE"]
        assert not restored.exists()
        assert (source / "test.png").read_bytes() == b"private original bytes"
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT 1 FROM app.jobs WHERE id=%s", (job,)).fetchone() is None
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.account_deletions WHERE account_id=%s", (account,))
