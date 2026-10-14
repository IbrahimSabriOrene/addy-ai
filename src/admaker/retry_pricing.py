"""Keep paid pack retries on their explicitly confirmed price and worker queue."""
from fastapi import HTTPException


def retry_terms(settings, confirmed_credits, owner_id):
    if settings.get("generationKind") != "campaign_pack":
        from admaker.photo_routing import photo_queue
        return 1, photo_queue(settings, owner_id)
    from admaker.campaign_routes import campaign_pack_configuration
    from admaker.consent import require_ai_consent

    _, queue = campaign_pack_configuration()
    if queue is None:
        raise HTTPException(503, "Campaign generation is not available yet")
    price = settings.get("priceSnapshot", {}).get("credits")
    if type(price) is not int or not 0 < price <= 10000 or confirmed_credits != price:
        raise HTTPException(409, "Confirm the full campaign retry price before generating again")
    try:
        require_ai_consent(owner_id)
    except PermissionError:
        raise HTTPException(403, "Current AI-processing permission is required") from None
    from admaker.campaign_layouts import preflight_campaign_text
    try:
        preflight_campaign_text(settings.get("campaignBrief", {}))
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    return price, queue
