ALTER TABLE app.account_deletions ADD COLUMN billing_minimized_at timestamptz;
DROP INDEX app.account_deletion_due;
CREATE INDEX account_deletion_due ON app.account_deletions(next_attempt_at,requested_at)
    WHERE state='requested' AND (application_deleted_at IS NULL OR billing_minimized_at IS NULL);
