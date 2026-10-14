-- Keep every hold positive and bound to the job owner's account.
SET LOCAL lock_timeout = '5s';
ALTER TABLE app.credit_reservations
    ADD CONSTRAINT credit_reservations_positive_amount CHECK (amount > 0),
    ADD CONSTRAINT credit_reservations_job_owner_fkey
        FOREIGN KEY (account_id, job_id) REFERENCES app.jobs(owner_id, id);
