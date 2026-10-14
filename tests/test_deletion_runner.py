import httpx
import psycopg
import pytest

from admaker.account_deletion import request_account_deletion
from admaker.deletion_runner import run_account_deletion
from admaker.media_drain import lock_media_writer
from test_worker_leases import URL, queued_job


def test_runner_waits_then_recovers_lost_identity_without_repeating_media(queued_job, tmp_path, monkeypatch):
    account, job, reservation, queue = queued_job
    monkeypatch.setenv("SUPABASE_URL", "https://identity.example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fixture-key")
    calls = []
    path = tmp_path / "test.png"
    path.write_bytes(b"private fixture")

    def respond(request):
        calls.append(request)
        assert not path.exists(), "Media must be removed before identity"
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT 1 FROM app.jobs WHERE id=%s", (job,)).fetchone()
        if len(calls) == 1:
            raise httpx.ReadTimeout("lost response", request=request)
        return httpx.Response(404, json={"code": "user_not_found"})

    try:
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(ValueError):
                run_account_deletion(URL, account, tmp_path, client=client)
            assert path.exists() and not calls
            with psycopg.connect(URL) as writer:
                lock_media_writer(writer, account)
                with psycopg.connect(URL) as c:
                    request_account_deletion(c, account)
                assert run_account_deletion(URL, account, tmp_path, client=client) == {"state": "waiting_for_writers"}
                assert path.exists() and not calls
            with pytest.raises(RuntimeError):
                run_account_deletion(URL, account, tmp_path, client=client)
            with psycopg.connect(URL) as c:
                assert c.execute("SELECT media_deleted_at IS NOT NULL,identity_deleted_at,application_deleted_at FROM app.account_deletions WHERE account_id=%s", (account,)).fetchone() == (True, None, None)
            for _ in range(2):
                assert run_account_deletion(URL, account, tmp_path, client=client) == {"state": "retention_pending"}
            assert len(calls) == 2
            with psycopg.connect(URL) as c:
                assert c.execute("SELECT 1 FROM app.jobs WHERE id=%s", (job,)).fetchone() is None
                assert c.execute("SELECT state,completed_at FROM app.account_deletions WHERE account_id=%s", (account,)).fetchone() == ("requested", None)
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.account_deletions WHERE account_id=%s", (account,))
