"""Commit review estimates before transfer; uncertain calls never refund the cap."""
import os
import re
import uuid

import psycopg
from psycopg.types.json import Jsonb

from admaker.media_drain import lock_media_writer


def review_budget_limits():
    values = []
    for key, maximum in (("MEDIA_REVIEW_ESTIMATE_MICROUSD", 1_000_000_000),
                         ("MEDIA_REVIEW_DAILY_BUDGET_MICROUSD", 1_000_000_000_000),
                         ("MEDIA_REVIEW_MAX_CALLS_PER_RUN", 20),
                         ("MEDIA_REVIEW_MAX_CONCURRENT_CALLS", 10000)):
        value = os.environ.get(key, "")
        if not value.isdecimal() or not 0 < int(value) <= maximum:
            raise ValueError("Positive bounded media review budgets are required")
        values.append(int(value))
    return tuple(values)


def reserve_review_budget(database_url, run_id, request_hash=None):
    if request_hash is not None and (not isinstance(request_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", request_hash)):
        raise ValueError("Invalid review request hash")
    estimate, daily, attempts, capacity = review_budget_limits()
    with psycopg.connect(database_url) as connection:
        row = connection.execute("SELECT j.owner_id FROM app.job_runs r JOIN app.jobs j ON j.id=r.job_id WHERE r.id=%s AND r.state='running'", (run_id,)).fetchone()
        if not row:
            raise ValueError("An active review run is required")
        lock_media_writer(connection, row[0])
        # One database-wide transaction lock makes both caps atomic across workers.
        connection.execute("SELECT pg_advisory_xact_lock(72419032)")
        if request_hash is not None:
            previous = connection.execute("SELECT state,verdict FROM app.media_review_budget WHERE run_id=%s AND request_hash=%s AND state IN ('unconfirmed','finished')", (run_id, request_hash)).fetchone()
            if previous:
                if previous[0] == "finished":
                    return previous[1]
                raise ValueError("Previous media review is unconfirmed")
        inflight = connection.execute("SELECT count(*) FROM app.media_review_budget WHERE state='unconfirmed'").fetchone()[0]
        used = connection.execute("SELECT COALESCE(sum(amount_microusd),0) FROM app.media_review_budget WHERE created_at >= date_trunc('day',clock_timestamp() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'").fetchone()[0]
        count = connection.execute("SELECT count(*) FROM app.media_review_budget WHERE run_id=%s", (run_id,)).fetchone()[0]
        if used + estimate > daily or count >= attempts or inflight >= capacity:
            raise ValueError("Media review budget exhausted")
        receipt = uuid.uuid4()
        connection.execute("INSERT INTO app.media_review_budget(id,run_id,amount_microusd,request_hash) VALUES (%s,%s,%s,%s)", (receipt, run_id, estimate, request_hash))
    return receipt


def finish_review_receipt(database_url, receipt, verdict):
    if isinstance(verdict, dict) and set(verdict) == {"creativePlan"}:
        from admaker.creative_planning import ProductPlan
        verdict = {"creativePlan": ProductPlan.model_validate(verdict["creativePlan"]).model_dump()}
    elif verdict is not None and (not isinstance(verdict, dict) or set(verdict) != {"policyAllowed", "qualityPassed", "offerFree"}
                                or any(type(value) is not bool for value in verdict.values())):
        raise ValueError("Invalid review verdict")
    state = "finished" if verdict is not None else "failed"
    with psycopg.connect(database_url) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(72419032)")
        row = connection.execute("SELECT state,verdict FROM app.media_review_budget WHERE id=%s FOR UPDATE", (receipt,)).fetchone()
        if not row or (row[0] != "unconfirmed" and row != (state, verdict)):
            raise ValueError("Review receipt conflicts")
        if row[0] == "unconfirmed":
            connection.execute("UPDATE app.media_review_budget SET state=%s,verdict=%s,completed_at=clock_timestamp() WHERE id=%s", (state, Jsonb(verdict) if verdict is not None else None, receipt))
