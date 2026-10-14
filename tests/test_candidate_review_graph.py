import uuid
import hashlib
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from fastapi.testclient import TestClient
from google.genai import types

from admaker import provider_graph, worker
from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.veo import VeoRequest
from test_provider_graph import provider_job, queued_job, URL, Crash


@pytest.mark.parametrize("verdict", [
    {"policyAllowed": True, "qualityPassed": True},
    {"policyAllowed": True, "qualityPassed": False},
    {"policyAllowed": False, "qualityPassed": True},
    {"policyAllowed": "yes", "qualityPassed": True},
])
def test_reviewed_candidate_survives_crash_and_controls_delivery(provider_job, monkeypatch, verdict):
    account, job, reservation, queue = provider_job
    calls = {"submit": 0, "review": 0}

    def submit(*args, **kwargs):
        calls["submit"] += 1
        return f"operations/{uuid.uuid4()}"

    def poll(name):
        return types.GenerateVideosOperation(name=name, done=True, response=types.GenerateVideosResponse(
            generated_videos=[types.GeneratedVideo(video=types.Video(uri="fake://video"))]))

    def review(root, exports):
        calls["review"] += 1
        assert exports["tiktok"]["key"].endswith("final.mp4")
        return verdict

    def compose(source, root, output_id, platforms):
        key = f"runs/{output_id}/final.mp4"
        (root / key).write_bytes(source.read_bytes())
        return {"tiktok": {"key": key, "caption": "Fixture", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}}
    monkeypatch.setattr(provider_graph, "compose_video", compose)
    service = SimpleNamespace(submit=submit, poll=poll,
        download=lambda operation, path: Path(path).write_bytes(b"fixture"))
    options = dict(video_service=service, video_request=VeoRequest("Fixture"),
                   estimated_cost_microusd=400000, video_review=review)
    allowed = verdict["policyAllowed"] is True
    if allowed:
        original = provider_graph.run_provider_graph

        def crash(*args):
            original(*args)
            raise Crash()

        monkeypatch.setattr(provider_graph, "run_provider_graph", crash)
        with pytest.raises(Crash):
            worker.process_one(URL, "first", queue, **options)
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone()[0] == "held"
            c.execute("UPDATE app.job_runs SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s", (job,))
        monkeypatch.setattr(provider_graph, "run_provider_graph", original)
        # A completed graph must not settle changed local output on restart.
        with psycopg.connect(URL) as c:
            manifest = c.execute("SELECT result FROM app.job_stages WHERE run_id=(SELECT active_run_id FROM app.jobs WHERE id=%s) AND stage_key='provider_compose'", (job,)).fetchone()[0]
        import os
        output = Path(os.environ["LOCAL_ASSET_ROOT"]) / manifest["tiktok"]["key"]
        original_bytes = output.read_bytes()
        output.write_bytes(b"changed after checkpoint")
        assert worker.recover_expired_runs(URL, queue, str(job)) == 1
        assert worker.process_one(URL, "changed-output", queue, **options)
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("held",)
            assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
            c.execute("UPDATE app.job_runs SET next_work_at=clock_timestamp()-interval '1 second' WHERE job_id=%s", (job,))
        output.write_bytes(original_bytes)
        assert worker.recover_expired_runs(URL, queue, str(job)) == 1
    assert worker.process_one(URL, "replacement", queue, **options)
    assert calls == {"submit": 1, "review": 1}
    expected = "failed" if not allowed else "delivered" if verdict["qualityPassed"] else "awaiting_user_decision"
    with psycopg.connect(URL) as c:
        state, result = c.execute("SELECT state,result FROM app.jobs WHERE id=%s", (job,)).fetchone()
        assert state == expected
        if allowed:
            assert result["candidateValidation"]["reservationId"] == str(reservation)
            assert result["runs"]["1"]["exports"] == result["exports"]
        else:
            assert not result.get("exports")
            assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone()[0] == "released"
        if expected != "delivered":
            assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone()[0] == 0
    if expected == "awaiting_user_decision":
        assert worker.recover_expired_runs(URL, queue, str(job)) == 0
        app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "candidate@example.com")
        try:
            with TestClient(app) as client:
                candidate = client.get(f"/v1/jobs/{job}").json()
                assert candidate["gate"] == "awaiting_user_decision" and candidate["exports"]
                response = client.post(f"/v1/jobs/{job}/decision", json={"action": "accept", "expectedVersion": candidate["version"]}, headers={"Idempotency-Key": "approve-candidate"})
                assert response.status_code == 202
            with psycopg.connect(URL) as c:
                assert c.execute("SELECT delta FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchall() == [(-2,)]
        finally:
            app.dependency_overrides.pop(authenticated_subject, None)
            with psycopg.connect(URL) as c:
                c.execute("DELETE FROM app.command_keys WHERE account_id=%s", (account,))


def test_missing_reviewer_cannot_start_paid_work(provider_job):
    account, job, reservation, queue = provider_job
    with pytest.raises(ValueError, match="reviewer"):
        worker.process_one(URL, "first", queue, video_service=object(),
                           video_request=VeoRequest("Fixture"), estimated_cost_microusd=400000)
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT count(*) FROM app.job_runs WHERE job_id=%s", (job,)).fetchone()[0] == 0
