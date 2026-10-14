ALTER TABLE app.webhook_events ADD COLUMN outcome text NOT NULL DEFAULT 'received';
