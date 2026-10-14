"""Public copy is fixed locally, never taken from provider or stored error text."""
PACK_INCOMPLETE = {
    "code": "campaign_pack_incomplete",
    "message": "Some campaign outputs could not be prepared. Your credits have not been spent and remain reserved while this generation is reviewed. Contact support for help.",
}


def campaign_failure(state, result):
    if state == "failed" and result.get("failure", {}).get("code") == "media_review_pending":
        return {"code": "media_review_pending", "message": "Your media is saved, but its content review could not be completed. Credits remain reserved and no new generation will start automatically. Contact support for help."}
    return dict(PACK_INCOMPLETE) if state == "failed" and result.get("failure", {}).get("code") == PACK_INCOMPLETE["code"] else None
