"""Dedicated local-storage deletion worker; no generation queue consumption."""
import argparse
import logging
import os
from pathlib import Path
import time
import uuid

import psycopg

from admaker.deletion_runner import run_account_deletion


def process_deletion_attempt(database_url, account_id, root, *, client=None):
    account_id = uuid.UUID(str(account_id))
    # A session lock spans the phase transactions without holding their row locks.
    with psycopg.connect(database_url, autocommit=True) as c:
        if not c.execute("SELECT pg_try_advisory_lock(hashtextextended(%s,0))", (f"deletion-worker:{account_id}",)).fetchone()[0]:
            return "busy"
        claimed = c.execute("UPDATE app.account_deletions SET attempts=attempts+1,next_attempt_at=clock_timestamp()+interval '5 minutes',last_outcome='processing' WHERE account_id=%s AND state='requested' AND (application_deleted_at IS NULL OR billing_minimized_at IS NULL) AND (next_attempt_at IS NULL OR next_attempt_at<=clock_timestamp()) RETURNING account_id", (account_id,)).fetchone()
        if not claimed:
            return "not_due"
        try:
            result = run_account_deletion(database_url, account_id, root, client=client)["state"]
        except Exception:
            # Never persist/log raw provider, SQL or filesystem exception payloads.
            result = "unconfirmed"
        c.execute("UPDATE app.account_deletions SET last_outcome=%s WHERE account_id=%s", (result, account_id))
        return result


def process_pending_deletions(database_url, root):
    with psycopg.connect(database_url) as c:
        accounts = c.execute("SELECT account_id FROM app.account_deletions WHERE state='requested' AND (application_deleted_at IS NULL OR billing_minimized_at IS NULL) AND (next_attempt_at IS NULL OR next_attempt_at<=clock_timestamp()) ORDER BY next_attempt_at NULLS FIRST,requested_at LIMIT 20").fetchall()
    for (account,) in accounts:
        process_deletion_attempt(database_url, account, root)
    return len(accounts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if not root.is_dir():
        parser.error("A private local storage directory is required")
    database_url = os.environ["DATABASE_URL"]
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            process_pending_deletions(database_url, root)
        except psycopg.Error:
            logging.warning("Deletion database work is unconfirmed; retrying on the next pass")
        time.sleep(30)


if __name__ == "__main__":
    main()
