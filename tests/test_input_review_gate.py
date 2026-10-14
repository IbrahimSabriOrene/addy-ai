import uuid
from types import SimpleNamespace

import psycopg
import pytest
from google.genai import types

from admaker import worker, provider_graph
from admaker.campaign_review import review_campaign_pack
from admaker.media_review import MediaReviewPending
from admaker.veo import VeoRequest
from test_provider_graph import provider_job
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("outcome", ["blocked", "unknown"])
def test_input_policy_gate_prevents_paid_submission(provider_job, monkeypatch, tmp_path, outcome):
    account, job, reservation, queue = provider_job
    submissions, reviews = [], []
    def submit(*args, **kwargs):
        submissions.append(1)
        return "operations/" + str(uuid.uuid4())
    def review(root, exports):
        reviews.append(exports)
        if len(reviews) == 1:
            assert exports["input"]["instructions"] == "Merchant fixture"
            if outcome == "unknown":
                raise MediaReviewPending("Transport uncertain")
            return {"policyAllowed": False, "qualityPassed": False, "offerFree": False}
        return {"policyAllowed": True, "qualityPassed": True, "offerFree": False}
    service = SimpleNamespace(submit=submit, poll=lambda name: types.GenerateVideosOperation(name=name, done=False))
    options = dict(video_service=service, video_request=VeoRequest("Merchant fixture"), estimated_cost_microusd=1,
                   video_review_factory=lambda *args: review)
    assert worker.process_one(URL, "input-gate", queue, **options)
    assert not submissions
    with psycopg.connect(URL) as c:
        run, fence = c.execute("SELECT id,fence FROM app.job_runs WHERE job_id=%s", (job,)).fetchone()
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("released" if outcome == "blocked" else "held",)
        assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
        assert c.execute("SELECT count(*) FROM app.provider_budget_holds WHERE attempt_id IN (SELECT id FROM app.job_attempts WHERE run_id=%s)", (run,)).fetchone() == (0,)
    if outcome == "unknown":
        assert review_campaign_pack(URL, run, fence, "operator", "Review now available", "resume", queue)
        assert worker.process_one(URL, "input-retry", queue, **options)
        assert submissions == [1] and len(reviews) == 2
        with psycopg.connect(URL) as c:
            c.execute("UPDATE app.job_runs SET next_work_at=clock_timestamp()-interval '1 second' WHERE id=%s", (run,))
        assert worker.recover_expired_runs(URL, queue, str(job)) == 1
        assert worker.process_one(URL, "input-cached", queue, **options)
        assert submissions == [1] and len(reviews) == 2
