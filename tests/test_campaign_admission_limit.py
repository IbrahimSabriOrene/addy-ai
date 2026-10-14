import uuid

import psycopg
import pytest
from fastapi import HTTPException
from psycopg.types.json import Jsonb

from admaker.campaign_generation import admit_campaign_generation
from admaker.catalogue import TEMPLATES
from test_worker_leases import URL, queued_job


def test_campaign_shares_standalone_capacity_and_replays_at_limit(queued_job, monkeypatch):
    account, job, _, queue = queued_job
    monkeypatch.setenv("MAX_OUTSTANDING_JOBS_PER_ACCOUNT", "1")
    product, campaign = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(URL) as c:
        try:
            asset = c.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (job,)).fetchone()[0]
            c.execute("INSERT INTO app.products(id,owner_id,name,source_asset_id) VALUES (%s,%s,'Capacity fixture',%s)", (product, account, asset))
            c.execute("INSERT INTO app.product_images(product_id,owner_id,version,asset_key) VALUES (%s,%s,1,%s)", (product, account, asset))
            c.execute("INSERT INTO app.campaigns(id,owner_id,product_id,image_version,brief,style_snapshot) VALUES (%s,%s,%s,1,'{}',%s)", (campaign, account, product, Jsonb(TEMPLATES["pedestal_spin"])))
            c.execute("INSERT INTO app.credit_ledger(account_id,delta,event_key) VALUES (%s,20,%s)", (account, str(uuid.uuid4())))
            def admit():
                return admit_campaign_generation(c, campaign, account, 1, "capacity-pack", price_credits=3, confirmed_credits=3, queue=queue)
            with pytest.raises(HTTPException) as error:
                admit()
            assert error.value.status_code == 429
            assert c.execute("SELECT count(*) FROM app.campaign_generations WHERE campaign_id=%s", (campaign,)).fetchone()[0] == 0
            c.execute("UPDATE app.credit_reservations SET state='released' WHERE job_id=%s", (job,))
            first = admit()
            assert admit() == first
            assert c.execute("SELECT count(*) FROM app.credit_reservations WHERE account_id=%s AND state='held'", (account,)).fetchone()[0] == 1
        finally:
            c.rollback()
