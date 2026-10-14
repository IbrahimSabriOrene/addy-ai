"""Trusted terminal reconciliation after account cleanup; no provider calls or credit changes."""
import argparse
import json
import os
import uuid

import psycopg
from psycopg.rows import dict_row


def reconcile_deleted_provider(database_url, attempt_id, operator, outcome, evidence, actual_cost_microusd):
    operator, evidence = operator.strip(), evidence.strip()
    if not 1 <= len(operator) <= 100 or not 1 <= len(evidence) <= 500:
        raise ValueError("A bounded operator and evidence reference are required")
    if outcome not in {"ready", "failed"}:
        raise ValueError("Only a verified terminal provider outcome may release capacity")
    if type(actual_cost_microusd) is not int or not 0 <= actual_cost_microusd <= 1_000_000_000:
        raise ValueError("Confirmed actual cost must be bounded integer micro-USD")
    with psycopg.connect(database_url) as c:
        row = c.execute("""SELECT provider_state,actual_cost_microusd,reconciled_at,reconciled_by,reconciliation_evidence
            FROM app.deleted_attempt_finances WHERE attempt_id=%s FOR UPDATE""", (attempt_id,)).fetchone()
        if row is None:
            return False
        state, cost, reconciled, saved_operator, saved_evidence = row
        if reconciled is not None:
            if (state, cost, saved_operator, saved_evidence) != (outcome, actual_cost_microusd, operator, evidence):
                raise ValueError("A different resolution is already recorded")
            return True
        if cost is not None and cost != actual_cost_microusd:
            raise ValueError("Actual cost conflicts with the recorded amount")
        if state in {"ready", "failed"} and state != outcome:
            raise ValueError("Terminal outcome conflicts with the recorded state")
        if state not in {"submitting", "submitted", "submission_unknown", "ready", "failed"}:
            raise ValueError("No provider operation is recorded for this attempt")
        c.execute("""UPDATE app.deleted_attempt_finances SET provider_state=%s,actual_cost_microusd=%s,
            reconciled_at=clock_timestamp(),reconciled_by=%s,reconciliation_evidence=%s WHERE attempt_id=%s""",
            (outcome, actual_cost_microusd, operator, evidence, attempt_id))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pending = commands.add_parser("list")
    pending.add_argument("--limit", type=int, choices=range(1, 101), default=20)
    resolve = commands.add_parser("resolve")
    resolve.add_argument("attempt_id", type=uuid.UUID)
    resolve.add_argument("--operator", required=True)
    resolve.add_argument("--outcome", required=True, choices=["ready", "failed"])
    resolve.add_argument("--evidence", required=True, help="Internal evidence reference; no photos, prompts or credentials")
    resolve.add_argument("--actual-cost-microusd", required=True, type=int)
    args = parser.parse_args()
    try:
        url = os.environ["DATABASE_URL"]
        if args.command == "list":
            with psycopg.connect(url, row_factory=dict_row) as c:
                rows = c.execute("""SELECT attempt_id,provider_state,operation_name,estimated_cost_microusd,
                    actual_cost_microusd,retained_at FROM app.deleted_attempt_finances
                    WHERE reconciled_at IS NULL AND provider_state IS NOT NULL
                    ORDER BY retained_at,attempt_id LIMIT %s""", (args.limit,)).fetchall()
            print(json.dumps(rows, default=str))
        elif reconcile_deleted_provider(url, args.attempt_id, args.operator, args.outcome, args.evidence, args.actual_cost_microusd):
            print("Provider outcome recorded; customer credits unchanged.")
        else:
            parser.exit(1, "No retained attempt found.\n")
    except ValueError as error:
        parser.exit(1, str(error) + "\n")
    except (psycopg.Error, KeyError):
        parser.exit(1, "Reconciliation unavailable.\n")


if __name__ == "__main__":
    main()
