"""Load private, version-bound inputs for campaign pack execution."""
from admaker.job_prompts import prepare_video_prompt
import hashlib
import json
import uuid
import os

from psycopg.types.json import Jsonb


def load_campaign_generation(cursor, campaign_id, owner_id, expected_version):
    """Call inside the admission transaction; holds the campaign/product locks."""
    row = cursor.execute(
        "SELECT c.version,c.product_id,c.image_version,c.brief,c.style_snapshot,i.asset_key "
        "FROM app.campaigns c JOIN app.products p ON p.id=c.product_id "
        "JOIN app.product_images i ON i.product_id=c.product_id AND i.version=c.image_version "
        "JOIN app.assets a ON a.asset_key=i.asset_key "
        "WHERE c.id=%s AND c.owner_id=%s AND p.owner_id=c.owner_id AND p.deleted_at IS NULL "
        "AND a.owner_id=c.owner_id AND a.verification_state='verified' FOR UPDATE OF c,p",
        (campaign_id, owner_id),
    ).fetchone()
    if not row:
        raise LookupError("Campaign or approved image is unavailable")
    version, product_id, image_version, brief, style, asset_key = row
    if type(expected_version) is not int or version != expected_version:
        raise ValueError("Campaign version changed")
    if not style or not isinstance(style.get("prompt"), str) or not style["prompt"].strip():
        raise ValueError("Campaign style must be selected before generation")
    from admaker.campaign_layouts import preflight_campaign_text
    preflight_campaign_text(brief)
    # Offers/CTA stay in deterministic layouts; edits must not purchase new video.
    prompt = prepare_video_prompt(style["prompt"], brief.get("instructions", ""))
    return {
        "assetKey": str(asset_key),
        "settings": {
            "structuredPlanning": os.environ.get("ENABLE_STRUCTURED_PLANNING") == "true",
            "campaignId": str(campaign_id), "campaignVersion": version,
            "productId": str(product_id), "imageVersion": image_version,
            "campaignBrief": brief, "templateId": style["id"],
            "templateVersion": style["version"], "preparedVideoPrompt": prompt,
            "outputKind": "video", "platforms": ["tiktok"],
            "renderPlatforms": ["tiktok"], "quality": "fast", "fastMode": True,
        },
    }


def admit_campaign_generation(cursor, campaign_id, owner_id, expected_version,
                              command_key, *, price_credits, confirmed_credits, queue):
    """Internal transactional admission; caller supplies server-controlled pack price.

    Not exposed for sale until pack composition/settlement is connected. Queue is
    explicit so incomplete pack work cannot enter the standalone worker by default.
    """
    if not isinstance(command_key, str) or not 1 <= len(command_key) <= 200:
        raise ValueError("Valid command key required")
    if type(confirmed_credits) is not int or not 0 < confirmed_credits <= 10000:
        raise ValueError("Valid confirmed pack price required")
    if type(expected_version) is not int or expected_version < 1:
        raise ValueError("Valid campaign version required")
    request_hash = hashlib.sha256(json.dumps(
        [str(campaign_id), expected_version, confirmed_credits], separators=(",", ":")
    ).encode()).hexdigest()
    if not cursor.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (owner_id,)).fetchone():
        raise LookupError("Account not found")
    previous = cursor.execute(
        "SELECT request_hash,response FROM app.command_keys WHERE account_id=%s AND route='campaign-generate' AND key=%s",
        (owner_id, command_key),
    ).fetchone()
    if previous:
        if previous[0] != request_hash:
            raise ValueError("Command key payload mismatch")
        return previous[1]
    if type(price_credits) is not int or not 0 < price_credits <= 10000:
        raise ValueError("Valid server pack price required")
    if confirmed_credits != price_credits:
        raise ValueError("Pack price confirmation changed")
    prepared = load_campaign_generation(cursor, campaign_id, owner_id, expected_version)
    if cursor.execute("SELECT job_id FROM app.campaign_generations WHERE campaign_id=%s AND campaign_version=%s", (campaign_id, expected_version)).fetchone():
        raise ValueError("This campaign version already has a generation")
    from admaker.admission_limit import require_generation_capacity
    require_generation_capacity(cursor, owner_id)
    available = cursor.execute(
        "SELECT COALESCE(sum(delta),0)-(SELECT COALESCE(sum(amount),0) FROM app.credit_reservations WHERE account_id=%s AND state='held') FROM app.credit_ledger WHERE account_id=%s",
        (owner_id, owner_id),
    ).fetchone()[0]
    if available < price_credits:
        raise ValueError("Insufficient credits")
    job_id = uuid.uuid4()
    settings = {**prepared["settings"], "generationKind": "campaign_pack",
                "priceSnapshot": {"credits": price_credits, "scope": "campaign_pack"}}
    cursor.execute("INSERT INTO app.jobs(id,owner_id,source_asset_id,state,settings) VALUES (%s,%s,%s,'submitted',%s)", (job_id, owner_id, prepared["assetKey"], Jsonb(settings)))
    cursor.execute("INSERT INTO app.credit_reservations(id,account_id,job_id,amount,state) VALUES (%s,%s,%s,%s,'held')", (uuid.uuid4(), owner_id, job_id, price_credits))
    cursor.execute("INSERT INTO app.campaign_generations(campaign_id,campaign_version,job_id,price_credits) VALUES (%s,%s,%s,%s)", (campaign_id, expected_version, job_id, price_credits))
    cursor.execute("SELECT pgmq.send(%s,%s::jsonb)", (queue, Jsonb({"jobId": str(job_id)})))
    response = {"id": str(job_id), "campaignId": str(campaign_id), "campaignVersion": expected_version, "state": "submitted", "priceCredits": price_credits}
    cursor.execute("INSERT INTO app.command_keys(account_id,route,key,request_hash,response) VALUES (%s,'campaign-generate',%s,%s,%s)", (owner_id, command_key, request_hash, Jsonb(response)))
    return response
