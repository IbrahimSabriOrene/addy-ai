import json

import httpx
import psycopg
import pytest

from admaker.account_deletion import request_account_deletion
from admaker.delete_identity import delete_requested_identity
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("outcome", ["success", "lost", "unauthorized", "redirect", "unknown404"])
def test_identity_phase_is_guarded_replayable_and_never_claims_full_cleanup(queued_job, monkeypatch, outcome):
    account, job, reservation, queue = queued_job
    monkeypatch.setenv("SUPABASE_URL", "https://identity.example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-server-only-key")
    calls = []

    def respond(request):
        calls.append(request)
        assert request.method == "DELETE"
        assert str(request.url) == f"https://identity.example.test/auth/v1/admin/users/{account}"
        assert request.headers["authorization"] == "Bearer test-server-only-key"
        assert request.headers["apikey"] == "test-server-only-key"
        assert json.loads(request.content) == {"should_soft_delete": False}
        if len(calls) > 1:
            return httpx.Response(404, json={"code": "user_not_found"})
        if outcome == "lost":
            raise httpx.ReadTimeout("Unknown server outcome", request=request)
        return httpx.Response({"success": 200, "unauthorized": 401, "redirect": 307, "unknown404": 404}[outcome],
                              headers={"Location": "https://untrusted.example.test"}, json={"message": "untrusted provider text"})

    try:
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(ValueError):
                delete_requested_identity(URL, account, client=client)
            assert not calls
            with psycopg.connect(URL) as c:
                request_account_deletion(c, account)
            if outcome != "success":
                with pytest.raises(RuntimeError) as error:
                    delete_requested_identity(URL, account, client=client)
                assert "test-server-only-key" not in str(error.value) and "untrusted provider text" not in str(error.value)
                with psycopg.connect(URL) as c:
                    assert c.execute("SELECT identity_deleted_at FROM app.account_deletions WHERE account_id=%s", (account,)).fetchone() == (None,)
            assert delete_requested_identity(URL, account, client=client)
            count = len(calls)
            assert delete_requested_identity(URL, account, client=client) is False
            assert len(calls) == count
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT state,identity_deleted_at IS NOT NULL,completed_at FROM app.account_deletions WHERE account_id=%s", (account,)).fetchone() == ("requested", True, None)
            assert c.execute("SELECT count(*) FROM app.assets WHERE owner_id=%s", (account,)).fetchone() == (1,)
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.account_deletions WHERE account_id=%s", (account,))
