ALTER TABLE app.account_deletions
    ADD COLUMN attempts integer NOT NULL DEFAULT 0,
    ADD COLUMN next_attempt_at timestamptz,
    ADD COLUMN last_outcome text;
CREATE INDEX account_deletion_due ON app.account_deletions(next_attempt_at,requested_at)
    WHERE state='requested' AND application_deleted_at IS NULL;
