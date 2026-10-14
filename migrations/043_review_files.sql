CREATE TABLE app.review_files (
    account_id uuid NOT NULL REFERENCES app.accounts(id),
    checksum text NOT NULL CHECK (checksum ~ '^[a-f0-9]{64}$'),
    mime_type text NOT NULL CHECK (mime_type IN ('image/png','image/jpeg','image/webp','video/mp4')),
    size_bytes bigint NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 134217728),
    file_name text NOT NULL UNIQUE CHECK (file_name ~ '^files/addy-[a-f0-9]{32}$'),
    credential_hash text NOT NULL CHECK (credential_hash ~ '^[a-f0-9]{64}$'),
    state text NOT NULL CHECK (state IN ('pending','processing','ready')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (account_id,checksum,mime_type)
);
ALTER TABLE app.review_files ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.review_files FROM PUBLIC, anon, authenticated;
CREATE TRIGGER review_file_deletion_insert BEFORE INSERT ON app.review_files
FOR EACH ROW EXECUTE FUNCTION app.reject_deleted_account_insert('account_id');
