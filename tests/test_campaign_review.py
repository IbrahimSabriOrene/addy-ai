import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from admaker import worker
from admaker.campaign_review import review_campaign_pack
from admaker.provider_graph import PROVIDER_GRAPH_VERSION
from test_provider_graph import Crash
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("decision", ["resume", "release"])
def test_campaign_review_preserves_work_and_replays_exactly(queued_job, monkeypatch, decision):
    account, job, reservation, queue = queued_job

    def crash(*args):
        raise Crash()

    monkeypatch.setattr(worker, "run_worker_graph", crash)
    with pytest.raises(Crash):
        worker.process_one(URL, "first", queue)
    with psycopg.connect(URL) as c:
        run, fence = c.execute("SELECT id,fence FROM app.job_runs WHERE job_id=%s", (job,)).fetchone()
        c.execute("UPDATE app.job_runs SET state='review_required',lease_until=NULL,graph_version=%s WHERE id=%s", (PROVIDER_GRAPH_VERSION, run))
        c.execute("UPDATE app.jobs SET state='failed',result=%s WHERE id=%s", (Jsonb({"failure": {"code": "campaign_pack_incomplete"}}), job))
        c.execute("INSERT INTO app.job_stages(run_id,stage_key,request_hash,result,fence) VALUES (%s,'provider_compose','snapshot','{}',%s),(%s,'campaign_pack_failures','snapshot','{\"count\":3}',%s)", (run, fence, run, fence))
        c.execute("SELECT pgmq.archive(%s,msg_id) FROM pgmq.read(%s,vt=>0,qty=>10)", (queue, queue))
    options = dict(queue=queue) if decision == "resume" else {}
    with pytest.raises(ValueError, match="no longer"):
        review_campaign_pack(URL, run, fence + 1, "operator", "Reason", decision, **options)
    if decision == "resume":
        with pytest.raises(psycopg.Error):
            review_campaign_pack(URL, run, fence, "operator", "Reason", decision, queue="missing_campaign_queue")
    assert review_campaign_pack(URL, run, fence, "operator", "Reason", decision, **options)
    assert not review_campaign_pack(URL, run, fence, "operator", "Reason", decision, **options)
    with pytest.raises(ValueError, match="replay differs"):
        review_campaign_pack(URL, run, fence, "operator", "Different reason", decision, **options)
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("held" if decision == "resume" else "released",)
        assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
        assert c.execute("SELECT count(*) FROM app.campaign_review_audit WHERE run_id=%s", (run,)).fetchone() == (1,)
        assert c.execute("SELECT count(*) FROM app.job_stages WHERE run_id=%s AND stage_key='provider_compose'", (run,)).fetchone() == (1,)
        if decision == "resume":
            assert c.execute("SELECT count(*) FROM app.job_stages WHERE run_id=%s AND stage_key='campaign_pack_failures'", (run,)).fetchone() == (0,)
            assert c.execute(sql.SQL("SELECT count(*) FROM pgmq.{} WHERE read_ct=0").format(sql.Identifier("q_" + queue))).fetchone() == (1,)
        else:
            assert c.execute("SELECT result->'failure'->>'code' FROM app.jobs WHERE id=%s", (job,)).fetchone() == ("generation_closed",)
    for role in ("anon", "authenticated"):
        with psycopg.connect(URL) as c:
            c.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("SELECT * FROM app.campaign_review_audit")
