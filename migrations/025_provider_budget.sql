CREATE TABLE app.provider_budget_holds (
  attempt_id uuid PRIMARY KEY,
  amount_microusd bigint NOT NULL CHECK (amount_microusd > 0),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
-- Keep cost commitments if application attempts are later removed.
ALTER TABLE app.provider_budget_holds ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.provider_budget_holds FROM PUBLIC, anon, authenticated;
