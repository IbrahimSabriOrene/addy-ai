"""Durable, store-transaction-based reconciliation for configured consumable packs."""
import argparse
import hashlib
import json
import os
import uuid

import psycopg


def credit_packs() -> dict[str, int]:
    """The same validated configuration drives the store catalogue and grants."""
    packs = json.loads(os.environ.get("REVENUECAT_CREDIT_PACKS", "{}"))
    if not isinstance(packs, dict) or len(packs) > 100 or any(
        not product or len(product) > 300 or product.strip() != product
        or any(ord(char) < 32 for char in product)
        or type(amount) is not int or not 1 <= amount <= 1_000_000
        for product, amount in packs.items()
    ):
        raise ValueError("Invalid credit pack configuration")
    return packs


def process_revenuecat_event(database_url: str, event_id: str) -> str:
    with psycopg.connect(database_url) as c:
        receipt = c.execute("SELECT payload,outcome FROM app.webhook_events WHERE provider='revenuecat' AND event_id=%s FOR UPDATE", (event_id,)).fetchone()
        if not receipt:
            raise ValueError("Unknown webhook event")
        if receipt[1] in {"granted", "reversed", "ignored_environment"}:
            return receipt[1]
        c.execute("UPDATE app.webhook_events SET attempts=attempts+1 WHERE provider='revenuecat' AND event_id=%s", (event_id,))

        def finish(outcome):
            retry = outcome in {"awaiting_purchase", "awaiting_identity", "configuration_required"}
            c.execute("UPDATE app.webhook_events SET outcome=%s,next_attempt_at=CASE WHEN %s THEN now()+interval '5 minutes' ELSE NULL END WHERE provider='revenuecat' AND event_id=%s", (outcome, retry, event_id))
            return outcome

        event = receipt[0]["event"]
        kind = event.get("type")
        if kind not in {"NON_RENEWING_PURCHASE", "CANCELLATION"}:
            return finish("reconciliation_required")
        if kind == "CANCELLATION" and event.get("cancel_reason") != "CUSTOMER_SUPPORT":
            return finish("reconciliation_required")
        fields = [event.get(name) for name in ("app_id", "store", "environment", "transaction_id", "product_id")]
        if not all(isinstance(value, str) and 0 < len(value) <= 300 for value in fields):
            return finish("reconciliation_required")
        app_id, store, environment, transaction_id, product_id = fields
        if environment not in {"SANDBOX", "PRODUCTION"} or store not in {"APP_STORE", "PLAY_STORE"}:
            return finish("reconciliation_required")
        expected_environment = os.environ.get("REVENUECAT_ENVIRONMENT", "SANDBOX")
        if environment != expected_environment:
            return finish("ignored_environment")
        if app_id != os.environ.get("REVENUECAT_APP_ID"):
            return finish("configuration_required")
        key = hashlib.sha256(json.dumps(fields[:4], separators=(",", ":")).encode()).hexdigest()
        # Serializes the same store transaction across distinct event IDs/accounts.
        c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (key,))
        if c.execute("SELECT 1 FROM app.credit_ledger WHERE event_key IN (%s,%s)", (f"purchase:{transaction_id}", f"refund:{transaction_id}")).fetchone():
            return finish("legacy_reconciliation_required")
        c.execute("INSERT INTO app.purchase_transactions(transaction_key,app_id,store,environment,transaction_id,product_id) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", (key, app_id, store, environment, transaction_id, product_id))
        owner, credits, purchased, refunded, saved_product = c.execute("SELECT account_id,credits,purchased,refunded,product_id FROM app.purchase_transactions WHERE transaction_key=%s FOR UPDATE", (key,)).fetchone()
        if saved_product != product_id:
            return finish("reconciliation_required")
        if kind == "NON_RENEWING_PURCHASE":
            if credits is None:
                try:
                    configured_credits = credit_packs().get(product_id)
                except ValueError:
                    return finish("configuration_required")
                if type(configured_credits) is not int or not 1 <= configured_credits <= 1_000_000:
                    return finish("configuration_required")
                credits = configured_credits
            purchased = True
        else:
            refunded = True
        c.execute("UPDATE app.purchase_transactions SET credits=%s,purchased=%s,refunded=%s WHERE transaction_key=%s", (credits, purchased, refunded, key))
        if not purchased:
            return finish("awaiting_purchase")
        if owner is None:
            aliases = event.get("aliases", [])
            if not isinstance(aliases, list) or len(aliases) > 100:
                return finish("reconciliation_required")
            identities = set()
            for identity in [event.get("app_user_id"), event.get("original_app_user_id"), *aliases]:
                try:
                    identities.add(uuid.UUID(identity))
                except (ValueError, TypeError, AttributeError):
                    pass
            candidates = c.execute("SELECT id FROM app.accounts WHERE id=ANY(%s::uuid[])", (list(identities),)).fetchall()
            if len(candidates) != 1:
                return finish("awaiting_identity" if not candidates else "reconciliation_required")
            owner = candidates[0][0]
            c.execute("UPDATE app.purchase_transactions SET account_id=%s WHERE transaction_key=%s", (owner, key))
        c.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (owner,))
        c.execute("INSERT INTO app.credit_ledger(account_id,delta,event_key,reason) VALUES (%s,%s,%s,'purchase') ON CONFLICT(event_key) DO NOTHING", (owner, credits, f"revenuecat:purchase:{key}"))
        if refunded:
            c.execute("INSERT INTO app.credit_ledger(account_id,delta,event_key,reason) VALUES (%s,%s,%s,'refund') ON CONFLICT(event_key) DO NOTHING", (owner, -credits, f"revenuecat:refund:{key}"))
        return finish("reversed" if refunded else "granted")


def process_pending_billing(database_url: str) -> int:
    with psycopg.connect(database_url) as c:
        events = c.execute("SELECT event_id FROM app.webhook_events WHERE provider='revenuecat' AND outcome IN ('received','awaiting_purchase','awaiting_identity','configuration_required') AND (next_attempt_at IS NULL OR next_attempt_at <= now()) ORDER BY received_at LIMIT 20").fetchall()
    for event_id, in events:
        process_revenuecat_event(database_url, event_id)
    return len(events)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", help="Reprocess a retained event after resolving its configuration or identity")
    args = parser.parse_args()
    url = os.environ["DATABASE_URL"]
    print(process_revenuecat_event(url, args.event) if args.event else process_pending_billing(url))


if __name__ == "__main__":
    main()
