from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import psycopg

from admaker.account_deletion import request_account_deletion
from admaker.deletion_worker import process_deletion_attempt
from test_worker_leases import URL, queued_job


def test_deletion_worker_serializes_accounts_and_persists_retry_delay(queued_job, tmp_path, monkeypatch):
    account, job, reservation, queue = queued_job
    monkeypatch.setenv("SUPABASE_URL", "https://identity.example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fixture-key")
    entered, release = Event(), Event()
    calls = []

    def respond(request):
        calls.append(request)
        entered.set()
        assert release.wait(5)
        if len(calls) == 1:
            raise httpx.ReadTimeout("private provider details", request=request)
        return httpx.Response(204)

    try:
        with psycopg.connect(URL) as c:
            request_account_deletion(c, account)
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(process_deletion_attempt, URL, account, tmp_path, client=client)
                try:
                    assert entered.wait(5)
                    assert process_deletion_attempt(URL, account, tmp_path, client=client) == "busy"
                finally:
                    release.set()
                assert future.result(timeout=5) == "unconfirmed"
            assert process_deletion_attempt(URL, account, tmp_path, client=client) == "not_due"
            assert len(calls) == 1
            with psycopg.connect(URL) as c:
                assert c.execute("SELECT attempts,last_outcome,next_attempt_at>now(),application_deleted_at FROM app.account_deletions WHERE account_id=%s", (account,)).fetchone() == (1, "unconfirmed", True, None)
                c.execute("UPDATE app.account_deletions SET next_attempt_at=now()-interval '1 second' WHERE account_id=%s", (account,))
            assert process_deletion_attempt(URL, account, tmp_path, client=client) == "retention_pending"
            assert process_deletion_attempt(URL, account, tmp_path, client=client) == "not_due"
            assert len(calls) == 2
            with psycopg.connect(URL) as c:
                assert c.execute("SELECT attempts,last_outcome,state,completed_at FROM app.account_deletions WHERE account_id=%s", (account,)).fetchone() == (2, "retention_pending", "requested", None)
    finally:
        release.set()
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.account_deletions WHERE account_id=%s", (account,))
