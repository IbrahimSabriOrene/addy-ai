CREATE TABLE app.campaigns (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    product_id uuid NOT NULL,
    image_version integer NOT NULL,
    brief jsonb NOT NULL,
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (owner_id, product_id) REFERENCES app.products(owner_id,id),
    FOREIGN KEY (product_id,image_version) REFERENCES app.product_images(product_id,version)
);
CREATE INDEX campaigns_product_created_idx ON app.campaigns(owner_id,product_id,created_at DESC);
ALTER TABLE app.campaigns ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.campaigns FROM PUBLIC, anon, authenticated;
