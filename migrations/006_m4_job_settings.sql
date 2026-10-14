ALTER TABLE app.jobs ADD COLUMN settings jsonb NOT NULL DEFAULT '{}'::jsonb;
