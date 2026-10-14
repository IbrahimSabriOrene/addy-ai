from datetime import datetime, timezone

import psycopg
import pytest

from admaker.restore_deletions import apply_deletions, export_deletions
from admaker.consent import require_ai_consent
from test_worker_leases import URL, queued_job


def test_restored_job_is_blocked_by_newer_deletion_snapshot(queued_job, monkeypatch):
    account, job, reservation, _ = queued_job
    monkeypatch.setenv("DATABASE_URL", URL)
    snapshot = {"version": 1, "exportedAt": datetime.now(timezone.utc).isoformat(), "accounts": [str(account)]}
    try:
        for _ in range(2):
            assert apply_deletions(URL, snapshot)["blockedAccounts"] == 1
        with pytest.raises(PermissionError):
            require_ai_consent(str(account))
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT state FROM app.jobs WHERE id=%s", (job,)).fetchone() == ("aborted",)
            assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("released",)
            assert c.execute("SELECT application_deleted_at,media_deleted_at FROM app.account_deletions WHERE account_id=%s", (account,)).fetchone() == (None, None)
        assert str(account) in export_deletions(URL)["accounts"]
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.account_deletions WHERE account_id=%s", (account,))
