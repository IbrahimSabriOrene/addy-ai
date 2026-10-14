CREATE TABLE app.job_runs (id uuid PRIMARY KEY, job_id uuid NOT NULL REFERENCES app.jobs(id), sequence integer NOT NULL, thread_id text NOT NULL UNIQUE, state text NOT NULL, lease_owner text, lease_until timestamptz, fence integer NOT NULL DEFAULT 0, next_work_at timestamptz, UNIQUE(job_id, sequence));
ALTER TABLE app.jobs ADD COLUMN active_run_id uuid REFERENCES app.job_runs(id);
