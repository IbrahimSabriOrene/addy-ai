-- Serialize new owned records with deletion admission, including requests that
-- authenticated before cutoff. Existing financial records remain untouched.
CREATE FUNCTION app.reject_deleted_account_insert() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, app AS $$
DECLARE owner uuid;
BEGIN
    owner := (to_jsonb(NEW)->>TG_ARGV[0])::uuid;
    PERFORM id FROM app.accounts WHERE id=owner FOR KEY SHARE;
    IF EXISTS (SELECT 1 FROM app.account_deletions WHERE account_id=owner) THEN
        RAISE EXCEPTION 'Account deletion has been requested'
            USING ERRCODE='23514', CONSTRAINT='account_deletion_requested';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION app.reject_deleted_account_insert() FROM PUBLIC;

CREATE TRIGGER account_deletion_insert BEFORE INSERT ON app.accounts
FOR EACH ROW EXECUTE FUNCTION app.reject_deleted_account_insert('id');
CREATE TRIGGER asset_deletion_insert BEFORE INSERT ON app.assets
FOR EACH ROW EXECUTE FUNCTION app.reject_deleted_account_insert('owner_id');
CREATE TRIGGER product_deletion_insert BEFORE INSERT ON app.products
FOR EACH ROW EXECUTE FUNCTION app.reject_deleted_account_insert('owner_id');
CREATE TRIGGER product_image_deletion_insert BEFORE INSERT ON app.product_images
FOR EACH ROW EXECUTE FUNCTION app.reject_deleted_account_insert('owner_id');
CREATE TRIGGER campaign_deletion_insert BEFORE INSERT ON app.campaigns
FOR EACH ROW EXECUTE FUNCTION app.reject_deleted_account_insert('owner_id');
CREATE TRIGGER job_deletion_insert BEFORE INSERT ON app.jobs
FOR EACH ROW EXECUTE FUNCTION app.reject_deleted_account_insert('owner_id');
CREATE TRIGGER reservation_deletion_insert BEFORE INSERT ON app.credit_reservations
FOR EACH ROW EXECUTE FUNCTION app.reject_deleted_account_insert('account_id');
