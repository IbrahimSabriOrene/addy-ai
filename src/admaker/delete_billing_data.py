"""Minimize linked legacy receipts without changing financial replay evidence."""
import uuid

import psycopg
from psycopg.types.json import Jsonb

from admaker.billing_payload import retained_revenuecat_payload


def minimize_deleted_account_billing(database_url, account_id):
    account_id = uuid.UUID(str(account_id))
    with psycopg.connect(database_url) as c:
        phase = c.execute("SELECT billing_minimized_at FROM app.account_deletions WHERE account_id=%s FOR UPDATE", (account_id,)).fetchone()
        if phase is None:
            raise ValueError("An admitted account deletion request is required")
        if phase[0] is not None:
            return
        rows = c.execute("""SELECT w.event_id,w.payload FROM app.webhook_events w
            WHERE w.provider='revenuecat' AND (
                w.payload->'event'->>'app_user_id'=%(owner)s
                OR w.payload->'event'->>'original_app_user_id'=%(owner)s
                OR w.payload->'event'->'aliases' ? %(owner)s
                OR w.payload->'event'->'transferred_from' ? %(owner)s
                OR w.payload->'event'->'transferred_to' ? %(owner)s
                OR EXISTS (SELECT 1 FROM app.purchase_transactions p
                    WHERE p.account_id=%(owner)s::uuid
                    AND p.app_id=w.payload->'event'->>'app_id'
                    AND p.store=w.payload->'event'->>'store'
                    AND p.environment=w.payload->'event'->>'environment'
                    AND p.transaction_id=w.payload->'event'->>'transaction_id'))
            ORDER BY w.event_id FOR UPDATE OF w""", {"owner": str(account_id)}).fetchall()
        for event_id, payload in rows:
            c.execute("UPDATE app.webhook_events SET payload=%s WHERE provider='revenuecat' AND event_id=%s", (Jsonb(retained_revenuecat_payload(payload)), event_id))
        c.execute("UPDATE app.account_deletions SET billing_minimized_at=clock_timestamp() WHERE account_id=%s", (account_id,))
