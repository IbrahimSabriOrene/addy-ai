"""Keep reconciliation fields, not arbitrary subscriber attributes or metadata."""


def retained_revenuecat_payload(payload):
    event = payload["event"]
    fields = (
        "id", "type", "cancel_reason", "app_id", "store", "environment",
        "transaction_id", "original_transaction_id", "product_id",
        "app_user_id", "original_app_user_id", "event_timestamp_ms",
        "purchased_at_ms", "price", "currency", "price_in_purchased_currency",
    )
    retained = {key: value if not isinstance(value, (dict, list)) else None
                for key in fields if key in event for value in [event[key]]}
    # Preserve identity/transfer ambiguity for review; never pick an arbitrary owner.
    for key in ("aliases", "transferred_from", "transferred_to"):
        if key in event:
            value = event[key]
            retained[key] = value if isinstance(value, list) and len(value) <= 100 and all(isinstance(item, str) for item in value) else None
    return {"event": retained}
