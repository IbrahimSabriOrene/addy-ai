"""Read a bounded job timeline from a trusted operator database connection."""
import argparse
import json
import os
import uuid

import psycopg
from psycopg.rows import dict_row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", type=uuid.UUID, required=True)
    parser.add_argument("--job", type=uuid.UUID, required=True)
    parser.add_argument("--limit", type=int, default=50, choices=range(1, 501), metavar="1..500")
    args = parser.parse_args()
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        job = connection.execute("SELECT state,active_run_id FROM app.jobs WHERE id=%s AND owner_id=%s", (args.job, args.account)).fetchone()
        if not job:
            parser.exit(1, "Job not found for the specified account.\n")
        rows = connection.execute("""SELECT e.run_id,e.event_key,e.occurred_at,e.detail
            FROM app.job_events e JOIN app.jobs j ON j.id=e.job_id
            WHERE j.id=%s AND j.owner_id=%s
            ORDER BY e.occurred_at DESC,e.event_key DESC LIMIT %s""",
            (args.job, args.account, args.limit + 1)).fetchall()
    print(json.dumps({"job": job, "events": list(reversed(rows[:args.limit])),
        "olderEventsOmitted": len(rows) > args.limit}, default=str, indent=2))


if __name__ == "__main__":
    main()
