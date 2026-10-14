CREATE TABLE app.job_events (
    job_id uuid NOT NULL REFERENCES app.jobs(id) ON DELETE CASCADE,
    run_id uuid REFERENCES app.job_runs(id) ON DELETE CASCADE,
    event_key text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    detail jsonb NOT NULL,
    PRIMARY KEY (job_id, event_key)
);
CREATE INDEX job_events_run_time_idx ON app.job_events(run_id, occurred_at);
ALTER TABLE app.job_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.job_events FROM PUBLIC, anon, authenticated;

CREATE FUNCTION app.record_job_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.state IS NOT DISTINCT FROM OLD.state THEN
            RETURN NEW;
        END IF;
    END IF;
    INSERT INTO app.job_events(job_id,run_id,event_key,detail)
    VALUES (NEW.id,NEW.active_run_id,'state:' || NEW.version,
        jsonb_build_object('kind','state','state',NEW.state,'version',NEW.version))
    ON CONFLICT DO NOTHING;
    RETURN NEW;
END;
$$;
CREATE TRIGGER jobs_record_transition AFTER INSERT OR UPDATE OF state ON app.jobs
    FOR EACH ROW EXECUTE FUNCTION app.record_job_transition();

CREATE FUNCTION app.record_job_stage() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO app.job_events(job_id,run_id,event_key,detail)
    SELECT job_id,NEW.run_id,'stage:' || NEW.run_id || ':' || NEW.stage_key,
        jsonb_build_object('kind','stage_recorded','stage',NEW.stage_key)
    FROM app.job_runs WHERE id=NEW.run_id
    ON CONFLICT DO NOTHING;
    RETURN NEW;
END;
$$;
CREATE TRIGGER job_stages_record_event AFTER INSERT ON app.job_stages
    FOR EACH ROW EXECUTE FUNCTION app.record_job_stage();

REVOKE ALL ON FUNCTION app.record_job_transition() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION app.record_job_stage() FROM PUBLIC, anon, authenticated;
