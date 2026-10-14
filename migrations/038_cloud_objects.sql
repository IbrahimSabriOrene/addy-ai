CREATE TABLE app.cloud_objects (
    account_id uuid NOT NULL REFERENCES app.accounts(id),
    local_key text NOT NULL,
    object_key text NOT NULL UNIQUE,
    origin text NOT NULL,
    bucket text NOT NULL,
    checksum text NOT NULL,
    size_bytes bigint NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 134217728),
    content_type text NOT NULL,
    state text NOT NULL CHECK (state IN ('pending','ready')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(account_id,local_key)
);
ALTER TABLE app.cloud_objects ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.cloud_objects FROM PUBLIC, anon, authenticated;
CREATE TRIGGER cloud_object_deletion_insert BEFORE INSERT ON app.cloud_objects
FOR EACH ROW EXECUTE FUNCTION app.reject_deleted_account_insert('account_id');
