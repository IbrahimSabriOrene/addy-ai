CREATE TABLE app.campaign_review_audit (
    run_id uuid NOT NULL REFERENCES app.job_runs(id) ON DELETE CASCADE,
    fence bigint NOT NULL,
    operator text NOT NULL,
    reason text NOT NULL,
    decision text NOT NULL CHECK (decision IN ('resume','release')),
    queue_name text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (run_id,fence)
);
ALTER TABLE app.campaign_review_audit ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.campaign_review_audit FROM PUBLIC, anon, authenticated;
