import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

from admaker.campaign_generation import admit_campaign_generation
from admaker.catalogue import TEMPLATES
from test_worker_leases import URL, queued_job


def test_campaign_admission_is_atomic_and_replayable(queued_job):
    account, existing_job, reservation, queue = queued_job
    product, campaign = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(URL) as connection:
        try:
            asset = connection.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (existing_job,)).fetchone()[0]
            connection.execute("INSERT INTO app.products(id,owner_id,name,source_asset_id) VALUES (%s,%s,'Fixture',%s)", (product, account, asset))
            connection.execute("INSERT INTO app.product_images(product_id,owner_id,version,asset_key) VALUES (%s,%s,1,%s)", (product, account, asset))
            connection.execute("INSERT INTO app.campaigns(id,owner_id,product_id,image_version,brief,style_snapshot) VALUES (%s,%s,%s,1,%s,%s)", (campaign, account, product, Jsonb({"offer": "20%"}), Jsonb(TEMPLATES["pedestal_spin"])))
            options = dict(price_credits=3, confirmed_credits=3, queue=queue)
            with pytest.raises(ValueError, match="Insufficient credits"):
                admit_campaign_generation(connection, campaign, account, 1, "generate", **options)
            connection.execute("INSERT INTO app.credit_ledger(account_id,delta,event_key) VALUES (%s,10,%s)", (account, str(uuid.uuid4())))
            with pytest.raises(psycopg.Error):
                with connection.transaction():
                    admit_campaign_generation(connection, campaign, account, 1, "generate", **{**options, "queue": "missing_" + uuid.uuid4().hex})
            assert connection.execute("SELECT count(*) FROM app.campaign_generations WHERE campaign_id=%s", (campaign,)).fetchone() == (0,)
            first = admit_campaign_generation(connection, campaign, account, 1, "generate", **options)
            connection.execute("UPDATE app.campaigns SET version=2 WHERE id=%s", (campaign,))
            assert admit_campaign_generation(connection, campaign, account, 1, "generate", **options) == first
            with pytest.raises(ValueError, match="payload mismatch"):
                admit_campaign_generation(connection, campaign, account, 2, "generate", **options)
            with pytest.raises(ValueError, match="confirmation changed"):
                admit_campaign_generation(connection, campaign, account, 2, "other", **{**options, "confirmed_credits": 2})
            assert connection.execute("SELECT amount,state FROM app.credit_reservations WHERE job_id=%s", (first["id"],)).fetchone() == (3, "held")
            assert connection.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (1,)
            settings = connection.execute("SELECT settings FROM app.jobs WHERE id=%s", (first["id"],)).fetchone()[0]
            assert settings["campaignVersion"] == 1
            assert settings["campaignBrief"] == {"offer": "20%"}
            assert settings["priceSnapshot"] == {"credits": 3, "scope": "campaign_pack"}
            assert connection.execute("SELECT count(*) FROM app.campaign_generations WHERE campaign_id=%s", (campaign,)).fetchone() == (1,)
        finally:
            connection.rollback()
