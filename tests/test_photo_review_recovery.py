import psycopg
import pytest
from psycopg.types.json import Jsonb

from admaker import worker
from admaker.campaign_review import review_campaign_pack
from admaker.media_review import MediaReviewPending
from admaker.photo_provider import PHOTO_MODEL
from test_provider_graph import provider_job
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("decision", ["resume", "release"])
def test_photo_review_operator_recovery_preserves_original_generation(provider_job, monkeypatch, tmp_path, decision):
    account, job, reservation, queue = provider_job
    monkeypatch.setenv("PHOTO_DAILY_BUDGET_MICROUSD", "100000000000")
    settings = {"outputKind": "photo", "photoProvider": True, "preparedPhotoPrompt": "Soft light",
        "photoModel": PHOTO_MODEL, "renderPlatforms": ["feed_square"]}
    with psycopg.connect(URL) as connection:
        connection.execute("UPDATE app.jobs SET settings=%s WHERE id=%s", (Jsonb(settings), job))
    generated, reviewed = [], []
    def generate(*args, **kwargs):
        generated.append(True)
        return (tmp_path / "test.png").read_bytes()
    def review(root, exports):
        reviewed.append(True)
        if len(reviewed) == 2:
            raise MediaReviewPending("Private review failure")
        return {"policyAllowed": True, "qualityPassed": True, "offerFree": True}
    options = dict(photo_generate=generate, estimated_cost_microusd=7, video_review=review)
    try:
        assert worker.process_one(URL, "photo-review-first", queue, **options)
        with psycopg.connect(URL) as connection:
            run, fence, state = connection.execute("SELECT id,fence,state FROM app.job_runs WHERE job_id=%s", (job,)).fetchone()
            assert state == "review_required"
            assert connection.execute("SELECT result->'failure' FROM app.jobs WHERE id=%s", (job,)).fetchone() == ({"code": "media_review_pending"},)
            assert connection.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("held",)
        assert worker.recover_expired_runs(URL, queue, str(job)) == 0
        assert not worker.process_one(URL, "photo-no-auto-review", queue, **options)
        args = (URL, run, fence, "operator", "Review service repaired", decision, queue if decision == "resume" else None)
        assert review_campaign_pack(*args)
        assert not review_campaign_pack(*args)
        if decision == "resume":
            assert worker.process_one(URL, "photo-reviewed", queue, **options)
        with psycopg.connect(URL) as connection:
            assert connection.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("consumed" if decision == "resume" else "released",)
            assert connection.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (1 if decision == "resume" else 0,)
        assert generated == [True]
        assert len(reviewed) == (3 if decision == "resume" else 2)
    finally:
        with psycopg.connect(URL) as connection:
            connection.execute("DELETE FROM app.provider_budget_holds WHERE attempt_id IN (SELECT a.id FROM app.job_attempts a JOIN app.job_runs r ON r.id=a.run_id WHERE r.job_id=%s)", (job,))
