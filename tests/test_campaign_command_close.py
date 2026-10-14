import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg
import pytest
from psycopg.types.json import Jsonb

from admaker.campaign_commands import close_campaign_command
from admaker.campaign_generation import admit_campaign_generation
from admaker.catalogue import TEMPLATES
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("race", [False, True])
def test_closed_command_cannot_later_create_a_job(queued_job, race):
    account, old_job, reservation, queue = queued_job
    product, campaign = uuid.uuid4(), uuid.uuid4()
    try:
        with psycopg.connect(URL) as c:
            asset = c.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (old_job,)).fetchone()[0]
            c.execute("INSERT INTO app.products(id,owner_id,name,source_asset_id) VALUES (%s,%s,'Fixture',%s)", (product, account, asset))
            c.execute("INSERT INTO app.product_images(product_id,owner_id,version,asset_key) VALUES (%s,%s,1,%s)", (product, account, asset))
            c.execute("INSERT INTO app.campaigns(id,owner_id,product_id,image_version,brief,style_snapshot) VALUES (%s,%s,%s,1,'{}',%s)", (campaign, account, product, Jsonb(TEMPLATES["pedestal_spin"])))
            c.execute("INSERT INTO app.credit_ledger(account_id,delta,event_key) VALUES (%s,10,%s)", (account, str(uuid.uuid4())))
        barrier = Barrier(2)

        def apply(close):
            if race:
                barrier.wait(timeout=10)
            with psycopg.connect(URL) as c:
                if close:
                    return close_campaign_command(c, campaign, account, 1, 3, "command")
                return admit_campaign_generation(c, campaign, account, 1, "command", price_credits=3, confirmed_credits=3, queue=queue)

        if race:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(apply, [True, False]))
        else:
            results = [apply(True), apply(False)]
        assert results[0] == results[1]
        cancelled = results[0]["state"] == "cancelled"
        if not race:
            assert cancelled
        with psycopg.connect(URL) as c:
            assert close_campaign_command(c, campaign, account, 1, 3, "command") == results[0]
            with pytest.raises(ValueError, match="payload mismatch"):
                close_campaign_command(c, campaign, account, 2, 3, "command")
            assert c.execute("SELECT count(*) FROM app.campaign_generations WHERE campaign_id=%s", (campaign,)).fetchone() == (0 if cancelled else 1,)
            assert c.execute("SELECT count(*) FROM app.credit_reservations WHERE account_id=%s AND job_id<>%s", (account, old_job)).fetchone() == (0 if cancelled else 1,)
            assert c.execute("SELECT sum(delta) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (10,)
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.campaign_generations WHERE campaign_id=%s", (campaign,))
            c.execute("DELETE FROM app.credit_reservations WHERE account_id=%s AND job_id<>%s", (account, old_job))
            c.execute("DELETE FROM app.jobs WHERE owner_id=%s AND id<>%s", (account, old_job))
            c.execute("DELETE FROM app.command_keys WHERE account_id=%s", (account,))
            c.execute("DELETE FROM app.campaigns WHERE id=%s", (campaign,))
            c.execute("DELETE FROM app.product_images WHERE product_id=%s", (product,))
            c.execute("DELETE FROM app.products WHERE id=%s", (product,))
