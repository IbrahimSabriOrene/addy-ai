CREATE TABLE app.product_images (
    product_id uuid NOT NULL,
    owner_id uuid NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    asset_key uuid NOT NULL,
    approved_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (product_id, version),
    FOREIGN KEY (owner_id, product_id) REFERENCES app.products(owner_id, id),
    FOREIGN KEY (owner_id, asset_key) REFERENCES app.assets(owner_id, asset_key)
);
ALTER TABLE app.product_images ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.product_images FROM PUBLIC, anon, authenticated;
