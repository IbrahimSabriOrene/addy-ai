from pathlib import Path

import psycopg
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from admaker import worker
from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.photo_provider import PHOTO_MODEL
from test_provider_graph import provider_job
from test_worker_leases import URL, queued_job


def test_photo_accept_requires_same_available_bytes_and_debits_once(provider_job, monkeypatch, tmp_path):
    account, job, reservation, queue = provider_job
    monkeypatch.setenv("PHOTO_DAILY_BUDGET_MICROUSD", "100000000000")
    calls = []
    def generate(*args, **kwargs):
        calls.append(True)
        return (tmp_path / "test.png").read_bytes()
    def review(root, exports):
        return {"policyAllowed": True, "qualityPassed": "input" in exports, "offerFree": True}
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.jobs SET settings=%s WHERE id=%s", (Jsonb({"outputKind": "photo", "photoModel": PHOTO_MODEL, "preparedPhotoPrompt": "Soft light", "platforms": ["feed"], "renderPlatforms": ["feed_square"]}), job))
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "photo@example.test")
    try:
        assert worker.process_one(URL, "photo-accept", queue, photo_generate=generate, estimated_cost_microusd=1, video_review=review)
        with psycopg.connect(URL) as c:
            result, version = c.execute("SELECT result,version FROM app.jobs WHERE id=%s", (job,)).fetchone()
        path = tmp_path / result["exports"]["feed_square"]["key"]
        assert path.resolve().is_relative_to(tmp_path.resolve())
        original = path.read_bytes()
        with TestClient(app) as client:
            body = {"action": "accept", "expectedVersion": version}
            headers = {"Idempotency-Key": "same-photo-accept"}
            path.unlink()
            assert client.post(f"/v1/jobs/{job}/decision", json=body, headers=headers).status_code == 409
            path.write_bytes(b"changed")
            assert client.post(f"/v1/jobs/{job}/decision", json=body, headers=headers).status_code == 409
            with psycopg.connect(URL) as c:
                assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("held",)
                assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
            path.write_bytes(original)
            for _ in range(2):
                assert client.post(f"/v1/jobs/{job}/decision", json=body, headers=headers).status_code == 202
        assert calls == [True]
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT count(*),sum(delta) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (1, -2)
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.command_keys WHERE account_id=%s", (account,))
            c.execute("DELETE FROM app.provider_budget_holds WHERE attempt_id IN (SELECT id FROM app.job_attempts WHERE run_id IN (SELECT id FROM app.job_runs WHERE job_id=%s))", (job,))
