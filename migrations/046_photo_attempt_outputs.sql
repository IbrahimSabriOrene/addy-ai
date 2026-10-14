CREATE TABLE app.photo_attempt_outputs (
    attempt_id uuid PRIMARY KEY REFERENCES app.job_attempts(id) ON DELETE CASCADE,
    data bytea NOT NULL CHECK (octet_length(data) BETWEEN 1 AND 10485760),
    mime_type text NOT NULL CHECK (mime_type IN ('image/png','image/jpeg','image/webp')),
    checksum text NOT NULL CHECK (checksum ~ '^[a-f0-9]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
ALTER TABLE app.photo_attempt_outputs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.photo_attempt_outputs FROM PUBLIC, anon, authenticated;
