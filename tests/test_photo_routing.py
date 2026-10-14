import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.retry_pricing import retry_terms
from admaker.worker import process_one
from test_provider_graph import provider_job
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("kind,flag,queue_key", [("photo", "ENABLE_REAL_PHOTO", "PHOTO_QUEUE"), ("video", "ENABLE_REAL_VEO", "CAMPAIGN_PACK_QUEUE")])
def test_photo_admission_and_retries_stay_off_fixture_queue(provider_job, monkeypatch, kind, flag, queue_key):
    account, original, _, queue = provider_job
    monkeypatch.setenv(flag, "true")
    monkeypatch.setenv("ENABLE_REAL_MEDIA_REVIEW", "true")
    monkeypatch.setenv(queue_key, queue)
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "photo-routing@example.test")
    job = None
    with psycopg.connect(URL) as connection:
        asset = connection.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (original,)).fetchone()[0]
        connection.execute("INSERT INTO app.credit_ledger(account_id,delta,event_key) VALUES (%s,3,%s)", (account, "photo-routing:" + str(account)))
        message = connection.execute("SELECT msg_id FROM pgmq.read(%s,vt=>60,qty=>1)", (queue,)).fetchone()[0]
        connection.execute("SELECT pgmq.archive(%s,%s)", (queue, message))
    try:
        with TestClient(app) as client:
            payload = {"assetKey": str(asset), "templateId": "pedestal_spin", "templateVersion": 1,
                "outputKind": kind, "platforms": ["feed"], "fastMode": False}
            result = client.post("/v1/jobs", json=payload, headers={"Idempotency-Key": "provider-photo"})
            assert result.status_code == 202
            job = result.json()["id"]
            with psycopg.connect(URL) as connection:
                settings = connection.execute("SELECT settings FROM app.jobs WHERE id=%s", (job,)).fetchone()[0]
                assert settings[kind + "Provider"] is True
                assert connection.execute("SELECT count(*) FROM pgmq.q_commands WHERE message->>'jobId'=%s", (job,)).fetchone() == (0,)
            with pytest.raises(ValueError, match=kind + " worker"):
                process_one(URL, "wrong-fixture-worker", queue)
            with psycopg.connect(URL) as connection:
                assert connection.execute("SELECT state FROM app.jobs WHERE id=%s", (job,)).fetchone() == ("submitted",)
                assert connection.execute("SELECT count(*) FROM app.job_runs WHERE job_id=%s", (job,)).fetchone() == (0,)
            assert retry_terms(settings, 1, str(account)) == (1, queue)
            monkeypatch.setenv(flag, "false")
            with pytest.raises(HTTPException) as error:
                retry_terms(settings, 1, str(account))
            assert error.value.status_code == 503
            assert client.post("/v1/jobs", json=payload, headers={"Idempotency-Key": "provider-photo"}).json() == result.json()
    finally:
        app.dependency_overrides.clear()
        if job:
            with psycopg.connect(URL) as connection:
                connection.execute("DELETE FROM app.command_keys WHERE account_id=%s AND key='provider-photo'", (account,))
                connection.execute("DELETE FROM app.credit_reservations WHERE job_id=%s", (job,))
                connection.execute("DELETE FROM app.jobs WHERE id=%s", (job,))


def test_photo_worker_once_binds_only_photo_services(provider_job, monkeypatch):
    import admaker.photo_worker as entry
    _, _, _, queue = provider_job
    values = {"ENABLE_REAL_PHOTO": "true", "ENABLE_REAL_MEDIA_REVIEW": "true", "PHOTO_QUEUE": queue,
        "GEMINI_API_KEY": "fixture", "GOOGLE_API_KEY": "fixture", "MEDIA_REVIEW_MODEL": "gemini-fixture",
        "PHOTO_ESTIMATED_COST_MICROUSD": "7", "PHOTO_DAILY_BUDGET_MICROUSD": "100", "PHOTO_MAX_CONCURRENT_OPERATIONS": "3",
        "MEDIA_REVIEW_ESTIMATE_MICROUSD": "1", "MEDIA_REVIEW_DAILY_BUDGET_MICROUSD": "100",
        "MEDIA_REVIEW_MAX_CALLS_PER_RUN": "3", "MEDIA_REVIEW_MAX_CONCURRENT_CALLS": "3"}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    calls = []
    monkeypatch.setattr("sys.argv", ["photo_worker", "--once"])
    monkeypatch.setattr(entry, "recover_photo_runs", lambda url, q: calls.append(("recover", q)))
    monkeypatch.setattr(entry, "build_media_reviewer", lambda db, job, run, model: model)
    def process(url, owner, q, **options):
        assert q == queue and options["photo_generate"] is entry.generate_product_photo
        assert options["estimated_cost_microusd"] == 7 and "video_service" not in options
        assert options["video_review_factory"](url, "job", "run") == "gemini-fixture"
        calls.append(("process", q))
        return False
    monkeypatch.setattr(entry, "process_one", process)
    entry.main()
    assert calls == [("recover", queue), ("process", queue)]
    monkeypatch.setenv("PHOTO_QUEUE", "commands")
    with pytest.raises(ValueError, match="dedicated"):
        entry.photo_worker_configuration()
    monkeypatch.setenv("PHOTO_QUEUE", queue)
    monkeypatch.setenv("ENABLE_REAL_PHOTO", "false")
    with pytest.raises(ValueError, match="enablement"):
        entry.photo_worker_configuration()
