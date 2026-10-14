ALTER TABLE app.assets ADD CONSTRAINT assets_owner_key UNIQUE (owner_id, asset_key);
CREATE TABLE app.products (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES app.accounts(id),
    name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 100),
    description text NOT NULL DEFAULT '' CHECK (length(description) <= 1000),
    source_asset_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,
    FOREIGN KEY (owner_id, source_asset_id) REFERENCES app.assets(owner_id, asset_key),
    UNIQUE (owner_id, id)
);
CREATE INDEX products_owner_created_idx ON app.products(owner_id, created_at DESC, id DESC)
    WHERE deleted_at IS NULL;
ALTER TABLE app.products ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.products FROM PUBLIC, anon, authenticated;
