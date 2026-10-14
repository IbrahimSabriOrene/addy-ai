ALTER TABLE app.review_files DROP CONSTRAINT review_files_state_check;
ALTER TABLE app.review_files ADD CONSTRAINT review_files_state_check
CHECK (state IN ('pending','processing','ready','verified_absent'));
CREATE TABLE app.review_file_resolutions (
    id uuid PRIMARY KEY,
    account_id uuid NOT NULL,
    file_name text NOT NULL,
    operator text NOT NULL CHECK (length(operator) BETWEEN 1 AND 100),
    evidence text NOT NULL CHECK (length(evidence) BETWEEN 1 AND 500),
    resolved_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
ALTER TABLE app.review_file_resolutions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.review_file_resolutions FROM PUBLIC, anon, authenticated;
