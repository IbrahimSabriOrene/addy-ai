import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg
import pytest
from fastapi.testclient import TestClient

from admaker.account_deletion import request_account_deletion
from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from test_worker_leases import URL, queued_job


def test_pre_authenticated_request_and_new_records_cannot_bypass_deletion(queued_job, monkeypatch):
    account, job, reservation, queue = queued_job
    monkeypatch.setenv("DATABASE_URL", URL)
    try:
        with psycopg.connect(URL) as c:
            asset = c.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (job,)).fetchone()[0]
            request_account_deletion(c, account)
        statements = [
            ("INSERT INTO app.accounts(id,email) VALUES (%s,'old-token@example.com') ON CONFLICT(id) DO UPDATE SET email=EXCLUDED.email", (account,)),
            ("INSERT INTO app.assets(asset_key,owner_id,storage_key,mime_type) VALUES (%s,%s,%s,'image/png')", (uuid.uuid4(), account, str(uuid.uuid4()))),
            ("INSERT INTO app.products(id,owner_id,name,source_asset_id) VALUES (%s,%s,'Late product',%s)", (uuid.uuid4(), account, asset)),
            ("INSERT INTO app.product_images(product_id,owner_id,version,asset_key) VALUES (%s,%s,1,%s)", (uuid.uuid4(), account, asset)),
            ("INSERT INTO app.campaigns(id,owner_id,product_id,image_version,brief) VALUES (%s,%s,%s,1,'{}')", (uuid.uuid4(), account, uuid.uuid4())),
            ("INSERT INTO app.jobs(id,owner_id,source_asset_id,state) VALUES (%s,%s,%s,'submitted')", (uuid.uuid4(), account, asset)),
            ("INSERT INTO app.credit_reservations(id,account_id,job_id,amount,state) VALUES (%s,%s,%s,1,'held')", (uuid.uuid4(), account, job)),
        ]
        for sql, values in statements:
            with psycopg.connect(URL) as c, pytest.raises(psycopg.errors.CheckViolation) as error:
                c.execute(sql, values)
            assert error.value.diag.constraint_name == "account_deletion_requested"
        # Simulate a request that already passed the normal authentication dependency.
        app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "owner@example.com")
        with TestClient(app) as client:
            response = client.post("/v1/products", json={"name": "Late product", "assetKey": str(asset)})
            assert response.status_code == 410
            assert response.json()["code"] == "account_deletion_requested"
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.account_deletions WHERE account_id=%s", (account,))


def test_concurrent_job_insert_and_deletion_leave_no_runnable_job(queued_job):
    account, job, reservation, queue = queued_job
    new_job = uuid.uuid4()
    barrier = Barrier(2)
    with psycopg.connect(URL) as c:
        asset = c.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (job,)).fetchone()[0]

    def insert():
        try:
            with psycopg.connect(URL) as c:
                barrier.wait()
                c.execute("INSERT INTO app.jobs(id,owner_id,source_asset_id,state) VALUES (%s,%s,%s,'submitted')", (new_job, account, asset))
            return True
        except psycopg.errors.CheckViolation:
            return False

    def delete():
        with psycopg.connect(URL) as c:
            barrier.wait()
            return request_account_deletion(c, account)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            writing, deleting = pool.submit(insert), pool.submit(delete)
            inserted = writing.result(timeout=10)
            assert deleting.result(timeout=10) == {"state": "requested"}
        with psycopg.connect(URL) as c:
            row = c.execute("SELECT state FROM app.jobs WHERE id=%s", (new_job,)).fetchone()
            assert row == (("aborted",) if inserted else None)
            assert c.execute("SELECT count(*) FROM app.credit_reservations WHERE account_id=%s AND state='held'", (account,)).fetchone() == (0,)
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.jobs WHERE id=%s", (new_job,))
            c.execute("DELETE FROM app.account_deletions WHERE account_id=%s", (account,))
