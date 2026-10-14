ALTER TABLE app.jobs ADD COLUMN version bigint NOT NULL DEFAULT 1 CHECK (version > 0);
CREATE FUNCTION app.bump_job_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.version := OLD.version;
    IF NEW IS DISTINCT FROM OLD THEN
        NEW.version := OLD.version + 1;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER jobs_version BEFORE UPDATE ON app.jobs FOR EACH ROW EXECUTE FUNCTION app.bump_job_version();
