import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from admaker.campaign_generation import admit_campaign_generation
from admaker.catalogue import TEMPLATES
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_campaign_admission_preserves_one_reservation(queued_job, same_key):
    account, existing_job, reservation, queue = queued_job
    product, campaign = uuid.uuid4(), uuid.uuid4()
    try:
        with psycopg.connect(URL) as c:
            asset = c.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (existing_job,)).fetchone()[0]
            c.execute("INSERT INTO app.products(id,owner_id,name,source_asset_id) VALUES (%s,%s,'Fixture',%s)", (product, account, asset))
            c.execute("INSERT INTO app.product_images(product_id,owner_id,version,asset_key) VALUES (%s,%s,1,%s)", (product, account, asset))
            c.execute("INSERT INTO app.campaigns(id,owner_id,product_id,image_version,brief,style_snapshot) VALUES (%s,%s,%s,1,'{}',%s)", (campaign, account, product, Jsonb(TEMPLATES["pedestal_spin"])))
            c.execute("INSERT INTO app.credit_ledger(account_id,delta,event_key) VALUES (%s,10,%s)", (account, str(uuid.uuid4())))
        barrier = Barrier(2)

        def submit(index):
            key = "same" if same_key else str(index)
            barrier.wait(timeout=10)
            try:
                with psycopg.connect(URL) as c:
                    return key, admit_campaign_generation(c, campaign, account, 1, key, price_credits=3, confirmed_credits=3, queue=queue)
            except ValueError as error:
                assert "already has a generation" in str(error)
                return key, None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, [0, 1]))
        successes = [(key, result) for key, result in results if result]
        assert len(successes) == (2 if same_key else 1)
        assert len({result["id"] for _, result in successes}) == 1
        key, first = successes[0]
        with psycopg.connect(URL) as c:
            # A lost response remains replayable after a server price change.
            assert admit_campaign_generation(c, campaign, account, 1, key, price_credits=4, confirmed_credits=3, queue=queue) == first
            assert c.execute("SELECT count(*) FROM app.campaign_generations WHERE campaign_id=%s", (campaign,)).fetchone() == (1,)
            assert c.execute("SELECT amount,state FROM app.credit_reservations WHERE job_id=%s", (first["id"],)).fetchone() == (3, "held")
            assert c.execute(sql.SQL("SELECT count(*) FROM pgmq.{} WHERE message->>'jobId'=%s").format(sql.Identifier("q_" + queue)), (first["id"],)).fetchone() == (1,)
            assert c.execute("SELECT sum(delta) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (10,)
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.campaign_generations WHERE campaign_id=%s", (campaign,))
            c.execute("DELETE FROM app.command_keys WHERE account_id=%s", (account,))
            c.execute("DELETE FROM app.credit_reservations WHERE account_id=%s AND job_id<>%s", (account, existing_job))
            c.execute("DELETE FROM app.jobs WHERE owner_id=%s AND id<>%s", (account, existing_job))
            c.execute("DELETE FROM app.campaigns WHERE id=%s", (campaign,))
            c.execute("DELETE FROM app.product_images WHERE product_id=%s", (product,))
            c.execute("DELETE FROM app.products WHERE id=%s", (product,))
