CREATE TABLE app.jobs (id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES app.accounts(id), source_asset_id uuid NOT NULL REFERENCES app.assets(asset_key), state text NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX jobs_owner_created_idx ON app.jobs (owner_id, created_at DESC);
CREATE TABLE app.credit_ledger (id bigserial PRIMARY KEY, account_id uuid NOT NULL REFERENCES app.accounts(id), delta integer NOT NULL, event_key text NOT NULL UNIQUE, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE app.credit_reservations (id uuid PRIMARY KEY, account_id uuid NOT NULL REFERENCES app.accounts(id), job_id uuid NOT NULL REFERENCES app.jobs(id), amount integer NOT NULL, state text NOT NULL CHECK (state IN ('held','consumed','released')), UNIQUE(job_id));
CREATE TABLE app.command_keys (account_id uuid NOT NULL REFERENCES app.accounts(id), route text NOT NULL, key text NOT NULL, request_hash text NOT NULL, response jsonb NOT NULL, PRIMARY KEY (account_id, route, key));
SELECT pgmq.create('commands');
