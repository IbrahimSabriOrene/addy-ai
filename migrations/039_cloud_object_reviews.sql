ALTER TABLE app.cloud_objects DROP CONSTRAINT cloud_objects_state_check;
ALTER TABLE app.cloud_objects ADD CONSTRAINT cloud_objects_state_check CHECK (state IN ('pending','ready','verified_absent'));
CREATE TABLE app.cloud_object_reviews (
    id uuid PRIMARY KEY,
    account_id uuid NOT NULL,
    local_key text NOT NULL,
    object_key text NOT NULL,
    checksum text NOT NULL,
    operator text NOT NULL,
    decision text NOT NULL CHECK (decision IN ('verified_present','verified_absent')),
    evidence text NOT NULL,
    resolved_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
ALTER TABLE app.cloud_object_reviews ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.cloud_object_reviews FROM PUBLIC, anon, authenticated;
