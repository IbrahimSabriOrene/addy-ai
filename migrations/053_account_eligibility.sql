CREATE TABLE app.account_eligibility (
    account_id uuid PRIMARY KEY REFERENCES app.accounts(id) ON DELETE CASCADE,
    policy_version text NOT NULL,
    confirmed_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE app.account_eligibility ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.account_eligibility FROM PUBLIC, anon, authenticated;
CREATE TRIGGER eligibility_deletion_guard BEFORE INSERT OR UPDATE ON app.account_eligibility
FOR EACH ROW EXECUTE FUNCTION app.reject_deleted_account_insert('account_id');
