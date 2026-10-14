ALTER TABLE app.media_review_budget
    ADD COLUMN resolution_id uuid UNIQUE,
    ADD COLUMN resolved_by text,
    ADD COLUMN resolution_evidence text,
    ADD CONSTRAINT media_review_resolution_fields CHECK (
        (resolution_id IS NULL AND resolved_by IS NULL AND resolution_evidence IS NULL)
        OR (resolution_id IS NOT NULL AND length(resolved_by) BETWEEN 1 AND 100
            AND length(resolution_evidence) BETWEEN 1 AND 500
            AND resolved_by IS NOT NULL AND resolution_evidence IS NOT NULL)
    );
