ALTER TABLE app.deleted_attempt_finances
    ADD COLUMN reconciled_at timestamptz,
    ADD COLUMN reconciled_by text,
    ADD COLUMN reconciliation_evidence text,
    ADD CONSTRAINT deleted_provider_resolution_complete CHECK (
        (reconciled_at IS NULL AND reconciled_by IS NULL AND reconciliation_evidence IS NULL)
        OR (reconciled_at IS NOT NULL AND reconciled_by IS NOT NULL AND reconciliation_evidence IS NOT NULL
            AND provider_state IN ('ready','failed') AND actual_cost_microusd IS NOT NULL)
    );
