import uuid

import psycopg
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from test_worker_leases import URL, queued_job


def test_pack_history_survives_brief_edits_and_paginates_privately(queued_job, monkeypatch):
    account, job, reservation, queue = queued_job
    product, campaign, older_job = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    monkeypatch.setenv("DATABASE_URL", URL)
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "history@example.com")
    try:
        with psycopg.connect(URL) as c:
            asset = c.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (job,)).fetchone()[0]
            c.execute("INSERT INTO app.products(id,owner_id,name,source_asset_id) VALUES (%s,%s,'Fixture',%s)", (product, account, asset))
            c.execute("INSERT INTO app.product_images(product_id,owner_id,version,asset_key) VALUES (%s,%s,1,%s)", (product, account, asset))
            c.execute("INSERT INTO app.campaigns(id,owner_id,product_id,image_version,brief,version) VALUES (%s,%s,%s,1,'{}',5)", (campaign, account, product))
            c.execute("INSERT INTO app.jobs(id,owner_id,source_asset_id,state) VALUES (%s,%s,%s,'delivered')", (older_job, account, asset))
            c.execute("INSERT INTO app.campaign_generations(campaign_id,campaign_version,job_id,price_credits) VALUES (%s,3,%s,3),(%s,1,%s,2)", (campaign, job, campaign, older_job))
        with TestClient(app) as client:
            path = f"/v1/campaigns/{campaign}/generations"
            first = client.get(path + "?limit=1").json()
            assert [item["version"] for item in first["items"]] == [3]
            assert first["nextBeforeVersion"] == 3
            second = client.get(path + "?limit=1&beforeVersion=3").json()
            assert [item["version"] for item in second["items"]] == [1]
            assert second["nextBeforeVersion"] is None
            assert client.get(path + "?beforeVersion=1").json()["items"] == []
            assert client.get(path + "?limit=0").status_code == 422
            assert client.get(path + "?beforeVersion=0").status_code == 422
            app.dependency_overrides[authenticated_subject] = lambda: Subject(str(uuid.uuid4()), "other@example.com")
            assert client.get(path).status_code == 404
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.campaign_generations WHERE campaign_id=%s", (campaign,))
            c.execute("DELETE FROM app.jobs WHERE id=%s", (older_job,))
            c.execute("DELETE FROM app.campaigns WHERE id=%s", (campaign,))
            c.execute("DELETE FROM app.product_images WHERE product_id=%s", (product,))
            c.execute("DELETE FROM app.products WHERE id=%s", (product,))
