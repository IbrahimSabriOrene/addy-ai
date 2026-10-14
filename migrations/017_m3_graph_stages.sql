ALTER TABLE app.job_runs ADD COLUMN graph_version text NOT NULL DEFAULT 'worker-fixture-v1';

CREATE TABLE app.job_stages (
    run_id uuid NOT NULL REFERENCES app.job_runs(id) ON DELETE CASCADE,
    stage_key text NOT NULL,
    request_hash text NOT NULL,
    result jsonb NOT NULL,
    fence integer NOT NULL,
    completed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, stage_key)
);
ALTER TABLE app.job_stages ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.job_stages FROM PUBLIC, anon, authenticated;
