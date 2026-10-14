import uuid
import psycopg
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient
from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from test_worker_leases import URL, queued_job


def test_owned_job_detail_and_list_keep_campaign_route(queued_job, monkeypatch):
    owner, job, *_ = queued_job
    campaign = str(uuid.uuid4())
    monkeypatch.setenv("DATABASE_URL", URL)
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.jobs SET settings=%s WHERE id=%s", (Jsonb({"campaignId": campaign, "campaignVersion": 3}), job))
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(owner), "fixture@example.test")
    try:
        with TestClient(app) as client:
            detail = client.get(f"/v1/jobs/{job}").json()
            listed = next(item for item in client.get("/v1/jobs").json()["items"] if item["id"] == str(job))
            for item in (detail, listed):
                assert (item["campaignId"], item["campaignVersion"]) == (campaign, 3)
            app.dependency_overrides[authenticated_subject] = lambda: Subject(str(uuid.uuid4()), "other@example.test")
            assert client.get(f"/v1/jobs/{job}").status_code == 404
            assert client.get("/v1/jobs").json()["items"] == []
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
