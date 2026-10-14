"""Pause incompatible checkpoints without discarding them or spending again."""
import psycopg
from psycopg.types.json import Jsonb
from admaker.db import lock_run_lease


def pause_incompatible_run(database_url, run_id, owner, fence, expected_version, queue, message_id):
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        lock_run_lease(cursor, run_id, owner, fence)
        cursor.execute("SELECT graph_version,job_id FROM app.job_runs WHERE id=%s", (run_id,))
        version, job_id = cursor.fetchone()
        if version == expected_version:
            return False
        cursor.execute("UPDATE app.job_runs SET state='review_required',lease_until=NULL,next_work_at=NULL WHERE id=%s", (run_id,))
        cursor.execute("UPDATE app.jobs SET state='failed',result=result || %s WHERE id=%s", (Jsonb({"failure": {"code": "incompatible_run"}}), job_id))
        cursor.execute("SELECT pgmq.archive(%s,%s)", (queue, message_id))
        return True


def resume_compatible_run(database_url, run_id, expected_fence, operator, reason, mode="fixture", queue="commands"):
    from admaker.graph import WORKER_GRAPH_VERSION
    from admaker.provider_graph import PROVIDER_GRAPH_VERSION
    from admaker.photo_graph import PHOTO_GRAPH_VERSION
    if mode not in {"fixture", "provider", "photo"} or type(expected_fence) is not int or expected_fence < 1:
        raise ValueError("Valid worker mode and expected fence are required")
    if mode == "photo":
        import os
        import re
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,47}", queue) or queue in {"commands", os.environ.get("CAMPAIGN_PACK_QUEUE", "")}:
            raise ValueError("A dedicated photo queue is required")
    if not isinstance(operator, str) or not operator.strip() or len(operator) > 100 or not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise ValueError("Operator and a bounded review reason are required")
    supported = {"fixture": WORKER_GRAPH_VERSION, "provider": PROVIDER_GRAPH_VERSION, "photo": PHOTO_GRAPH_VERSION}[mode]
    with psycopg.connect(database_url) as connection:
        job = connection.execute("SELECT j.id,j.state,j.active_run_id,j.result->'failure'->>'code' FROM app.jobs j JOIN app.job_runs r ON r.job_id=j.id WHERE r.id=%s FOR UPDATE OF j", (run_id,)).fetchone()
        if not job:
            raise ValueError("Run not found")
        previous = connection.execute("SELECT operator,reason,worker_mode,queue_name FROM app.run_resume_audit WHERE run_id=%s AND fence=%s", (run_id, expected_fence)).fetchone()
        if previous:
            if previous != (operator, reason, mode, queue):
                raise ValueError("Resume audit replay differs")
            return False
        run = connection.execute("SELECT state,fence,graph_version FROM app.job_runs WHERE id=%s FOR UPDATE", (run_id,)).fetchone()
        if str(job[2]) != str(run_id) or job[1] != "failed" or job[3] != "incompatible_run" or run[:2] != ("review_required", expected_fence):
            raise ValueError("Run is no longer at this incompatible-version review")
        if run[2] != supported:
            raise ValueError("This installed worker cannot resume the recorded graph version")
        holds = connection.execute("SELECT r.id FROM app.credit_reservations r JOIN app.job_attempts a ON a.reservation_id=r.id WHERE a.run_id=%s AND a.state='running' AND r.state='held' AND r.job_id=%s FOR UPDATE OF r", (run_id, job[0])).fetchall()
        if len(holds) != 1:
            raise ValueError("Exactly one original held reservation is required")
        connection.execute("UPDATE app.job_runs SET state='running',lease_until=clock_timestamp()-interval '1 second',next_work_at=NULL WHERE id=%s", (run_id,))
        connection.execute("UPDATE app.jobs SET state='submitted',result=result-'failure' WHERE id=%s", (job[0],))
        connection.execute("SELECT pgmq.send(%s,%s)", (queue, Jsonb({"jobId": str(job[0])})))
        connection.execute("INSERT INTO app.run_resume_audit(run_id,fence,operator,reason,worker_mode,queue_name) VALUES (%s,%s,%s,%s,%s,%s)", (run_id, expected_fence, operator, reason, mode, queue))
    return True


def main():
    import argparse
    import json
    import os
    import uuid
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    resume = sub.add_parser("resume")
    resume.add_argument("run_id", type=uuid.UUID)
    resume.add_argument("--expected-fence", type=int, required=True)
    resume.add_argument("--operator", required=True)
    resume.add_argument("--reason-file", type=Path, required=True)
    resume.add_argument("--mode", choices=["fixture", "provider", "photo"], default="fixture")
    resume.add_argument("--queue", default="commands")
    args = parser.parse_args()
    if args.command == "list":
        with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
            rows = connection.execute("SELECT r.id,r.job_id,r.fence,r.graph_version FROM app.job_runs r JOIN app.jobs j ON j.active_run_id=r.id WHERE r.state='review_required' AND j.result->'failure'->>'code'='incompatible_run' ORDER BY r.id LIMIT 100").fetchall()
        print(json.dumps(rows, default=str))
    else:
        changed = resume_compatible_run(os.environ["DATABASE_URL"], args.run_id, args.expected_fence, args.operator, args.reason_file.read_text(encoding="utf-8"), args.mode, args.queue)
        print("Run queued for compatible resume." if changed else "This resume was already recorded.")


if __name__ == "__main__":
    main()
