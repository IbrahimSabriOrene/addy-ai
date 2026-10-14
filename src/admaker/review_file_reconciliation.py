"""Trusted terminal-upload reconciliation; absence or age alone is not proof."""
import argparse
import json
import os
import uuid
from contextlib import nullcontext

import psycopg
from psycopg.rows import dict_row

from admaker.review_files import get_review_file, review_file_client


def resolve_absent_review_file(database_url, account_id, file_name, resolution_id, operator, evidence, *, verified_terminal, store=None):
    account_id, resolution_id = uuid.UUID(str(account_id)), uuid.UUID(str(resolution_id))
    operator, evidence = operator.strip(), evidence.strip()
    if verified_terminal is not True or not 1 <= len(operator) <= 100 or not 1 <= len(evidence) <= 500:
        raise ValueError("Verified terminal-upload evidence and a bounded operator are required")
    with psycopg.connect(database_url) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"account-media:{account_id}",))
        prior = connection.execute("SELECT account_id,file_name,operator,evidence FROM app.review_file_resolutions WHERE id=%s", (resolution_id,)).fetchone()
        if prior:
            if prior != (account_id, file_name, operator, evidence):
                raise ValueError("Resolution identifier has a different outcome")
            return True
        row = connection.execute("SELECT credential_hash,state FROM app.review_files WHERE account_id=%s AND file_name=%s FOR UPDATE", (account_id, file_name)).fetchone()
        if row is None:
            return False
        if row[1] == "verified_absent":
            raise ValueError("Use the original resolution identifier")
        with nullcontext(store) if store is not None else review_file_client() as client:
            if client.credential_hash != row[0]:
                raise ValueError("Review credentials differ from the recorded destination")
            if get_review_file(client, file_name) is not None:
                raise ValueError("The provider file still exists")
        connection.execute("INSERT INTO app.review_file_resolutions(id,account_id,file_name,operator,evidence) VALUES (%s,%s,%s,%s,%s)",
            (resolution_id, account_id, file_name, operator, evidence))
        connection.execute("UPDATE app.review_files SET state='verified_absent' WHERE account_id=%s AND file_name=%s", (account_id, file_name))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    resolve = commands.add_parser("resolve")
    resolve.add_argument("account_id", type=uuid.UUID)
    resolve.add_argument("file_name")
    resolve.add_argument("--resolution-id", type=uuid.UUID, required=True)
    resolve.add_argument("--operator", required=True)
    resolve.add_argument("--evidence", required=True, help="Restricted terminal-upload evidence reference, not customer content")
    resolve.add_argument("--verified-terminal", action="store_true", required=True)
    args = parser.parse_args()
    try:
        url = os.environ["DATABASE_URL"]
        if args.command == "list":
            with psycopg.connect(url, row_factory=dict_row) as connection:
                rows = connection.execute("SELECT account_id,file_name,state,created_at FROM app.review_files WHERE state<>'verified_absent' ORDER BY created_at LIMIT 100").fetchall()
            print(json.dumps(rows, default=str))
        elif resolve_absent_review_file(url, args.account_id, args.file_name, args.resolution_id, args.operator, args.evidence, verified_terminal=args.verified_terminal):
            print("Terminal absence recorded; no upload, review or credit change performed.")
        else:
            parser.exit(1, "No review file found.\n")
    except Exception:
        parser.exit(1, "Review file reconciliation is unconfirmed; check restricted operational records.\n")


if __name__ == "__main__":
    main()
