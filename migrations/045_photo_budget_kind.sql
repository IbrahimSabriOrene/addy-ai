ALTER TABLE app.provider_budget_holds ADD COLUMN media_kind text NOT NULL DEFAULT 'video'
CHECK (media_kind IN ('video','photo'));
