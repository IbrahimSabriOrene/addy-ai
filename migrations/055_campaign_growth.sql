CREATE TABLE app.growth_preferences (
 account_id uuid PRIMARY KEY REFERENCES app.accounts(id) ON DELETE CASCADE,
 preferences jsonb NOT NULL, version integer NOT NULL DEFAULT 1,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE app.campaign_outcomes (
 campaign_id uuid PRIMARY KEY REFERENCES app.campaigns(id) ON DELETE CASCADE,
 account_id uuid NOT NULL REFERENCES app.accounts(id) ON DELETE CASCADE,
 result jsonb NOT NULL, version integer NOT NULL DEFAULT 1
);
CREATE TABLE app.growth_events (
 account_id uuid NOT NULL REFERENCES app.accounts(id) ON DELETE CASCADE,
 day date NOT NULL DEFAULT CURRENT_DATE, name text NOT NULL,
 PRIMARY KEY(account_id,day,name)
);
CREATE TABLE app.push_devices (
 token text PRIMARY KEY, account_id uuid NOT NULL REFERENCES app.accounts(id) ON DELETE CASCADE,
 expires_at timestamptz NOT NULL
);
CREATE INDEX push_devices_owner ON app.push_devices(account_id);
CREATE TABLE app.growth_notifications (
 id uuid PRIMARY KEY, account_id uuid NOT NULL REFERENCES app.accounts(id) ON DELETE CASCADE,
 event_key text NOT NULL, kind text NOT NULL CHECK(kind IN ('completion','weekly')),
 created_at timestamptz NOT NULL DEFAULT now(), read_at timestamptz,
 push_attempted_at timestamptz, push_state text NOT NULL DEFAULT 'pending',
 ticket_id text, UNIQUE(account_id,event_key)
);
CREATE INDEX growth_notifications_owner ON app.growth_notifications(account_id,created_at DESC);
DO $$ DECLARE tbl text; BEGIN
 FOREACH tbl IN ARRAY ARRAY['growth_preferences','campaign_outcomes','growth_events','push_devices','growth_notifications'] LOOP
  EXECUTE format('ALTER TABLE app.%I ENABLE ROW LEVEL SECURITY',tbl);
  EXECUTE format('REVOKE ALL ON app.%I FROM PUBLIC, anon, authenticated',tbl);
  EXECUTE format('CREATE TRIGGER growth_deletion_guard BEFORE INSERT OR UPDATE ON app.%I FOR EACH ROW EXECUTE FUNCTION app.reject_deleted_account_insert(''account_id'')',tbl);
 END LOOP;
END $$;
