-- Private frozen creative instructions; legacy drafts have no chosen style.
ALTER TABLE app.campaigns ADD COLUMN IF NOT EXISTS style_snapshot jsonb;
