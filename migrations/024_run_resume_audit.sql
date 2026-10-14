CREATE TABLE app.run_resume_audit (
  run_id uuid NOT NULL REFERENCES app.job_runs(id) ON DELETE CASCADE,
  fence bigint NOT NULL,
  operator text NOT NULL,
  reason text NOT NULL,
  worker_mode text NOT NULL CHECK (worker_mode IN ('fixture','provider')),
  queue_name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (run_id,fence)
);
ALTER TABLE app.run_resume_audit ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.run_resume_audit FROM PUBLIC, anon, authenticated;
