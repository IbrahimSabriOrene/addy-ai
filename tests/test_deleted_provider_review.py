import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from admaker.db import migrate
from admaker.deleted_provider_review import reconcile_deleted_provider
from admaker.provider_budget import provider_operations_inflight
from test_worker_leases import URL


def test_verified_deleted_operation_releases_capacity_once_without_credit_changes():
    migrate(URL)
    attempt, owner, reservation = (uuid.uuid4() for _ in range(3))
    with psycopg.connect(URL) as c:
        baseline = provider_operations_inflight(c)
        c.execute("""INSERT INTO app.deleted_attempt_finances
            (attempt_id,account_id,reservation_id,credits,reservation_state,provider_state,estimated_cost_microusd)
            VALUES (%s,%s,%s,3,'released','submission_unknown',1000)""", (attempt, owner, reservation))
        c.execute("INSERT INTO app.provider_budget_holds(attempt_id,amount_microusd) VALUES (%s,1000)", (attempt,))
    args = (URL, attempt, "operator-fixture", "failed", "review-ticket-fixture", 250)
    try:
        with psycopg.connect(URL) as c:
            assert provider_operations_inflight(c) == baseline + 1
        with pytest.raises(ValueError):
            reconcile_deleted_provider(URL, attempt, "operator", "unknown", "ticket", 0)
        with pytest.raises(ValueError):
            reconcile_deleted_provider(URL, attempt, "operator", "failed", "ticket", -1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert all(pool.map(lambda _: reconcile_deleted_provider(*args), range(2)))
        with pytest.raises(ValueError, match="different resolution"):
            reconcile_deleted_provider(*args[:-1], 251)
        with psycopg.connect(URL) as c:
            assert provider_operations_inflight(c) == baseline
            row = c.execute("""SELECT provider_state,actual_cost_microusd,reconciled_by,reconciliation_evidence,
                reservation_state,credits,reconciled_at IS NOT NULL FROM app.deleted_attempt_finances WHERE attempt_id=%s""", (attempt,)).fetchone()
            assert row == ('failed', 250, 'operator-fixture', 'review-ticket-fixture', 'released', 3, True)
            assert c.execute("SELECT amount_microusd FROM app.provider_budget_holds WHERE attempt_id=%s", (attempt,)).fetchone() == (1000,)
            assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (owner,)).fetchone() == (0,)
        assert reconcile_deleted_provider(URL, uuid.uuid4(), "operator", "failed", "ticket", 0) is False
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.provider_budget_holds WHERE attempt_id=%s", (attempt,))
            c.execute("DELETE FROM app.deleted_attempt_finances WHERE attempt_id=%s", (attempt,))
