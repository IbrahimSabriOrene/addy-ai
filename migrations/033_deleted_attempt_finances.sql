CREATE TABLE app.deleted_attempt_finances (
    attempt_id uuid PRIMARY KEY,
    account_id uuid NOT NULL,
    reservation_id uuid NOT NULL,
    credits integer NOT NULL,
    reservation_state text NOT NULL,
    estimated_cost_microusd bigint,
    actual_cost_microusd bigint,
    provider_state text,
    operation_name text,
    retained_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
ALTER TABLE app.deleted_attempt_finances ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON app.deleted_attempt_finances FROM PUBLIC, anon, authenticated;

CREATE FUNCTION app.retain_deleted_attempt_finances() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, app AS $$
BEGIN
    INSERT INTO app.deleted_attempt_finances(attempt_id,account_id,reservation_id,credits,reservation_state,
        estimated_cost_microusd,actual_cost_microusd,provider_state,operation_name)
    SELECT OLD.id,c.account_id,c.id,c.amount,c.state,OLD.estimated_cost_microusd,
        OLD.actual_cost_microusd,OLD.provider_state,OLD.operation_name
    FROM app.credit_reservations c JOIN app.account_deletions d ON d.account_id=c.account_id
    WHERE c.id=OLD.reservation_id
    ON CONFLICT (attempt_id) DO NOTHING;
    RETURN OLD;
END;
$$;
REVOKE ALL ON FUNCTION app.retain_deleted_attempt_finances() FROM PUBLIC;
CREATE TRIGGER deleted_attempt_finances BEFORE DELETE ON app.job_attempts
FOR EACH ROW EXECUTE FUNCTION app.retain_deleted_attempt_finances();
