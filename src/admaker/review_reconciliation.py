"""Trusted CLI: close an uncertain review only with verified terminal-call evidence."""
import argparse
import json
import os
import uuid
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


def resolve_review_receipt(database_url, receipt_id, resolution_id, operator, evidence, *, verified_terminal):
    receipt_id, resolution_id = uuid.UUID(str(receipt_id)), uuid.UUID(str(resolution_id))
    if (verified_terminal is not True or not isinstance(operator, str) or not 1 <= len(operator.strip()) <= 100
            or not isinstance(evidence, str) or not 1 <= len(evidence.strip()) <= 500
            or len(operator) > 100 or len(evidence) > 500):
        raise ValueError("Verified terminal-call evidence and bounded operator details are required")
    with psycopg.connect(database_url) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(72419032)")
        previous = connection.execute("SELECT id,resolved_by,resolution_evidence FROM app.media_review_budget WHERE resolution_id=%s", (resolution_id,)).fetchone()
        if previous:
            if previous != (receipt_id, operator, evidence):
                raise ValueError("Resolution replay differs")
            return False
        row = connection.execute("SELECT state FROM app.media_review_budget WHERE id=%s FOR UPDATE", (receipt_id,)).fetchone()
        if not row or row[0] != "unconfirmed":
            raise ValueError("An unconfirmed review receipt is required")
        # No synthetic verdict: a new review still needs a separate worker resume and budget.
        connection.execute("UPDATE app.media_review_budget SET state='failed',completed_at=clock_timestamp(),resolution_id=%s,resolved_by=%s,resolution_evidence=%s WHERE id=%s",
                           (resolution_id, operator, evidence, receipt_id))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pending = commands.add_parser("list")
    pending.add_argument("--limit", type=int, choices=range(1, 101), default=20)
    resolve = commands.add_parser("resolve")
    resolve.add_argument("receipt", type=uuid.UUID)
    resolve.add_argument("--resolution-id", type=uuid.UUID, required=True)
    resolve.add_argument("--operator", required=True)
    resolve.add_argument("--evidence-file", type=Path, required=True)
    resolve.add_argument("--verified-terminal", action="store_true", required=True,
                         help="Confirm trusted evidence that the original remote call ended; age or missing response is insufficient")
    args = parser.parse_args()
    try:
        url = os.environ["DATABASE_URL"]
        if args.command == "list":
            with psycopg.connect(url, row_factory=dict_row) as connection:
                rows = connection.execute("SELECT id,run_id,amount_microusd,created_at FROM app.media_review_budget WHERE state='unconfirmed' ORDER BY created_at,id LIMIT %s", (args.limit,)).fetchall()
            print(json.dumps(rows, default=str))
        else:
            with args.evidence_file.open(encoding="utf-8") as stream:
                evidence = stream.read(501)
            applied = resolve_review_receipt(url, args.receipt, args.resolution_id, args.operator, evidence,
                                             verified_terminal=args.verified_terminal)
            print("Resolution recorded; no review call or credit change made." if applied else "Resolution already recorded.")
    except ValueError as error:
        parser.exit(1, str(error) + "\n")
    except (OSError, psycopg.Error, KeyError):
        parser.exit(1, "Review reconciliation is unavailable.\n")


if __name__ == "__main__":
    main()
