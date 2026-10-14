import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

from admaker import provider_worker
from admaker.provider_graph import PROVIDER_GRAPH_VERSION
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("settings", [{"generationKind": "campaign_pack"}, {"videoProvider": True, "outputKind": "video"}])
def test_provider_recovery_selects_only_campaign_provider_runs(queued_job, monkeypatch, settings):
    _, job, _, queue = queued_job
    run = uuid.uuid4()
    calls = []
    monkeypatch.setattr(provider_worker, "recover_expired_runs", lambda db, target_queue, target_job: calls.append((target_queue, target_job)) or 1)
    with psycopg.connect(URL) as c:
        c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state,lease_until,graph_version) VALUES (%s,%s,1,%s,'running',clock_timestamp()-interval '1 second',%s)", (run, job, str(run), PROVIDER_GRAPH_VERSION))
        c.execute("UPDATE app.jobs SET active_run_id=%s,state='running' WHERE id=%s", (run, job))
    provider_worker.recover_campaign_provider_runs(URL, queue)
    assert (queue, str(job)) not in calls
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.jobs SET settings=%s WHERE id=%s", (Jsonb(settings), job))
    from admaker.worker import recover_expired_runs
    assert recover_expired_runs(URL, "commands", str(job)) == 0
    calls.clear()
    provider_worker.recover_campaign_provider_runs(URL, queue)
    assert (queue, str(job)) in calls
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.job_runs SET graph_version='legacy-fixture' WHERE id=%s", (run,))
    calls.clear()
    provider_worker.recover_campaign_provider_runs(URL, queue)
    assert (queue, str(job)) not in calls
