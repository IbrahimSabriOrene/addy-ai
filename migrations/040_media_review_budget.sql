CREATE TABLE app.media_review_budget (
    id uuid PRIMARY KEY,
    run_id uuid REFERENCES app.job_runs(id) ON DELETE SET NULL,
    amount_microusd bigint NOT NULL CHECK (amount_microusd > 0 AND amount_microusd <= 1000000000),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX media_review_budget_day ON app.media_review_budget(created_at);
CREATE INDEX media_review_budget_run ON app.media_review_budget(run_id);
ALTER TABLE app.media_review_budget ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.media_review_budget FROM PUBLIC, anon, authenticated;
