import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

from admaker.campaign_video_source import delivered_video_source
from test_worker_leases import URL, queued_job


def test_source_matches_delivered_pack_not_latest_run_and_enforces_owner(queued_job):
    account, job, _, _ = queued_job
    first, latest = uuid.uuid4(), uuid.uuid4()
    accepted, rejected = {"video": {"key": "accepted.mp4"}}, {"video": {"key": "rejected.mp4"}}
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.jobs SET state='delivered',settings=%s,result=%s WHERE id=%s",
                  (Jsonb({"generationKind": "campaign_pack"}), Jsonb({"exports": accepted}), job))
        for index, run in enumerate((first, latest), 1):
            c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state,lease_owner,lease_until,fence) VALUES (%s,%s,%s,%s,'running','fixture',clock_timestamp()+interval '1 minute',1)",
                      (run, job, index, str(run)))
            for stage, value in (("campaign_pack_compose", accepted if run == first else rejected),
                                 ("provider_compose", {"tiktok": {"key": f"runs/{run}/original.mp4"}})):
                c.execute("INSERT INTO app.job_stages(run_id,stage_key,request_hash,result,fence) VALUES (%s,%s,'fixture',%s,1)",
                          (run, stage, Jsonb(value)))
        c.execute("UPDATE app.jobs SET active_run_id=%s WHERE id=%s", (latest, job))
        assert delivered_video_source(c, job, account) == {"runId": str(first), "key": f"runs/{first}/original.mp4"}
        with pytest.raises(ValueError, match="unavailable"):
            delivered_video_source(c, job, uuid.uuid4())
        c.execute("UPDATE app.jobs SET state='awaiting_user_decision' WHERE id=%s", (job,))
        with pytest.raises(ValueError, match="unavailable"):
            delivered_video_source(c, job, account)
        c.execute("UPDATE app.jobs SET state='delivered' WHERE id=%s", (job,))
        c.execute("UPDATE app.job_stages SET result=%s WHERE run_id=%s AND stage_key='campaign_pack_compose'", (Jsonb(accepted), latest))
        with pytest.raises(ValueError, match="unique"):
            delivered_video_source(c, job, account)
        c.execute("UPDATE app.job_stages SET result=%s WHERE run_id=%s AND stage_key='campaign_pack_compose'", (Jsonb(rejected), latest))
        c.execute("UPDATE app.job_stages SET result=%s WHERE run_id=%s AND stage_key='provider_compose'", (Jsonb({"tiktok": {"key": "../foreign.mp4"}}), first))
        with pytest.raises(ValueError, match="invalid"):
            delivered_video_source(c, job, account)
