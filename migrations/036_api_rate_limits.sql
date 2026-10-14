CREATE TABLE app.api_rate_limits (
    account_id uuid PRIMARY KEY,
    window_started_at timestamptz NOT NULL,
    requests integer NOT NULL CHECK (requests > 0)
);
ALTER TABLE app.api_rate_limits ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.api_rate_limits FROM PUBLIC, anon, authenticated;
CREATE TRIGGER api_rate_deletion_insert BEFORE INSERT ON app.api_rate_limits
FOR EACH ROW EXECUTE FUNCTION app.reject_deleted_account_insert('account_id');
