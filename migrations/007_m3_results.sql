ALTER TABLE app.jobs ADD COLUMN result jsonb NOT NULL DEFAULT '{}'::jsonb;
