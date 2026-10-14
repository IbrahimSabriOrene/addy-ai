import hashlib
import uuid
from types import SimpleNamespace

import psycopg
from google.genai import types

from admaker import provider_graph, worker
from admaker.veo import VeoRequest
from test_provider_graph import provider_job
from test_worker_leases import URL, queued_job


def test_optional_offer_free_review_is_bound_to_source_bytes(provider_job, monkeypatch, tmp_path):
    account, job, _, queue = provider_job
    source = tmp_path / "reviewed.mp4"
    source.write_bytes(b"fixture: codec boundary injected")
    monkeypatch.setattr(provider_graph, "compose_video", lambda *args: {"tiktok": {"key": source.name}})
    service = SimpleNamespace(submit=lambda *args, **kwargs: "operations/" + str(uuid.uuid4()),
        poll=lambda name: types.GenerateVideosOperation(name=name, done=True, response=types.GenerateVideosResponse(
            generated_videos=[types.GeneratedVideo(video=types.Video(uri="fake://video"))])), download=lambda *args: None)
    assert worker.process_one(URL, "review-proof", queue, video_service=service, video_request=VeoRequest("Fixture"),
        estimated_cost_microusd=1, video_review=lambda *args: {"policyAllowed": True, "qualityPassed": True, "offerFree": True})
    with psycopg.connect(URL) as c:
        verdict = c.execute("SELECT s.result FROM app.job_stages s JOIN app.job_runs r ON r.id=s.run_id WHERE r.job_id=%s AND s.stage_key='candidate_review'", (job,)).fetchone()[0]
    assert verdict["offerFree"] is True
    assert verdict["sourceSha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
