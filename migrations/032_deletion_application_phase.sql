ALTER TABLE app.account_deletions ADD COLUMN application_deleted_at timestamptz;
CREATE TRIGGER consent_deletion_insert BEFORE INSERT ON app.ai_consent
FOR EACH ROW EXECUTE FUNCTION app.reject_deleted_account_insert('account_id');
CREATE TRIGGER command_deletion_insert BEFORE INSERT ON app.command_keys
FOR EACH ROW EXECUTE FUNCTION app.reject_deleted_account_insert('account_id');
