"""Read-only operational snapshot: python -m admaker.ops_status --queue commands."""
import argparse
import json
import os

import psycopg
from psycopg import sql

from admaker.provider_budget import provider_operations_inflight


def operational_snapshot(database_url, queue):
    with psycopg.connect(database_url) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        observed = c.execute("SELECT now()").fetchone()[0]
        queued, visible, oldest = c.execute(sql.SQL("""
            SELECT count(*), count(*) FILTER (WHERE vt<=now()),
                coalesce(extract(epoch FROM now()-min(enqueued_at)),0)
            FROM pgmq.{}
        """).format(sql.Identifier("q_" + queue))).fetchone()
        expired, overdue, review = c.execute("""
            SELECT count(*) FILTER (WHERE r.state='running' AND j.state='running'
                    AND r.lease_until<now() AND (r.next_work_at IS NULL OR r.next_work_at<=now())),
                coalesce(max(extract(epoch FROM now()-r.lease_until)) FILTER
                    (WHERE r.state='running' AND j.state='running' AND r.lease_until<now()
                    AND (r.next_work_at IS NULL OR r.next_work_at<=now())),0),
                count(*) FILTER (WHERE r.state='review_required')
            FROM app.job_runs r JOIN app.jobs j ON j.active_run_id=r.id
        """).fetchone()
        held_count, held_credits = c.execute("SELECT count(*),coalesce(sum(amount),0) FROM app.credit_reservations WHERE state='held'").fetchone()
        media_budget = dict(c.execute("SELECT media_kind,sum(amount_microusd) FROM app.provider_budget_holds WHERE created_at>=date_trunc('day',now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' GROUP BY media_kind").fetchall())
        budget = sum(media_budget.values())
        review_budget, unconfirmed_reviews, oldest_review = c.execute("""
            SELECT coalesce(sum(amount_microusd) FILTER (WHERE created_at>=date_trunc('day',now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'),0),
                count(*) FILTER (WHERE state='unconfirmed'),
                coalesce(max(extract(epoch FROM now()-created_at)) FILTER (WHERE state='unconfirmed'),0)
            FROM app.media_review_budget
        """).fetchone()
        deletions = c.execute("""SELECT count(*) FROM app.account_deletions WHERE state='requested'
            AND (application_deleted_at IS NULL OR billing_minimized_at IS NULL)
            AND (next_attempt_at IS NULL OR next_attempt_at<=now())""").fetchone()[0]
        return {
            "event": "operational_snapshot", "observedAt": observed.isoformat(), "queue": queue,
            "queueMessages": queued, "queueVisibleMessages": visible,
            "queueOldestAgeSeconds": max(0, float(oldest)),
            "recoverableExpiredRuns": expired, "oldestExpiredLeaseSeconds": max(0, float(overdue)),
            "reviewRequiredRuns": review, "heldReservations": held_count, "heldCredits": held_credits,
            "providerOperationsInflight": provider_operations_inflight(c),
            "providerCommittedEstimateMicrousdToday": int(budget), "deletionPhasesDue": deletions,
            "videoCommittedEstimateMicrousdToday": int(media_budget.get("video", 0)),
            "photoCommittedEstimateMicrousdToday": int(media_budget.get("photo", 0)),
            "reviewAndPlanningCommittedEstimateMicrousdToday": int(review_budget),
            "totalCommittedEstimateMicrousdToday": int(budget + review_budget),
            "photoOperationsInflight": provider_operations_inflight(c, "photo"),
            "videoOperationsInflight": provider_operations_inflight(c, "video"),
            "unconfirmedReviewAndPlanningCalls": unconfirmed_reviews,
            "oldestUnconfirmedReviewAndPlanningSeconds": max(0, float(oldest_review)),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", default="commands")
    args = parser.parse_args()
    try:
        result = operational_snapshot(os.environ["DATABASE_URL"], args.queue)
    except (psycopg.Error, KeyError):
        print(json.dumps({"event": "operational_snapshot_failed", "message": "Operational snapshot unavailable"}))
        raise SystemExit(1) from None
    print(json.dumps(result))


if __name__ == "__main__":
    main()
