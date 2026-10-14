import uuid
from types import SimpleNamespace

import psycopg
import pytest
from google.genai import types

from admaker import provider_graph, worker
from admaker.media_review import MediaReviewPending
from admaker.campaign_review import review_campaign_pack
from admaker.campaign_failure import campaign_failure
from admaker.veo import VeoRequest
from test_provider_graph import provider_job
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("decision", ["resume", "release"])
def test_uncertain_review_preserves_media_credit_and_resumes_without_generation(provider_job, monkeypatch, tmp_path, decision):
    account, job, reservation, queue = provider_job
    submitted, reviewed = [], []
    def submit(*args, **kwargs):
        submitted.append(1)
        return "operations/" + str(uuid.uuid4())
    def compose(*args):
        path = tmp_path / "video.mp4"
        path.write_bytes(b"fixture saved media")
        return {"tiktok": {"key": path.name}}
    def review(*args):
        reviewed.append(1)
        if len(reviewed) == 1:
            raise MediaReviewPending("Secret provider error must not enter result")
        return {"policyAllowed": True, "qualityPassed": True}
    monkeypatch.setattr(provider_graph, "compose_video", compose)
    service = SimpleNamespace(submit=submit,
        poll=lambda name: types.GenerateVideosOperation(name=name, done=True, response=types.GenerateVideosResponse(
            generated_videos=[types.GeneratedVideo(video=types.Video(uri="fake://video"))])), download=lambda *args: None)
    options = dict(video_service=service, video_request=VeoRequest("Fixture"), estimated_cost_microusd=1, video_review=review)
    assert worker.process_one(URL, "review-error", queue, **options)
    with psycopg.connect(URL) as c:
        run, fence, state = c.execute("SELECT id,fence,state FROM app.job_runs WHERE job_id=%s", (job,)).fetchone()
        result = c.execute("SELECT result FROM app.jobs WHERE id=%s", (job,)).fetchone()[0]
        assert state == "review_required"
        assert result["failure"] == {"code": "media_review_pending"}
        assert campaign_failure("failed", result)["code"] == "media_review_pending"
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("held",)
    assert worker.recover_expired_runs(URL, queue, str(job)) == 0
    assert not worker.process_one(URL, "automatic", queue, **options)
    assert len(reviewed) == len(submitted) == 1
    assert review_campaign_pack(URL, run, fence, "operator", "Review service investigated", decision, queue if decision == "resume" else None)
    assert not review_campaign_pack(URL, run, fence, "operator", "Review service investigated", decision, queue if decision == "resume" else None)
    if decision == "resume":
        assert worker.process_one(URL, "review-resumed", queue, **options)
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("consumed" if decision == "resume" else "released",)
        assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (1 if decision == "resume" else 0,)
    assert submitted == [1]
    assert (tmp_path / "video.mp4").read_bytes() == b"fixture saved media"
