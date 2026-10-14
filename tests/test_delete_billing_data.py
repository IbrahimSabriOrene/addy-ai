import uuid

import psycopg
from psycopg.types.json import Jsonb
import pytest

from admaker.account_deletion import request_account_deletion
from admaker.delete_billing_data import minimize_deleted_account_billing
from admaker.deletion_worker import process_deletion_attempt
from test_worker_leases import URL, queued_job


def test_legacy_billing_minimization_is_scoped_and_old_cleanup_resumes(queued_job, tmp_path):
    account, job, reservation, queue = queued_job
    ids = [str(uuid.uuid4()) for _ in range(3)]
    try:
        with psycopg.connect(URL) as c:
            for event_id, identity in zip(ids, ({"aliases": [str(account)]}, {"transferred_to": [str(account)]}, {"app_user_id": str(uuid.uuid4())})):
                c.execute("INSERT INTO app.webhook_events(provider,event_id,payload_hash,payload) VALUES ('revenuecat',%s,'unchanged-proof',%s)", (event_id, Jsonb({"event": {"id": event_id, "type": "TRANSFER", **identity, "subscriber_attributes": {"email": "private@example.test"}}})))
        with pytest.raises(ValueError):
            minimize_deleted_account_billing(URL, account)
        with psycopg.connect(URL) as c:
            request_account_deletion(c, account)
            # Simulate an account whose older runner already finished application cleanup.
            c.execute("UPDATE app.account_deletions SET identity_deleted_at=now(),media_deleted_at=now(),application_deleted_at=now() WHERE account_id=%s", (account,))
        assert process_deletion_attempt(URL, account, tmp_path) == "retention_pending"
        assert process_deletion_attempt(URL, account, tmp_path) == "not_due"
        with psycopg.connect(URL) as c:
            for event_id in ids:
                payload, digest = c.execute("SELECT payload,payload_hash FROM app.webhook_events WHERE provider='revenuecat' AND event_id=%s", (event_id,)).fetchone()
                assert digest == "unchanged-proof"
                assert ("subscriber_attributes" in payload["event"]) == (event_id == ids[2])
            assert c.execute("SELECT billing_minimized_at IS NOT NULL,state FROM app.account_deletions WHERE account_id=%s", (account,)).fetchone() == (True, "requested")
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.webhook_events WHERE provider='revenuecat' AND event_id=ANY(%s)", (ids,))
            c.execute("DELETE FROM app.account_deletions WHERE account_id=%s", (account,))
