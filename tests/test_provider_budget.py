from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import uuid

import psycopg
import pytest

from admaker.db import migrate
from admaker.provider_budget import reserve_provider_budget


def test_budget_serializes_admission_and_keeps_uncertain_commitments(monkeypatch):
    url = "postgresql://postgres:postgres@localhost:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", url)
    migrate()
    ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    with psycopg.connect(url) as connection:
        baseline = connection.execute("SELECT COALESCE(sum(amount_microusd),0) FROM app.provider_budget_holds WHERE created_at >= date_trunc('day',clock_timestamp() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'").fetchone()[0]
    monkeypatch.setenv("VEO_DAILY_BUDGET_MICROUSD", str(baseline + 10))
    barrier = Barrier(2)

    def reserve(identifier):
        barrier.wait(timeout=5)
        try:
            with psycopg.connect(url) as connection, connection.cursor() as cursor:
                reserve_provider_budget(cursor, identifier, 7)
            return identifier
        except OSError:
            return None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            winners = [value for value in pool.map(reserve, ids[:2]) if value]
        assert len(winners) == 1
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            reserve_provider_budget(cursor, winners[0], 7)
        with pytest.raises(OSError, match="changed"):
            with psycopg.connect(url) as connection, connection.cursor() as cursor:
                reserve_provider_budget(cursor, winners[0], 6)
        with pytest.raises(RuntimeError):
            with psycopg.connect(url) as connection, connection.cursor() as cursor:
                reserve_provider_budget(cursor, ids[2], 3)
                raise RuntimeError("transaction failed before submission")
        with psycopg.connect(url) as connection:
            assert connection.execute("SELECT count(*) FROM app.provider_budget_holds WHERE attempt_id=ANY(%s)", (ids,)).fetchone()[0] == 1
        monkeypatch.delenv("VEO_DAILY_BUDGET_MICROUSD")
        monkeypatch.setenv("ENABLE_REAL_VEO", "true")
        with pytest.raises(OSError, match="budget is required"):
            with psycopg.connect(url) as connection, connection.cursor() as cursor:
                reserve_provider_budget(cursor, ids[2], 3)
    finally:
        with psycopg.connect(url) as connection:
            connection.execute("DELETE FROM app.provider_budget_holds WHERE attempt_id=ANY(%s)", (ids,))
