"""Remove private product data; retain pseudonymous financial records separately."""
import uuid

import psycopg
from psycopg import sql
from admaker.media_drain import try_lock_media_cleanup


def delete_requested_application_data(database_url, account_id):
    account_id = uuid.UUID(str(account_id))
    with psycopg.connect(database_url) as c:
        if not try_lock_media_cleanup(c, account_id):
            return {"state": "waiting_for_writers"}
        c.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (account_id,)).fetchone()
        phases = c.execute("SELECT identity_deleted_at,media_deleted_at,application_deleted_at FROM app.account_deletions WHERE account_id=%s FOR UPDATE", (account_id,)).fetchone()
        if phases[2] is not None:
            return {"state": "application_removed"}
        if phases[0] is None or phases[1] is None:
            raise ValueError("Identity and media deletion must be confirmed first")
        if c.execute("SELECT 1 FROM app.cloud_objects WHERE account_id=%s LIMIT 1", (account_id,)).fetchone():
            raise ValueError("Cloud object cleanup must be confirmed first")
        if c.execute("SELECT 1 FROM app.review_files WHERE account_id=%s LIMIT 1", (account_id,)).fetchone():
            raise ValueError("Provider review file cleanup must be confirmed first")
        jobs = [row[0] for row in c.execute("SELECT id FROM app.jobs WHERE owner_id=%s ORDER BY id FOR UPDATE", (account_id,))]
        if c.execute("SELECT 1 FROM app.credit_reservations WHERE account_id=%s AND state='held' LIMIT 1", (account_id,)).fetchone():
            raise ValueError("Held reservations must be resolved before application cleanup")
        threads = [row[0] for row in c.execute("SELECT thread_id FROM app.job_runs WHERE job_id=ANY(%s::uuid[])", (jobs,))]
        threads.extend(str(job) for job in jobs)  # Legacy graphs used the job UUID as thread ID.
        for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            c.execute(sql.SQL("DELETE FROM public.{} WHERE thread_id=ANY(%s)").format(sql.Identifier(table)), (threads,))
        # Queue/archive payloads contain job IDs; remove only this account's jobs.
        tables = c.execute("SELECT tablename FROM pg_tables WHERE schemaname='pgmq' AND (left(tablename,2)='q_' OR left(tablename,2)='a_')").fetchall()
        for (table,) in tables:
            c.execute(sql.SQL("DELETE FROM pgmq.{} WHERE message->>'jobId'=ANY(%s)").format(sql.Identifier(table)), ([str(job) for job in jobs],))
        c.execute("DELETE FROM app.result_reports WHERE owner_id=%s", (account_id,))
        for table in ("growth_notifications", "push_devices", "growth_events", "campaign_outcomes", "growth_preferences"):
            c.execute(sql.SQL("DELETE FROM app.{} WHERE account_id=%s").format(sql.Identifier(table)), (account_id,))
        c.execute("DELETE FROM app.campaign_generations WHERE campaign_id IN (SELECT id FROM app.campaigns WHERE owner_id=%s)", (account_id,))
        c.execute("UPDATE app.jobs SET active_run_id=NULL WHERE owner_id=%s", (account_id,))
        c.execute("UPDATE app.media_review_budget SET verdict=NULL WHERE verdict ? 'creativePlan' AND run_id IN (SELECT id FROM app.job_runs WHERE job_id=ANY(%s::uuid[]))", (jobs,))
        c.execute("DELETE FROM app.job_attempts WHERE run_id IN (SELECT id FROM app.job_runs WHERE job_id=ANY(%s::uuid[]))", (jobs,))
        c.execute("DELETE FROM app.job_runs WHERE job_id=ANY(%s::uuid[])", (jobs,))
        c.execute("DELETE FROM app.credit_reservations WHERE account_id=%s", (account_id,))
        c.execute("DELETE FROM app.jobs WHERE owner_id=%s", (account_id,))
        c.execute("DELETE FROM app.command_keys WHERE account_id=%s", (account_id,))
        c.execute("DELETE FROM app.campaigns WHERE owner_id=%s", (account_id,))
        c.execute("DELETE FROM app.product_images WHERE owner_id=%s", (account_id,))
        c.execute("DELETE FROM app.products WHERE owner_id=%s", (account_id,))
        c.execute("DELETE FROM app.brand_profiles WHERE account_id=%s", (account_id,))
        c.execute("DELETE FROM app.assets WHERE owner_id=%s", (account_id,))
        c.execute("DELETE FROM app.ai_consent WHERE account_id=%s", (account_id,))
        c.execute("DELETE FROM app.account_eligibility WHERE account_id=%s", (account_id,))
        c.execute("DELETE FROM app.api_rate_limits WHERE account_id=%s", (account_id,))
        c.execute("UPDATE app.accounts SET email='' WHERE id=%s", (account_id,))
        c.execute("UPDATE app.account_deletions SET application_deleted_at=clock_timestamp() WHERE account_id=%s", (account_id,))
    return {"state": "application_removed"}
