"""Carry current deletion tombstones into an isolated restored database before startup."""
import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from admaker.account_deletion import request_account_deletion


def export_deletions(database_url):
    with psycopg.connect(database_url) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        observed = connection.execute("SELECT clock_timestamp()").fetchone()[0]
        rows = connection.execute("SELECT account_id FROM app.account_deletions ORDER BY account_id").fetchall()
    return {"version": 1, "exportedAt": observed.isoformat(), "accounts": [str(row[0]) for row in rows]}


def apply_deletions(database_url, snapshot):
    if (not isinstance(snapshot, dict) or set(snapshot) != {"version", "exportedAt", "accounts"}
            or type(snapshot["version"]) is not int or snapshot["version"] != 1
            or not isinstance(snapshot["exportedAt"], str) or not isinstance(snapshot["accounts"], list)
            or len(snapshot["accounts"]) > 100000):
        raise ValueError("Invalid deletion snapshot")
    observed = datetime.fromisoformat(snapshot["exportedAt"])
    if observed.tzinfo is None or observed > datetime.now(timezone.utc):
        raise ValueError("Invalid deletion snapshot time")
    accounts = sorted({uuid.UUID(value) for value in snapshot["accounts"]})
    # Validate the whole file before any mutation. Restore targets must remain offline.
    with psycopg.connect(database_url) as connection:
        for account in accounts:
            if connection.execute("SELECT 1 FROM app.accounts WHERE id=%s", (account,)).fetchone():
                request_account_deletion(connection, account)
            else:
                connection.execute("INSERT INTO app.account_deletions(account_id) VALUES (%s) ON CONFLICT DO NOTHING", (account,))
            connection.execute("""UPDATE app.account_deletions SET state='requested',completed_at=NULL,
                identity_deleted_at=NULL,media_deleted_at=NULL,application_deleted_at=NULL,
                billing_minimized_at=NULL,next_attempt_at=NULL,last_outcome='restored_deletion_requires_cleanup'
                WHERE account_id=%s""", (account,))
    return {"blockedAccounts": len(accounts), "cleanupRequired": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("file", type=Path)
    apply = sub.add_parser("apply")
    apply.add_argument("file", type=Path)
    apply.add_argument("--isolated-target", action="store_true", required=True,
                       help="Confirm DATABASE_URL points to an offline restored target, never the source")
    args = parser.parse_args()
    try:
        if args.command == "export":
            snapshot = export_deletions(os.environ["DATABASE_URL"])
            # Refuse accidental replacement of a prior recovery artifact.
            with args.file.open("x", encoding="utf-8") as stream:
                json.dump(snapshot, stream)
        else:
            if args.file.stat().st_size > 10 * 1024 * 1024:
                raise ValueError("Deletion snapshot exceeds the limit")
            snapshot = json.loads(args.file.read_text(encoding="utf-8"))
            print(json.dumps(apply_deletions(os.environ["DATABASE_URL"], snapshot)))
    except Exception:
        print(json.dumps({"event": "deletion_restore_failed", "message": "Operation unconfirmed; verify the source or isolated target and snapshot before retrying."}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
