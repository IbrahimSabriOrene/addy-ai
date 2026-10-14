"""Trusted support CLI. No customer token can claim or resolve reports."""
import argparse
import json
import os
from pathlib import Path
import uuid

import psycopg
from psycopg.rows import dict_row


def update_report(database_url: str, report_id: uuid.UUID, assignee: str, resolution: str | None = None) -> bool:
    assignee = assignee.strip()
    if not 1 <= len(assignee) <= 100:
        raise ValueError("Use an operator identifier of 1–100 characters")
    if resolution is not None and not 1 <= len(resolution.strip()) <= 1000:
        raise ValueError("A user-visible resolution of 1–1000 characters is required")
    with psycopg.connect(database_url) as connection:
        if resolution is None:
            row = connection.execute("UPDATE app.result_reports SET status='reviewing',assignee=%s,updated_at=now() WHERE id=%s AND status='open' RETURNING id", (assignee, report_id)).fetchone()
        else:
            row = connection.execute("UPDATE app.result_reports SET status='resolved',resolution=%s,updated_at=now() WHERE id=%s AND status='reviewing' AND assignee=%s RETURNING id", (resolution.strip(), report_id, assignee)).fetchone()
    return bool(row)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    queue = sub.add_parser("list")
    queue.add_argument("--limit", type=int, default=20, choices=range(1, 101), metavar="1..100")
    show = sub.add_parser("show")
    show.add_argument("id", type=uuid.UUID)
    for command in ("claim", "resolve"):
        action = sub.add_parser(command)
        action.add_argument("id", type=uuid.UUID)
        action.add_argument("--assignee", required=True)
        if command == "resolve":
            action.add_argument("--resolution-file", required=True, type=Path)
    args = parser.parse_args()
    database_url = os.environ["DATABASE_URL"]
    if args.command == "list":
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            rows = connection.execute("SELECT id,job_id,run_id,reason,details,status,assignee,created_at FROM app.result_reports WHERE status <> 'resolved' ORDER BY created_at,id LIMIT %s", (args.limit,)).fetchall()
        print(json.dumps(rows, default=str, ensure_ascii=False, indent=2))
    elif args.command == "show":
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            row = connection.execute("""SELECT r.id,r.owner_id,r.job_id,r.run_id,j.sequence AS attempt_sequence,
                r.reason,r.details,r.status,r.assignee,r.resolution,r.created_at,
                r.result_snapshot->'exports' AS reported_exports
                FROM app.result_reports r LEFT JOIN app.job_runs j ON j.id=r.run_id
                WHERE r.id=%s""", (args.id,)).fetchone()
        if row is None:
            parser.exit(1, "Report not found.\n")
        print(json.dumps(row, default=str, ensure_ascii=False, indent=2))
    else:
        resolution = args.resolution_file.read_text(encoding="utf-8") if args.command == "resolve" else None
        if not update_report(database_url, args.id, args.assignee, resolution):
            parser.exit(1, "Report not found or state/assignee changed; reload the queue.\n")
        print("Report updated")


if __name__ == "__main__":
    main()
