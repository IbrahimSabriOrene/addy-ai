-- Checkpoints contain private prompts/results, never direct-client API data.
SET LOCAL lock_timeout = '5s';
-- Applies to future public tables created by the migration role, including saver.setup().
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
DO $$
DECLARE checkpoint_table text;
BEGIN
    FOREACH checkpoint_table IN ARRAY ARRAY['checkpoints','checkpoint_blobs','checkpoint_writes','checkpoint_migrations'] LOOP
        IF to_regclass('public.' || checkpoint_table) IS NOT NULL THEN
            EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC, anon, authenticated', checkpoint_table);
        END IF;
    END LOOP;
END;
$$;
