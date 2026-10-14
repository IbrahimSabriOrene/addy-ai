-- Retained tombstone prevents an old identity/token recreating a deleted account.
CREATE TABLE app.account_deletions (
    account_id uuid PRIMARY KEY,
    state text NOT NULL DEFAULT 'requested' CHECK (state IN ('requested','completed')),
    requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz
);
ALTER TABLE app.account_deletions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.account_deletions FROM PUBLIC, anon, authenticated;
