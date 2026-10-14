"""Operator entry of allocated costs; values are micro-USD (1 USD = 1,000,000)."""
import argparse
import os
import uuid
import psycopg


def record_costs(database_url, campaign, *, storage=None, support=None, payment_fees=None):
    values = (storage, support, payment_fees)
    if not any(value is not None for value in values) or any(value is not None and (type(value) is not int or not 0 <= value <= 10**12) for value in values):
        raise ValueError("Supply at least one non-negative integer cost, at most 1,000,000 USD")
    with psycopg.connect(database_url) as c:
        row = c.execute("SELECT owner_id FROM app.campaigns WHERE id=%s", (campaign,)).fetchone()
        if not row:
            raise ValueError("Campaign not found")
        from admaker.growth import lock_account
        lock_account(c, row[0])
        c.execute("INSERT INTO app.campaign_operating_costs(campaign_id,account_id,storage_microusd,support_microusd,payment_fees_microusd) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(campaign_id) DO UPDATE SET storage_microusd=COALESCE(EXCLUDED.storage_microusd,app.campaign_operating_costs.storage_microusd),support_microusd=COALESCE(EXCLUDED.support_microusd,app.campaign_operating_costs.support_microusd),payment_fees_microusd=COALESCE(EXCLUDED.payment_fees_microusd,app.campaign_operating_costs.payment_fees_microusd),recorded_at=now()", (campaign, row[0], *values))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=uuid.UUID)
    parser.add_argument("--storage", type=int)
    parser.add_argument("--support", type=int)
    parser.add_argument("--payment-fees", type=int)
    args = parser.parse_args()
    record_costs(os.environ["DATABASE_URL"], args.campaign, storage=args.storage, support=args.support, payment_fees=args.payment_fees)
