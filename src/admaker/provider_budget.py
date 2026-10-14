"""Conservative UTC daily estimate commitments, separate from customer credits."""
import os


class ProviderCapacityBusy(Exception):
    """No new provider call may begin until an open operation is resolved."""


def provider_operations_inflight(cursor, media_kind=None):
    return cursor.execute("""SELECT count(*) FROM app.provider_budget_holds h WHERE
        (%s::text IS NULL OR h.media_kind=%s) AND (EXISTS (SELECT 1 FROM app.job_attempts a WHERE a.id=h.attempt_id
            AND a.provider_state IN ('submitting','submitted','submission_unknown'))
        OR EXISTS (SELECT 1 FROM app.deleted_attempt_finances f WHERE f.attempt_id=h.attempt_id
            AND f.provider_state IN ('submitting','submitted','submission_unknown')))""", (media_kind, media_kind)).fetchone()[0]


def reserve_provider_budget(cursor, attempt_id, estimate, *, media_kind="video"):
    if media_kind not in {"video", "photo"}:
        raise ValueError("Unsupported provider media kind")
    prefix = "VEO" if media_kind == "video" else "PHOTO"
    enabled = os.environ.get("ENABLE_REAL_" + prefix) == "true"
    configured = os.environ.get(prefix + "_DAILY_BUDGET_MICROUSD")
    capacity = os.environ.get(prefix + "_MAX_CONCURRENT_OPERATIONS", "3" if enabled or media_kind == "photo" else None)
    if media_kind == "video" and configured is None and capacity is None and not enabled:
        return
    if configured is None or not configured.isdecimal() or not 0 < int(configured) <= 1_000_000_000_000:
        raise OSError(f"A positive bounded daily {media_kind} budget is required")
    if type(estimate) is not int or estimate <= 0:
        raise OSError("A positive provider cost estimate is required")
    # One database-wide lock serializes budget admission across workers/accounts.
    cursor.execute("SELECT pg_advisory_xact_lock(72419031)")
    previous = cursor.execute("SELECT amount_microusd,media_kind FROM app.provider_budget_holds WHERE attempt_id=%s", (attempt_id,)).fetchone()
    if previous:
        if previous != (estimate, media_kind):
            raise OSError("Provider budget estimate changed")
        return
    if capacity is not None:
        if not capacity.isdecimal() or not 0 < int(capacity) <= 10000:
            raise OSError("A positive bounded provider concurrency limit is required")
        if provider_operations_inflight(cursor, media_kind) >= int(capacity):
            raise ProviderCapacityBusy()
    committed = cursor.execute("SELECT COALESCE(sum(amount_microusd),0) FROM app.provider_budget_holds WHERE media_kind=%s AND created_at >= date_trunc('day',clock_timestamp() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'", (media_kind,)).fetchone()[0]
    if committed + estimate > int(configured):
        raise OSError(f"Daily {media_kind} estimate budget exhausted")
    cursor.execute("INSERT INTO app.provider_budget_holds(attempt_id,amount_microusd,media_kind) VALUES (%s,%s,%s)", (attempt_id, estimate, media_kind))
