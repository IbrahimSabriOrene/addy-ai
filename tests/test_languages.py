import uuid
from datetime import datetime, timezone

import psycopg
import pytest
from pydantic import ValidationError
from PIL import Image

from admaker.api import CampaignRequest, CampaignEditRequest
from admaker.growth import Preferences
from admaker.growth_worker import dispatch_account, collect_notifications, PUSH_TEXT
from admaker.campaign_layouts import render_campaign_layouts, preflight_campaign_text
from test_growth import growth_account
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("locale,offer", [("en", "Save 20%\nToday"), ("tr", "İlk alışverişe %20 indirim\nÇığ Şölen"), ("pt-BR", "Promoção: R$ 29,90\nSó hoje"), ("es", "¡Oferta! 19,90 €\nSólo hoy")])
def test_languages_validate_and_render_exact_text(locale, offer, tmp_path):
    payload = {"productId": str(uuid.uuid4()), "imageVersion": 1}
    legacy = CampaignRequest(**payload)
    assert "campaignLanguage" not in legacy.model_dump(exclude_none=True)
    assert CampaignRequest(**payload, campaignLanguage=locale).campaignLanguage == locale
    assert Preferences(locale=locale).locale == locale
    brief = {"offer": offer, "cta": "Comprar / Satın al", "campaignLanguage": locale}
    source = tmp_path / "product.png"
    Image.new("RGB", (32, 32), "red").save(source)
    for font in ("sans", "serif"):
        brief["font"] = font
        preflight_campaign_text(brief)
        outputs = render_campaign_layouts(source, tmp_path / font, brief)
        assert all(output["offer"] == offer for output in outputs.values())
    with pytest.raises(ValidationError):
        CampaignRequest(**payload, campaignLanguage="xx")
    with pytest.raises(ValidationError):
        CampaignEditRequest(expectedVersion=1, offer="", caption="", cta="", color="#FFFFFF", campaignLanguage="xx")


@pytest.mark.parametrize("locale", ["en", "tr", "pt-BR", "es"])
def test_language_only_update_preserves_consent_and_localizes_push(growth_account, locale):
    account, job, client = growth_account
    now = datetime.now(timezone.utc).replace(hour=10, minute=0)
    prefs = {**Preferences().model_dump(), "weekly": True, "weekday": now.weekday(), "expectedVersion": 0}
    assert client.put("/v1/account/engagement", json=prefs).status_code == 200
    with psycopg.connect(URL) as c:
        before = c.execute("SELECT preferences,version,updated_at FROM app.growth_preferences WHERE account_id=%s", (account,)).fetchone()
    assert client.put("/v1/account/language", json={"locale": locale}).status_code == 200
    assert client.put("/v1/account/language", json={"locale": "de"}).status_code == 422
    assert client.put("/v1/account/language", json={"locale": locale, "completion": True}).status_code == 422
    with psycopg.connect(URL) as c:
        after = c.execute("SELECT preferences,version,updated_at FROM app.growth_preferences WHERE account_id=%s", (account,)).fetchone()
        assert after == ({**before[0], "locale": locale}, before[1], before[2])
        collect_notifications(c, account, now)
    assert client.put("/v1/account/push-device", json={"token": "ExpoPushToken[language]"}).status_code == 200
    sent = []
    dispatch_account(URL, account, send=lambda message: (sent.append(message) or {"status": "ok", "id": "language"}), now=now)
    assert len(sent) == 1
    assert sent[0]["body"] == PUSH_TEXT[locale]["weekly"]


def test_campaign_language_persist_edit_and_copy_without_jobs(growth_account):
    account, job, client = growth_account
    product = uuid.uuid4()
    with psycopg.connect(URL) as c:
        asset = c.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (job,)).fetchone()[0]
        c.execute("INSERT INTO app.products(id,owner_id,name,source_asset_id) VALUES (%s,%s,'Language',%s)", (product, account, asset))
        c.execute("INSERT INTO app.product_images(product_id,owner_id,version,asset_key) VALUES (%s,%s,1,%s)", (product, account, asset))
    try:
        payload = {"productId": str(product), "imageVersion": 1, "campaignLanguage": "tr", "offer": "Çiçeklerde %20", "caption": "Aynen kalır", "cta": "Satın al", "color": "#FFFFFF"}
        headers = {"Idempotency-Key": "language"}
        first = client.post("/v1/campaigns", json=payload, headers=headers)
        assert first.status_code == 201, first.text
        assert client.post("/v1/campaigns", json=payload, headers=headers).json() == first.json()
        assert client.post("/v1/campaigns", json={**payload, "campaignLanguage": "es"}, headers=headers).status_code == 409
        route = f"/v1/campaigns/{first.json()['id']}"
        edit = client.patch(route, json={**payload, "expectedVersion": 1, "campaignLanguage": "es"})
        assert edit.status_code == 200, edit.text
        brief = client.get(route).json()["brief"]
        assert brief["campaignLanguage"] == "es"
        assert brief["offer"] == payload["offer"] and brief["caption"] == payload["caption"]
        copied = client.post("/v1/campaigns", json={**brief, "productId": str(product), "imageVersion": 1}, headers={"Idempotency-Key": "language-copy"})
        assert copied.status_code == 201 and copied.json()["brief"] == brief
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT count(*) FROM app.jobs WHERE owner_id=%s", (account,)).fetchone() == (1,)
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.command_keys WHERE account_id=%s", (account,))
            c.execute("DELETE FROM app.campaigns WHERE owner_id=%s", (account,))
            c.execute("DELETE FROM app.product_images WHERE owner_id=%s", (account,))
            c.execute("DELETE FROM app.products WHERE owner_id=%s", (account,))
