-- Account balance/holds and bounded active-run recovery lookups (plan section 5).
SET LOCAL lock_timeout = '5s';
CREATE INDEX credit_ledger_account_idx ON app.credit_ledger(account_id);
CREATE INDEX credit_reservations_account_state_idx ON app.credit_reservations(account_id, state);
CREATE INDEX job_runs_running_lease_idx ON app.job_runs(lease_until, next_work_at)
    WHERE state = 'running';
