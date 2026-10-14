"""Audited operator repair/resume or credit release for incomplete campaign packs."""
import psycopg
from psycopg.types.json import Jsonb

from admaker.provider_graph import PROVIDER_GRAPH_VERSION
from admaker.photo_graph import PHOTO_GRAPH_VERSION


def review_campaign_pack(database_url, run_id, expected_fence, operator, reason, decision, queue=None):
    if decision not in {"resume", "release"} or type(expected_fence) is not int or expected_fence < 1:
        raise ValueError("Valid decision and fence required")
    if not operator.strip() or len(operator) > 100 or not reason.strip() or len(reason) > 2000:
        raise ValueError("Operator and bounded reason required")
    if (decision == "resume" and not queue) or (decision == "release" and queue is not None):
        raise ValueError("Specify the configured provider queue only for resume")
    with psycopg.connect(database_url) as c:
        account = c.execute("SELECT j.owner_id FROM app.jobs j JOIN app.job_runs r ON r.job_id=j.id WHERE r.id=%s", (run_id,)).fetchone()
        if not account:
            raise ValueError("Run not found")
        c.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", account)
        job = c.execute("SELECT j.id,j.state,j.active_run_id,j.result->'failure'->>'code' FROM app.jobs j JOIN app.job_runs r ON r.job_id=j.id WHERE r.id=%s FOR UPDATE OF j", (run_id,)).fetchone()
        previous = c.execute("SELECT operator,reason,decision,queue_name FROM app.campaign_review_audit WHERE run_id=%s AND fence=%s", (run_id, expected_fence)).fetchone()
        if previous:
            if previous != (operator, reason, decision, queue):
                raise ValueError("Review replay differs")
            return False
        run = c.execute("SELECT state,fence,graph_version FROM app.job_runs WHERE id=%s FOR UPDATE", (run_id,)).fetchone()
        if str(job[2]) != str(run_id) or job[1] != "failed" or job[3] not in {"campaign_pack_incomplete", "media_review_pending"} or run[:2] != ("review_required", expected_fence):
            raise ValueError("Run is no longer at this campaign review")
        holds = c.execute("SELECT a.id,r.id FROM app.job_attempts a JOIN app.credit_reservations r ON r.id=a.reservation_id WHERE a.run_id=%s AND a.state='running' AND r.state='held' AND r.job_id=%s FOR UPDATE OF a,r", (run_id, job[0])).fetchall()
        if len(holds) != 1:
            raise ValueError("Exactly one original held reservation required")
        if decision == "resume":
            stages = ["provider_compose", "input_media"] if job[3] == "media_review_pending" else ["provider_compose"]
            versions = {PROVIDER_GRAPH_VERSION, PHOTO_GRAPH_VERSION} if job[3] == "media_review_pending" else {PROVIDER_GRAPH_VERSION}
            if run[2] not in versions or not c.execute("SELECT 1 FROM app.job_stages WHERE run_id=%s AND stage_key=ANY(%s)", (run_id, stages)).fetchone():
                raise ValueError("Compatible completed media stage required")
            c.execute("DELETE FROM app.job_stages WHERE run_id=%s AND stage_key='campaign_pack_failures'", (run_id,))
            c.execute("UPDATE app.job_runs SET state='running',lease_until=clock_timestamp()-interval '1 second',next_work_at=NULL WHERE id=%s", (run_id,))
            c.execute("UPDATE app.jobs SET state='submitted',result=result-'failure' WHERE id=%s", (job[0],))
            c.execute("SELECT pgmq.send(%s,%s)", (queue, Jsonb({"jobId": str(job[0])})))
        else:
            c.execute("UPDATE app.credit_reservations SET state='released' WHERE id=%s", (holds[0][1],))
            c.execute("UPDATE app.job_attempts SET state='failed',completed_at=now() WHERE id=%s", (holds[0][0],))
            c.execute("UPDATE app.job_runs SET state='failed',lease_until=NULL,next_work_at=NULL WHERE id=%s", (run_id,))
            c.execute("UPDATE app.jobs SET result=result || %s WHERE id=%s", (Jsonb({"failure": {"code": "generation_closed"}}), job[0]))
        c.execute("INSERT INTO app.campaign_review_audit(run_id,fence,operator,reason,decision,queue_name) VALUES (%s,%s,%s,%s,%s,%s)", (run_id, expected_fence, operator, reason, decision, queue))
    return True


def main():
    import argparse
    import json
    import os
    import uuid
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["list", "resume", "release"])
    parser.add_argument("--run", type=uuid.UUID)
    parser.add_argument("--expected-fence", type=int)
    parser.add_argument("--operator")
    parser.add_argument("--reason-file", type=Path)
    parser.add_argument("--queue")
    args = parser.parse_args()
    if args.command == "list":
        with psycopg.connect(os.environ["DATABASE_URL"]) as c:
            rows = c.execute("SELECT r.id,r.job_id,r.fence FROM app.job_runs r JOIN app.jobs j ON j.active_run_id=r.id WHERE r.state='review_required' AND j.result->'failure'->>'code' IN ('campaign_pack_incomplete','media_review_pending') ORDER BY r.id LIMIT 100").fetchall()
        print(json.dumps(rows, default=str))
    else:
        if not all((args.run, args.expected_fence, args.operator, args.reason_file)):
            parser.error("--run, --expected-fence, --operator and --reason-file are required")
        applied = review_campaign_pack(os.environ["DATABASE_URL"], args.run, args.expected_fence, args.operator, args.reason_file.read_text(encoding="utf-8"), args.command, args.queue)
        print("Review applied." if applied else "Review already recorded.")


if __name__ == "__main__":
    main()
