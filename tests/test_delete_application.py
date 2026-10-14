import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

from admaker.account_deletion import request_account_deletion
from admaker.delete_application import delete_requested_application_data
from test_worker_leases import URL, queued_job


def test_application_purge_removes_private_history_and_preserves_financial_and_other_threads(queued_job):
    account, job, reservation, queue = queued_job
    product, campaign, run = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    receipt = uuid.uuid4()
    thread, other_thread = str(uuid.uuid4()), str(uuid.uuid4())
    try:
        with psycopg.connect(URL) as c:
            asset = c.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (job,)).fetchone()[0]
            c.execute("INSERT INTO app.products(id,owner_id,name,source_asset_id) VALUES (%s,%s,'Private product',%s)", (product, account, asset))
            c.execute("INSERT INTO app.product_images(product_id,owner_id,version,asset_key) VALUES (%s,%s,1,%s)", (product, account, asset))
            c.execute("INSERT INTO app.campaigns(id,owner_id,product_id,image_version,brief) VALUES (%s,%s,%s,1,%s)", (campaign, account, product, Jsonb({"offer": "private offer"})))
            c.execute("INSERT INTO app.campaign_generations(campaign_id,campaign_version,job_id,price_credits) VALUES (%s,1,%s,2)", (campaign, job))
            c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state) VALUES (%s,%s,1,%s,'running')", (run, job, thread))
            c.execute("INSERT INTO app.media_review_budget(id,run_id,amount_microusd,state,verdict) VALUES (%s,%s,1,'finished',%s)", (receipt, run, Jsonb({"creativePlan": {"product_summary": "Private product", "creative_direction": "Private direction"}})))
            c.execute("INSERT INTO app.credit_ledger(account_id,delta,event_key) VALUES (%s,10,%s)", (account, str(uuid.uuid4())))
            for value in (thread, str(job), other_thread):
                c.execute("INSERT INTO public.checkpoints(thread_id,checkpoint_ns,checkpoint_id,checkpoint,metadata) VALUES (%s,'','1',%s,'{}')", (value, Jsonb({"private": "prompt"})))
                c.execute("INSERT INTO public.checkpoint_blobs(thread_id,checkpoint_ns,channel,version,type,blob) VALUES (%s,'','image','1','bytes',%s)", (value, b"private media"))
                c.execute("INSERT INTO public.checkpoint_writes(thread_id,checkpoint_ns,checkpoint_id,task_id,idx,channel,type,blob) VALUES (%s,'','1','task',0,'image','bytes',%s)", (value, b"private media"))
            c.execute("INSERT INTO app.account_eligibility(account_id,policy_version) VALUES (%s,'test')", (account,))
            c.execute("INSERT INTO app.brand_profiles(account_id,profile) VALUES (%s,%s)", (account, Jsonb({"name": "Private brand", "contact": "private@example.com"})))
            request_account_deletion(c, account)
            assert c.execute("SELECT count(*) FROM app.job_events WHERE job_id=%s", (job,)).fetchone()[0] > 0
        with pytest.raises(ValueError):
            delete_requested_application_data(URL, account)
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT name FROM app.products WHERE id=%s", (product,)).fetchone() == ("Private product",)
            # The two independent external/filesystem phase boundaries are injected here.
            c.execute("UPDATE app.account_deletions SET identity_deleted_at=now(),media_deleted_at=now() WHERE account_id=%s", (account,))
        for _ in range(2):
            assert delete_requested_application_data(URL, account) == {"state": "application_removed"}
        with psycopg.connect(URL) as c:
            for table in ("assets", "jobs", "products", "campaigns"):
                assert c.execute(f"SELECT count(*) FROM app.{table} WHERE owner_id=%s", (account,)).fetchone() == (0,)
            assert c.execute("SELECT count(*) FROM app.job_events WHERE job_id=%s", (job,)).fetchone() == (0,)
            for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                assert c.execute(f"SELECT count(*) FROM public.{table} WHERE thread_id=ANY(%s)", ([thread, str(job)],)).fetchone() == (0,)
                assert c.execute(f"SELECT count(*) FROM public.{table} WHERE thread_id=%s", (other_thread,)).fetchone() == (1,)
            assert c.execute("SELECT email FROM app.accounts WHERE id=%s", (account,)).fetchone() == ("",)
            assert c.execute("SELECT count(*) FROM app.account_eligibility WHERE account_id=%s", (account,)).fetchone() == (0,)
            assert c.execute("SELECT count(*) FROM app.brand_profiles WHERE account_id=%s", (account,)).fetchone() == (0,)
            assert c.execute("SELECT sum(delta) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (10,)
            assert c.execute("SELECT run_id,amount_microusd,verdict FROM app.media_review_budget WHERE id=%s", (receipt,)).fetchone() == (None, 1, None)
            assert c.execute("SELECT state,application_deleted_at IS NOT NULL FROM app.account_deletions WHERE account_id=%s", (account,)).fetchone() == ("requested", True)
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.media_review_budget WHERE id=%s", (receipt,))
            for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                c.execute(f"DELETE FROM public.{table} WHERE thread_id=ANY(%s)", ([thread, str(job), other_thread],))
            c.execute("DELETE FROM app.account_deletions WHERE account_id=%s", (account,))
            c.execute("DELETE FROM app.campaign_generations WHERE campaign_id=%s", (campaign,))
            c.execute("DELETE FROM app.campaigns WHERE id=%s", (campaign,))
            c.execute("DELETE FROM app.product_images WHERE product_id=%s", (product,))
            c.execute("DELETE FROM app.products WHERE id=%s", (product,))
