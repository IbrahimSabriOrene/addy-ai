import uuid
from types import SimpleNamespace

import psycopg
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient
from google.genai import types

from admaker.api import app, STYLE_CANDIDATES
from admaker.auth import Subject, authenticated_subject
from admaker.catalogue import TEMPLATES
from admaker.job_prompts import snapshot_styles
from admaker.worker import process_one
from test_provider_graph import provider_job, queued_job, URL, allow_review


def test_style_snapshot_stays_private_and_drives_provider_request(provider_job, monkeypatch):
    account, job, reservation, queue = provider_job
    options = snapshot_styles(STYLE_CANDIDATES)
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.jobs SET state='awaiting_style_choice',settings=%s WHERE id=%s",
                  (Jsonb({"styleOptions": options, "direction": "Warm light"}), job))
    monkeypatch.setitem(TEMPLATES, "pedestal_spin", {**TEMPLATES["pedestal_spin"], "prompt": "CHANGED AFTER THE USER SAW THE CHOICES"})
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "style@example.com")
    try:
        with TestClient(app) as client:
            detail = client.get(f"/v1/jobs/{job}").json()
            assert detail["candidates"][0]["name"] == options[0]["name"]
            assert "prompt" not in str(detail["candidates"])
            version = detail["version"]
            for invalid in ({"presetId": "not-offered"}, {"direction": "  "}, {"presetId": "pedestal_spin", "direction": "other"}):
                assert client.post(f"/v1/jobs/{job}/style-choice", json={**invalid, "expectedVersion": version}, headers={"Idempotency-Key": "invalid"}).status_code == 422
            response = client.post(f"/v1/jobs/{job}/style-choice", json={"presetId": "pedestal_spin", "expectedVersion": version}, headers={"Idempotency-Key": "choice"})
            assert response.status_code == 202
            detail = client.get(f"/v1/jobs/{job}")
            assert "preparedVideoPrompt" not in detail.text and "seamless studio backdrop" not in detail.text
        requests = []

        def submit(request, **kwargs):
            requests.append(request)
            return f"operations/{uuid.uuid4()}"

        service = SimpleNamespace(submit=submit, poll=lambda name: types.GenerateVideosOperation(name=name, done=False))
        assert process_one(URL, "worker", queue, video_service=service,
                           estimated_cost_microusd=400000, video_review=allow_review)
        assert len(requests) == 1
        assert "seamless studio backdrop" in requests[0].prompt and "Warm light" in requests[0].prompt
        assert "CHANGED AFTER" not in requests[0].prompt and "{product}" not in requests[0].prompt
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.command_keys WHERE account_id=%s", (account,))
            c.execute("DELETE FROM pgmq.q_commands WHERE message->>'jobId'=%s", (str(job),))
