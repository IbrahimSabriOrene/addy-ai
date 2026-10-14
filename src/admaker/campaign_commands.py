"""Close only unaccepted Generate commands, serializing against job admission."""
import hashlib
import json

from psycopg.types.json import Jsonb


def close_campaign_command(cursor, campaign_id, owner_id, version, credits, key):
    if not isinstance(key, str) or not 1 <= len(key) <= 200:
        raise ValueError("Valid command key required")
    if type(version) is not int or version < 1 or type(credits) is not int or not 0 < credits <= 10000:
        raise ValueError("Valid campaign version and confirmed credits required")
    request_hash = hashlib.sha256(json.dumps([str(campaign_id), version, credits], separators=(",", ":")).encode()).hexdigest()
    if not cursor.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (owner_id,)).fetchone():
        raise LookupError("Account not found")
    previous = cursor.execute("SELECT request_hash,response FROM app.command_keys WHERE account_id=%s AND route='campaign-generate' AND key=%s", (owner_id, key)).fetchone()
    if previous:
        if previous[0] != request_hash:
            raise ValueError("Command key payload mismatch")
        return previous[1]
    if not cursor.execute("SELECT id FROM app.campaigns WHERE id=%s AND owner_id=%s", (campaign_id, owner_id)).fetchone():
        raise LookupError("Campaign not found")
    response = {"state": "cancelled", "campaignId": str(campaign_id), "campaignVersion": version}
    cursor.execute("INSERT INTO app.command_keys(account_id,route,key,request_hash,response) VALUES (%s,'campaign-generate',%s,%s,%s)", (owner_id, key, request_hash, Jsonb(response)))
    return response
