"""Bound outstanding paid work while the caller holds the account row lock."""
import os

from fastapi import HTTPException


def require_generation_capacity(connection, account_id, existing_job_id=None):
    value = os.environ.get("MAX_OUTSTANDING_JOBS_PER_ACCOUNT", "10")
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 100:
        raise HTTPException(503, "Generation capacity configuration is unavailable")
    count = connection.execute(
        "SELECT count(DISTINCT job_id) FROM app.credit_reservations "
        "WHERE account_id=%s AND state='held' AND (%s::uuid IS NULL OR job_id<>%s::uuid)",
        (account_id, existing_job_id, existing_job_id),
    ).fetchone()[0]
    if count >= int(value):
        raise HTTPException(429, "Too many unfinished generations. Finish or close an existing generation before starting another.")
