-- Preserve explicit financial provenance without rewriting historical event keys.
SET LOCAL lock_timeout = '5s';
ALTER TABLE app.credit_ledger
    ADD COLUMN reason text NOT NULL DEFAULT 'legacy',
    ADD COLUMN reservation_id uuid;
-- Snapshot reference intentionally survives application/hold deletion.
CREATE UNIQUE INDEX credit_ledger_reservation_idx ON app.credit_ledger(reservation_id)
    WHERE reservation_id IS NOT NULL;
