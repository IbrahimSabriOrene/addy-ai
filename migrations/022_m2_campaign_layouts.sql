CREATE TABLE app.campaign_layouts (
    campaign_id uuid NOT NULL REFERENCES app.campaigns(id) ON DELETE CASCADE,
    version integer NOT NULL,
    manifest jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (campaign_id,version)
);
ALTER TABLE app.campaign_layouts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.campaign_layouts FROM PUBLIC, anon, authenticated;
