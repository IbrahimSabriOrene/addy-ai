ALTER TABLE app.jobs ADD CONSTRAINT jobs_owner_key UNIQUE (owner_id, id);
CREATE TABLE app.result_reports (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    job_id uuid NOT NULL,
    run_id uuid,
    result_snapshot jsonb NOT NULL,
    reason text NOT NULL CHECK (reason IN ('unsafe_content','product_accuracy','rights','other')),
    details text NOT NULL DEFAULT '' CHECK (length(details) <= 1000),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','reviewing','resolved')),
    assignee text CHECK (length(assignee) BETWEEN 1 AND 100),
    resolution text NOT NULL DEFAULT '' CHECK (length(resolution) <= 1000),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (owner_id, job_id) REFERENCES app.jobs(owner_id,id),
    CHECK (status = 'open' OR assignee IS NOT NULL),
    CHECK (status <> 'resolved' OR length(btrim(resolution)) > 0)
);
CREATE INDEX result_reports_queue ON app.result_reports(status,created_at,id);
CREATE INDEX result_reports_owner ON app.result_reports(owner_id,job_id,created_at DESC);
ALTER TABLE app.result_reports ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.result_reports FROM PUBLIC, anon, authenticated;
