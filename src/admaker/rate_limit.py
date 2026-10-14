"""One shared, bounded request counter per verified account."""
import math
import os

import psycopg
from fastapi import HTTPException


def enforce_account_rate_limit(account_id):
    try:
        limit = int(os.environ.get("API_REQUESTS_PER_MINUTE", "240"))
        if not 1 <= limit <= 10000:
            raise ValueError
    except ValueError:
        raise HTTPException(503, "API request limit is not configured correctly") from None
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        count, remaining = c.execute("""
            INSERT INTO app.api_rate_limits AS r VALUES (%s, clock_timestamp(), 1)
            ON CONFLICT (account_id) DO UPDATE SET
                requests = CASE WHEN r.window_started_at <= clock_timestamp()-interval '1 minute'
                    THEN 1 ELSE least(r.requests+1, %s+1) END,
                window_started_at = CASE WHEN r.window_started_at <= clock_timestamp()-interval '1 minute'
                    THEN clock_timestamp() ELSE r.window_started_at END
            RETURNING requests, extract(epoch FROM window_started_at+interval '1 minute'-clock_timestamp())
        """, (account_id, limit)).fetchone()
    # Commit the counter before rejecting; rollback would erase rejected attempts.
    if count > limit:
        raise HTTPException(429, "Too many requests", headers={"Retry-After": str(max(1, math.ceil(remaining)))})
