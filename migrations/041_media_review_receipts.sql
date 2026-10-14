ALTER TABLE app.media_review_budget
    ADD COLUMN request_hash text CHECK (request_hash ~ '^[a-f0-9]{64}$'),
    ADD COLUMN state text NOT NULL DEFAULT 'unconfirmed' CHECK (state IN ('unconfirmed','finished','failed')),
    ADD COLUMN verdict jsonb,
    ADD COLUMN completed_at timestamptz;
CREATE UNIQUE INDEX media_review_request ON app.media_review_budget(run_id,request_hash)
    WHERE state IN ('unconfirmed','finished') AND request_hash IS NOT NULL;
CREATE INDEX media_review_pending ON app.media_review_budget(state) WHERE state='unconfirmed';
