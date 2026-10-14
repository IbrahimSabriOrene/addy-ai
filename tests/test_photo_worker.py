from admaker.eligibility import POLICY_VERSION
import io
from pathlib import Path

import psycopg
import pytest
from PIL import Image
from psycopg.types.json import Jsonb

from admaker import worker
from admaker.cloud_objects import CloudPublicationPending
from admaker.consent import DISCLOSURE_VERSION
from admaker.photo_provider import PHOTO_MODEL
from test_provider_graph import provider_job
from test_worker_leases import URL, queued_job


def test_photo_api_uses_frozen_direction_and_delivers_one_paid_result(monkeypatch, tmp_path):
    import test_photo_flow
    from admaker.catalogue import TEMPLATES
    monkeypatch.setenv("PHOTO_DAILY_BUDGET_MICROUSD", "100000000000")
    calls, reviews = [], []
    image = io.BytesIO()
    Image.new("RGB", (40, 40), "green").save(image, format="PNG")
    def process(database_url, owner, queue):
        with psycopg.connect(database_url) as connection:
            job = connection.execute("SELECT message->>'jobId' FROM pgmq." + "q_" + queue).fetchone()[0]
            account, settings = connection.execute("SELECT owner_id,settings FROM app.jobs WHERE id=%s", (job,)).fetchone()
            assert "preparedVideoPrompt" not in settings and settings["photoModel"] == PHOTO_MODEL
            frozen = settings["preparedPhotoPrompt"]
            connection.execute("INSERT INTO app.account_eligibility(account_id,policy_version) VALUES (%s,%s)", (account, POLICY_VERSION))
            connection.execute("INSERT INTO app.ai_consent(account_id,disclosure_version,granted) VALUES (%s,%s,true)", (account, DISCLOSURE_VERSION))
        monkeypatch.setitem(TEMPLATES["pedestal_spin"], "prompt", "Changed catalogue after admission")
        def generate(request, *, account_id):
            assert request.prompt == frozen and account_id == str(account)
            calls.append(True)
            return image.getvalue()
        def review(root, exports):
            reviews.append(exports)
            return {"policyAllowed": True, "qualityPassed": True, "offerFree": True}
        try:
            return worker.process_one(database_url, owner, queue, photo_generate=generate,
                estimated_cost_microusd=7, video_review=review)
        finally:
            with psycopg.connect(database_url) as connection:
                connection.execute("DELETE FROM app.ai_consent WHERE account_id=%s", (account,))
                connection.execute("DELETE FROM app.provider_budget_holds WHERE attempt_id IN (SELECT a.id FROM app.job_attempts a JOIN app.job_runs r ON r.id=a.run_id WHERE r.job_id=%s)", (job,))
    monkeypatch.setattr(test_photo_flow, "process_one", process)
    # Reuse the actual upload/create/private-download/idempotency/account-isolation assertions.
    test_photo_flow.test_photo_api_queue_worker_download_and_replay(monkeypatch, tmp_path)
    assert calls == [True] and len(reviews) == 2


@pytest.mark.parametrize("quality", [True, False])
def test_photo_publication_recovery_reuses_generation_and_review(provider_job, monkeypatch, tmp_path, quality):
    from admaker import creative_planning

    account, job, reservation, queue = provider_job
    monkeypatch.setenv("PHOTO_DAILY_BUDGET_MICROUSD", "100000000000")
    monkeypatch.setenv("PUBLISH_PRIVATE_OUTPUTS", "true")
    settings = {"outputKind": "photo", "structuredPlanning": True, "preparedPhotoPrompt": "Soft light", "photoModel": PHOTO_MODEL, "renderPlatforms": ["feed_square"]}
    with psycopg.connect(URL) as connection:
        connection.execute("UPDATE app.jobs SET settings=%s WHERE id=%s", (Jsonb(settings), job))
        inflight = connection.execute("SELECT count(*) FROM app.media_review_budget WHERE state='unconfirmed'").fetchone()[0]
    for key, value in {"MEDIA_REVIEW_MODEL": "gemini-fixture", "MEDIA_REVIEW_ESTIMATE_MICROUSD": "1",
        "MEDIA_REVIEW_DAILY_BUDGET_MICROUSD": "1000000000", "MEDIA_REVIEW_MAX_CALLS_PER_RUN": "10",
        "MEDIA_REVIEW_MAX_CONCURRENT_CALLS": str(inflight + 1)}.items():
        monkeypatch.setenv(key, value)
    plans = []
    original_plan = creative_planning.plan_product
    def plan(messages, **kwargs):
        plans.append(True)
        return {"product_summary": "Blue product", "creative_direction": "Soft shadows"}
    monkeypatch.setattr(creative_planning, "plan_product", lambda *args: original_plan(*args, invoke=plan))
    generated, reviewed, published = [], [], []
    def generate(*args, **kwargs):
        assert args[0].prompt == "Soft light Product summary: Blue product Creative adaptation: Soft shadows"
        generated.append(True)
        return (tmp_path / "test.png").read_bytes()
    def review(root, exports):
        reviewed.append(True)
        return {"policyAllowed": True, "qualityPassed": True if "input" in exports else quality, "offerFree": True}
    def publish(*args):
        published.append(True)
        if len(published) == 1:
            raise CloudPublicationPending("fixture output transfer interrupted")
    monkeypatch.setattr("admaker.cloud_objects.publish_job_outputs", publish)
    options = dict(photo_generate=generate, estimated_cost_microusd=7, video_review=review)
    try:
        assert worker.process_one(URL, "photo-first", queue, **options)
        with psycopg.connect(URL) as connection:
            assert connection.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("held",)
            run = connection.execute("SELECT active_run_id FROM app.jobs WHERE id=%s", (job,)).fetchone()[0]
            manifest = connection.execute("SELECT result FROM app.job_stages WHERE run_id=%s AND stage_key='provider_compose'", (run,)).fetchone()[0]
            connection.execute("UPDATE app.job_runs SET next_work_at=clock_timestamp()-interval '1 second' WHERE id=%s", (run,))
        target = (tmp_path / manifest["feed_square"]["key"]).resolve()
        assert target.is_relative_to(tmp_path.resolve())
        before = target.read_bytes()
        target.unlink()  # Simulate loss of the local cache, not the durable photo receipt.
        assert worker.recover_expired_runs(URL, queue, str(job)) == 1
        assert worker.process_one(URL, "photo-recovered", queue, **options)
        assert target.read_bytes() == before
        assert len(plans) == 1 and len(generated) == 1 and len(reviewed) == 2 and len(published) == 2
        with psycopg.connect(URL) as connection:
            assert connection.execute("SELECT state FROM app.jobs WHERE id=%s", (job,)).fetchone() == ("delivered" if quality else "awaiting_user_decision",)
            assert connection.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("consumed" if quality else "held",)
            assert connection.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (1 if quality else 0,)
    finally:
        with psycopg.connect(URL) as connection:
            connection.execute("DELETE FROM app.media_review_budget WHERE run_id IN (SELECT id FROM app.job_runs WHERE job_id=%s)", (job,))
            connection.execute("DELETE FROM app.provider_budget_holds WHERE attempt_id IN (SELECT id FROM app.job_attempts WHERE run_id IN (SELECT id FROM app.job_runs WHERE job_id=%s))", (job,))
