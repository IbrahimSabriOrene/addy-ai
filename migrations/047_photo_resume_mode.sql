ALTER TABLE app.run_resume_audit DROP CONSTRAINT run_resume_audit_worker_mode_check;
ALTER TABLE app.run_resume_audit ADD CONSTRAINT run_resume_audit_worker_mode_check
  CHECK (worker_mode IN ('fixture', 'provider', 'photo'));
