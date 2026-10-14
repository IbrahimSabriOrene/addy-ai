import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

from admaker.campaign_generation import load_campaign_generation
from admaker.catalogue import TEMPLATES
from test_worker_leases import URL, queued_job


def test_generation_uses_owned_frozen_campaign_inputs(queued_job, monkeypatch):
    account, job, reservation, queue = queued_job
    product, campaign = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(URL) as connection:
        try:
            asset = connection.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (job,)).fetchone()[0]
            connection.execute("INSERT INTO app.products(id,owner_id,name,source_asset_id) VALUES (%s,%s,'Fixture',%s)", (product, account, asset))
            connection.execute("INSERT INTO app.product_images(product_id,owner_id,version,asset_key) VALUES (%s,%s,1,%s),(%s,%s,2,%s)", (product, account, asset, product, account, asset))
            style = dict(TEMPLATES["pedestal_spin"])
            brief = {"offer": "UNIQUE OFFER 20%", "cta": "UNIQUE CTA", "instructions": "Slow movement", "caption": "Caption"}
            connection.execute("INSERT INTO app.campaigns(id,owner_id,product_id,image_version,brief,style_snapshot) VALUES (%s,%s,%s,1,%s,%s)", (campaign, account, product, Jsonb(brief), Jsonb(style)))
            monkeypatch.setitem(TEMPLATES, "pedestal_spin", {**style, "version": 99, "prompt": "REPLACED"})
            result = load_campaign_generation(connection, campaign, account, 1)
            settings = result["settings"]
            assert result["assetKey"] == str(asset)
            assert settings["imageVersion"] == settings["templateVersion"] == 1
            assert settings["campaignBrief"] == brief
            assert "Slow movement" in settings["preparedVideoPrompt"]
            assert all(text not in settings["preparedVideoPrompt"] for text in ("UNIQUE OFFER", "UNIQUE CTA", "REPLACED"))
            with pytest.raises(LookupError):
                load_campaign_generation(connection, campaign, uuid.uuid4(), 1)
            for version in (2, True):
                with pytest.raises(ValueError, match="version changed"):
                    load_campaign_generation(connection, campaign, account, version)
            connection.execute("UPDATE app.campaigns SET style_snapshot=NULL WHERE id=%s", (campaign,))
            with pytest.raises(ValueError, match="style must be selected"):
                load_campaign_generation(connection, campaign, account, 1)
            connection.execute("UPDATE app.products SET deleted_at=now() WHERE id=%s", (product,))
            with pytest.raises(LookupError):
                load_campaign_generation(connection, campaign, account, 1)
            assert connection.execute("SELECT count(*) FROM app.jobs WHERE owner_id=%s", (account,)).fetchone() == (1,)
            assert connection.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
        finally:
            connection.rollback()
