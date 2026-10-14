ALTER TABLE app.webhook_events ADD COLUMN attempts integer NOT NULL DEFAULT 0;
ALTER TABLE app.webhook_events ADD COLUMN next_attempt_at timestamptz;
CREATE INDEX webhook_reconciliation_due ON app.webhook_events(outcome,next_attempt_at,received_at);
CREATE TABLE app.purchase_transactions (
    transaction_key text PRIMARY KEY,
    app_id text NOT NULL,
    store text NOT NULL,
    environment text NOT NULL,
    transaction_id text NOT NULL,
    product_id text NOT NULL,
    account_id uuid REFERENCES app.accounts(id),
    credits integer CHECK (credits > 0),
    purchased boolean NOT NULL DEFAULT false,
    refunded boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(app_id,store,environment,transaction_id)
);
ALTER TABLE app.purchase_transactions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.purchase_transactions FROM PUBLIC, anon, authenticated;
