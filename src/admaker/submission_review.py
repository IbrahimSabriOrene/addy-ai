"""Trusted operator CLI for uncertain submissions. Never resubmits or consumes credits."""

import argparse
import json
import os
import uuid
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def resolve_submission(database_url: str, attempt_id: uuid.UUID, operator: str,
                       decision: str, reason: str, actual_cost_microusd: int | None = None) -> bool:
    operator, reason = operator.strip(), reason.strip()
    if not 1 <= len(operator) <= 100 or not 1 <= len(reason) <= 2000:
        raise ValueError("An operator identifier and a bounded review reason are required")
    if decision not in {"verified_no_output", "goodwill_release"}:
        raise ValueError("Choose verified_no_output or goodwill_release")
    if actual_cost_microusd is not None and (type(actual_cost_microusd) is not int or not 0 <= actual_cost_microusd <= 1_000_000_000):
        raise ValueError("Actual cost must be bounded integer micro-USD, or omitted when unknown")
    with psycopg.connect(database_url) as connection:
        identity = connection.execute("SELECT r.job_id,r.id,a.reservation_id,j.owner_id FROM app.job_attempts a JOIN app.job_runs r ON r.id=a.run_id JOIN app.jobs j ON j.id=r.job_id WHERE a.id=%s", (attempt_id,)).fetchone()
        if not identity:
            return False
        job, run, reservation, account = identity
        connection.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (account,))
        job_state = connection.execute("SELECT state,active_run_id FROM app.jobs WHERE id=%s FOR UPDATE", (job,)).fetchone()
        run_state = connection.execute("SELECT state FROM app.job_runs WHERE id=%s FOR UPDATE", (run,)).fetchone()[0]
        attempt_state, provider_state, saved_cost, provider_error = connection.execute("SELECT state,provider_state,actual_cost_microusd,provider_error FROM app.job_attempts WHERE id=%s FOR UPDATE", (attempt_id,)).fetchone()
        if saved_cost is not None:
            if actual_cost_microusd is not None and actual_cost_microusd != saved_cost:
                raise ValueError("Actual cost conflicts with the recorded amount")
            actual_cost_microusd = saved_cost
        review = connection.execute("SELECT resolved_at,operator,decision,reason,actual_cost_microusd FROM app.submission_reviews WHERE attempt_id=%s FOR UPDATE", (attempt_id,)).fetchone()
        if not review:
            return False
        if review[0] is not None:
            if review[1:] != (operator, decision, reason, actual_cost_microusd):
                raise ValueError("This review already has a different resolution")
            return True
        reviewable = provider_state == "submission_unknown" or (provider_state in {"submitted", "ready"} and provider_error == "wait_deadline_exceeded")
        if job_state != ("failed", run) or run_state != "review_required" or attempt_state != "running" or not reviewable:
            raise ValueError("Attempt state changed; reload before resolving")
        released = connection.execute("UPDATE app.credit_reservations SET state='released' WHERE id=%s AND account_id=%s AND job_id=%s AND state='held' RETURNING id", (reservation, account, job)).fetchone()
        if not released:
            raise ValueError("Reservation is no longer held; no credit adjustment was made")
        connection.execute("UPDATE app.job_attempts SET state='failed',completed_at=clock_timestamp(),actual_cost_microusd=%s WHERE id=%s", (actual_cost_microusd, attempt_id))
        if decision == "verified_no_output":
            connection.execute("UPDATE app.job_attempts SET provider_state='failed' WHERE id=%s", (attempt_id,))
        connection.execute("UPDATE app.job_runs SET state='failed',lease_until=NULL,next_work_at=NULL WHERE id=%s", (run,))
        connection.execute("UPDATE app.jobs SET result=result || %s WHERE id=%s", (Jsonb({"failure": {"code": "generation_closed"}}), job))
        connection.execute("UPDATE app.submission_reviews SET resolved_at=clock_timestamp(),operator=%s,decision=%s,reason=%s,actual_cost_microusd=%s WHERE attempt_id=%s", (operator, decision, reason, actual_cost_microusd, attempt_id))
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pending = commands.add_parser("list")
    pending.add_argument("--limit", type=int, choices=range(1, 101), default=20)
    resolve = commands.add_parser("resolve")
    resolve.add_argument("attempt_id", type=uuid.UUID)
    resolve.add_argument("--operator", required=True)
    resolve.add_argument("--decision", required=True, choices=["verified_no_output", "goodwill_release"])
    resolve.add_argument("--reason-file", required=True, type=Path)
    resolve.add_argument("--actual-cost-microusd", type=int)
    args = parser.parse_args()
    url = os.environ["DATABASE_URL"]
    if args.command == "list":
        with psycopg.connect(url, row_factory=dict_row) as connection:
            rows = connection.execute("SELECT s.attempt_id,r.job_id,s.created_at,s.review_due_at,s.review_due_at<=clock_timestamp() AS overdue,a.estimated_cost_microusd,a.actual_cost_microusd FROM app.submission_reviews s JOIN app.job_attempts a ON a.id=s.attempt_id JOIN app.job_runs r ON r.id=a.run_id WHERE s.resolved_at IS NULL ORDER BY s.review_due_at,s.attempt_id LIMIT %s", (args.limit,)).fetchall()
        print(json.dumps(rows, default=str, indent=2))
    else:
        if not resolve_submission(url, args.attempt_id, args.operator, args.decision,
                                  args.reason_file.read_text(encoding="utf-8"), args.actual_cost_microusd):
            parser.exit(1, "No review found.\n")
        print("Review resolved; reserved credits released.")


if __name__ == "__main__":
    main()
