CREATE TABLE app.campaign_generations (
    campaign_id uuid NOT NULL REFERENCES app.campaigns(id),
    campaign_version integer NOT NULL CHECK (campaign_version > 0),
    job_id uuid NOT NULL UNIQUE REFERENCES app.jobs(id),
    price_credits integer NOT NULL CHECK (price_credits > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (campaign_id, campaign_version)
);
ALTER TABLE app.campaign_generations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.campaign_generations FROM PUBLIC, anon, authenticated;
