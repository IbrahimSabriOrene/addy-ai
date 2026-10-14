CREATE TABLE app.campaign_operating_costs (
 campaign_id uuid PRIMARY KEY REFERENCES app.campaigns(id) ON DELETE CASCADE,
 account_id uuid NOT NULL REFERENCES app.accounts(id) ON DELETE CASCADE,
 storage_microusd bigint CHECK(storage_microusd>=0),
 support_microusd bigint CHECK(support_microusd>=0),
 payment_fees_microusd bigint CHECK(payment_fees_microusd>=0),
 recorded_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE app.campaign_operating_costs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.campaign_operating_costs FROM PUBLIC, anon, authenticated;
CREATE TRIGGER cost_deletion_guard BEFORE INSERT OR UPDATE ON app.campaign_operating_costs
FOR EACH ROW EXECUTE FUNCTION app.reject_deleted_account_insert('account_id');
