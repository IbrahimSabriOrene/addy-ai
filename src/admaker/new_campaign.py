"""One transactional receipt for creating a campaign and admitting its first pack."""
import hashlib

from fastapi import HTTPException
from psycopg.types.json import Jsonb


def new_campaign_command(connection, payload, subject, key, *, close=False):
    from admaker.api import CampaignRequest, create_campaign_record
    from admaker.campaign_generation import admit_campaign_generation
    from admaker.campaign_routes import campaign_pack_configuration
    from admaker.consent import require_ai_consent

    if not key or len(key) > 200:
        raise HTTPException(422, "valid Idempotency-Key is required")
    digest = hashlib.sha256(payload.model_dump_json(exclude_none=True).encode()).hexdigest()
    if not connection.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (subject.id,)).fetchone():
        raise HTTPException(404, "account not found")
    previous = connection.execute("SELECT request_hash,response FROM app.command_keys WHERE account_id=%s AND route='new-campaign-generate' AND key=%s", (subject.id, key)).fetchone()
    if previous:
        if previous[0] != digest:
            raise HTTPException(409, "idempotency key payload mismatch")
        return previous[1]
    if close:
        result = {"state": "cancelled"}
    else:
        price, queue = campaign_pack_configuration()
        if price is None:
            raise HTTPException(503, "Campaign generation is not available yet")
        try:
            require_ai_consent(str(subject.id))
        except PermissionError:
            raise HTTPException(403, "AI consent is required") from None
        # Separate internal namespaces from either public API's command keys.
        internal_key = "newpack:" + hashlib.sha256(key.encode()).hexdigest()
        brief = CampaignRequest.model_validate(payload.model_dump(by_alias=True, exclude={"confirmed_credits"}))
        campaign = create_campaign_record(connection, brief, subject, internal_key)
        try:
            result = admit_campaign_generation(connection, campaign["id"], subject.id, 1, internal_key,
                price_credits=price, confirmed_credits=payload.confirmed_credits, queue=queue)
        except LookupError as error:
            raise HTTPException(404, str(error)) from None
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
    connection.execute("INSERT INTO app.command_keys(account_id,route,key,request_hash,response) VALUES (%s,'new-campaign-generate',%s,%s,%s)", (subject.id, key, digest, Jsonb(result)))
    return result
