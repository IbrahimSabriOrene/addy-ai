ALTER TABLE app.job_attempts
    ADD COLUMN provider_state text CHECK (provider_state IN ('submitting','submitted','ready','failed','submission_unknown')),
    ADD COLUMN provider_fence integer,
    ADD COLUMN provider_request jsonb,
    ADD COLUMN provider_request_hash text,
    ADD COLUMN operation_name text,
    ADD COLUMN estimated_cost_microusd bigint CHECK (estimated_cost_microusd >= 0),
    ADD COLUMN actual_cost_microusd bigint CHECK (actual_cost_microusd >= 0),
    ADD COLUMN next_poll_at timestamptz,
    ADD COLUMN provider_error text;
CREATE UNIQUE INDEX attempt_operation_name_idx ON app.job_attempts(operation_name) WHERE operation_name IS NOT NULL;
CREATE INDEX attempts_due_poll_idx ON app.job_attempts(next_poll_at) WHERE provider_state IN ('submitted','ready');
ALTER TABLE app.job_attempts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.job_attempts FROM PUBLIC, anon, authenticated;
