CREATE TABLE app.accounts (
    id uuid PRIMARY KEY,
    email text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.assets (
    asset_key uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES app.accounts(id),
    storage_key text NOT NULL UNIQUE,
    mime_type text NOT NULL,
    size_bytes integer,
    checksum text,
    verification_state text NOT NULL DEFAULT 'pending' CHECK (verification_state IN ('pending', 'verified')),
    created_at timestamptz NOT NULL DEFAULT now(),
    verified_at timestamptz
);

CREATE INDEX assets_owner_created_idx ON app.assets (owner_id, created_at DESC);
