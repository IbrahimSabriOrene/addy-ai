CREATE TABLE app.brand_profiles (
    account_id uuid PRIMARY KEY REFERENCES app.accounts(id) ON DELETE CASCADE,
    profile jsonb NOT NULL,
    version integer NOT NULL DEFAULT 1 CHECK (version > 0)
);
ALTER TABLE app.brand_profiles ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.brand_profiles FROM PUBLIC, anon, authenticated;
CREATE TRIGGER brand_deletion_guard BEFORE INSERT OR UPDATE ON app.brand_profiles
FOR EACH ROW EXECUTE FUNCTION app.reject_deleted_account_insert('account_id');
