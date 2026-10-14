CREATE TABLE app.submission_reviews (
    attempt_id uuid PRIMARY KEY REFERENCES app.job_attempts(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    review_due_at timestamptz NOT NULL DEFAULT clock_timestamp() + interval '24 hours',
    resolved_at timestamptz,
    operator text,
    decision text CHECK (decision IN ('verified_no_output', 'goodwill_release')),
    reason text,
    actual_cost_microusd bigint CHECK (actual_cost_microusd >= 0),
    CHECK ((resolved_at IS NULL AND operator IS NULL AND decision IS NULL AND reason IS NULL)
        OR (resolved_at IS NOT NULL AND operator IS NOT NULL AND decision IS NOT NULL AND reason IS NOT NULL))
);
CREATE INDEX submission_reviews_due_idx ON app.submission_reviews(review_due_at) WHERE resolved_at IS NULL;
ALTER TABLE app.submission_reviews ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.submission_reviews FROM PUBLIC, anon, authenticated;
INSERT INTO app.submission_reviews(attempt_id)
SELECT a.id FROM app.job_attempts a JOIN app.job_runs r ON r.id=a.run_id
WHERE a.provider_state='submission_unknown' AND r.state='review_required';
