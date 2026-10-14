import io
import uuid

import psycopg
from fastapi.testclient import TestClient
from PIL import Image

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.db import migrate
from admaker.worker import process_one


def test_photo_api_queue_worker_download_and_replay(monkeypatch, tmp_path):
    url = "postgresql://postgres:postgres@localhost:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("LOCAL_ASSET_ROOT", str(tmp_path))
    monkeypatch.setenv("DEV_SEED_CREDITS", "1")
    migrate()
    owner = Subject(str(uuid.uuid4()), "photo-flow@example.com")
    queue = f"photo_{uuid.uuid4().hex}"
    with psycopg.connect(url) as c:
        c.execute("SELECT pgmq.create(%s)", (queue,))
    app.dependency_overrides[authenticated_subject] = lambda: owner

    def no_video(*args, **kwargs):
        raise AssertionError("Photo job attempted video rendering")

    monkeypatch.setattr("admaker.worker._render_fake", no_video)
    try:
        with TestClient(app) as client:
            data = io.BytesIO()
            Image.new("RGB", (40, 40), "blue").save(data, format="PNG")
            upload = client.post("/v1/uploads/presign", json={"mimeType": "image/png", "sizeBytes": len(data.getvalue())}).json()
            assert client.put(upload["uploadUrl"], content=data.getvalue(), headers=upload["headers"]).status_code == 204
            assert client.post("/v1/uploads/complete", json={"assetKey": upload["assetKey"]}).status_code == 200
            payload = {"assetKey": upload["assetKey"], "platforms": ["feed"], "fastMode": False,
                       "templateId": "pedestal_spin", "templateVersion": 1, "outputKind": "photo"}
            headers = {"Idempotency-Key": "photo-action"}
            created = client.post("/v1/jobs", json=payload, headers=headers)
            assert created.status_code == 202
            job = created.json()["id"]
            assert created.json()["state"] == "submitted"
            assert created.json()["candidates"] == []
            with psycopg.connect(url) as c:
                messages = c.execute("SELECT msg_id,message FROM pgmq.q_commands WHERE message->>'jobId'=%s", (job,)).fetchall()
                assert len(messages) == 1
                c.execute("SELECT pgmq.send(%s,%s)", (queue, psycopg.types.json.Jsonb(messages[0][1])))
                c.execute("SELECT pgmq.delete('commands',%s)", (messages[0][0],))
            assert process_one(url, "photo-worker", queue)
            result = client.get(f"/v1/jobs/{job}").json()
            assert result["state"] == "delivered"
            downloaded = client.get(result["exports"][0]["url"])
            assert downloaded.headers["content-type"] == "image/png"
            with Image.open(io.BytesIO(downloaded.content)) as image:
                assert image.size == (1080, 1080)
            assert client.post("/v1/jobs", json=payload, headers=headers).json() == created.json()
            assert client.get("/v1/credits").json()["balance"] == 0
            app.dependency_overrides[authenticated_subject] = lambda: Subject(str(uuid.uuid4()), "other@example.com")
            assert client.get(result["exports"][0]["url"]).status_code == 404
    finally:
        app.dependency_overrides.clear()
        with psycopg.connect(url) as c:
            c.execute("SELECT pgmq.drop_queue(%s)", (queue,))
            c.execute("DELETE FROM pgmq.q_commands WHERE message->>'jobId' IN (SELECT id::text FROM app.jobs WHERE owner_id=%s)", (owner.id,))
            c.execute("UPDATE app.jobs SET active_run_id=NULL WHERE owner_id=%s", (owner.id,))
            c.execute("DELETE FROM app.job_attempts WHERE run_id IN (SELECT r.id FROM app.job_runs r JOIN app.jobs j ON j.id=r.job_id WHERE j.owner_id=%s)", (owner.id,))
            c.execute("DELETE FROM app.job_runs WHERE job_id IN (SELECT id FROM app.jobs WHERE owner_id=%s)", (owner.id,))
            c.execute("DELETE FROM app.credit_reservations WHERE account_id=%s", (owner.id,))
            c.execute("DELETE FROM app.command_keys WHERE account_id=%s", (owner.id,))
            c.execute("DELETE FROM app.jobs WHERE owner_id=%s", (owner.id,))
            c.execute("DELETE FROM app.credit_ledger WHERE account_id=%s", (owner.id,))
            c.execute("DELETE FROM app.assets WHERE owner_id=%s", (owner.id,))
            c.execute("DELETE FROM app.accounts WHERE id=%s", (owner.id,))
