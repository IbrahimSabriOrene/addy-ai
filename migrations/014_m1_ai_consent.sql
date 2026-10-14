CREATE TABLE app.ai_consent (
    account_id uuid PRIMARY KEY REFERENCES app.accounts(id),
    disclosure_version text NOT NULL,
    granted boolean NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE app.ai_consent ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.ai_consent FROM PUBLIC, anon, authenticated;
