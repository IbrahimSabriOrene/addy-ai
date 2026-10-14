import uuid

import psycopg
import pytest
from PIL import Image
from psycopg import sql
from psycopg.types.json import Jsonb

from admaker.campaign_generation import admit_campaign_generation
from admaker.campaign_layouts import preflight_campaign_text, render_campaign_layouts
from admaker.catalogue import TEMPLATES
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("brief", [
    {"offer": "\U0010ffff"},
    {"offer": "Sale\n" * 30},
    {"cta": "Buy\n" * 20},
    {"contact": "bad\ncontact"},
    {"font": "unknown"},
])
def test_invalid_text_cannot_reserve_credits_or_queue_work(queued_job, brief):
    account, job, reservation, queue = queued_job
    with psycopg.connect(URL) as connection:
        try:
            asset = connection.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (job,)).fetchone()[0]
            product, campaign = uuid.uuid4(), uuid.uuid4()
            connection.execute("INSERT INTO app.products(id,owner_id,name,source_asset_id) VALUES (%s,%s,'Preflight',%s)", (product, account, asset))
            connection.execute("INSERT INTO app.product_images(product_id,owner_id,version,asset_key) VALUES (%s,%s,1,%s)", (product, account, asset))
            connection.execute("INSERT INTO app.campaigns(id,owner_id,product_id,image_version,brief,style_snapshot) VALUES (%s,%s,%s,1,%s,%s)", (campaign, account, product, Jsonb(brief), Jsonb(TEMPLATES["pedestal_spin"])))
            connection.execute("INSERT INTO app.credit_ledger(account_id,delta,event_key) VALUES (%s,10,%s)", (account, str(uuid.uuid4())))
            with pytest.raises(ValueError, match="No new credits were reserved"):
                admit_campaign_generation(connection, campaign, account, 1, "invalid", price_credits=3, confirmed_credits=3, queue=queue)
            assert connection.execute("SELECT count(*) FROM app.jobs WHERE owner_id=%s", (account,)).fetchone() == (1,)
            assert connection.execute("SELECT count(*) FROM app.credit_reservations WHERE account_id=%s", (account,)).fetchone() == (1,)
            assert connection.execute("SELECT sum(delta) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (10,)
            assert connection.execute("SELECT count(*) FROM app.command_keys WHERE account_id=%s", (account,)).fetchone() == (0,)
            assert connection.execute(sql.SQL("SELECT count(*) FROM pgmq.{}").format(sql.Identifier("q_" + queue))).fetchone() == (1,)
        finally:
            connection.rollback()


@pytest.mark.parametrize("family", ["sans", "serif"])
def test_turkish_brand_text_passes_preflight_and_renders(tmp_path, family):
    source = tmp_path / "product.png"
    Image.new("RGB", (20, 30), "blue").save(source)
    brief = {"offer": "Şişli’ye özel %20 indirim\nİğne, çiçek ve örgü", "cta": "Şimdi keşfet",
             "contact": "örnek.com • İstanbul", "font": family, "logoAssetKey": str(uuid.uuid4())}
    preflight_campaign_text(brief)
    result = render_campaign_layouts(source, tmp_path / "output", brief, logo=source)
    assert result["story"]["offer"] == brief["offer"]
    assert Image.open(result["feed"]["path"]).size == (1080, 1080)


def test_missing_font_fails_closed(monkeypatch):
    monkeypatch.setenv("CAMPAIGN_FONT_PATH", "missing-font-file.ttf")
    with pytest.raises(OSError):
        preflight_campaign_text({"offer": "Sale"})


def test_paid_retry_also_checks_saved_text(monkeypatch):
    from fastapi import HTTPException
    from admaker.retry_pricing import retry_terms
    monkeypatch.setattr("admaker.campaign_routes.campaign_pack_configuration", lambda: (3, "pack"))
    monkeypatch.setattr("admaker.consent.require_ai_consent", lambda _: None)
    with pytest.raises(HTTPException) as error:
        retry_terms({"generationKind": "campaign_pack", "priceSnapshot": {"credits": 3},
                     "campaignBrief": {"offer": "\U0010ffff"}}, 3, "owner")
    assert error.value.status_code == 409
    assert "No new credits were reserved" in error.value.detail
