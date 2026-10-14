CREATE TABLE app.job_attempts (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES app.job_runs(id),
    reservation_id uuid NOT NULL REFERENCES app.credit_reservations(id),
    sequence integer NOT NULL,
    state text NOT NULL CHECK (state IN ('running', 'delivered', 'failed')),
    request_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE (run_id, sequence),
    UNIQUE (reservation_id)
);

CREATE INDEX job_attempts_run_idx ON app.job_attempts (run_id, sequence);
