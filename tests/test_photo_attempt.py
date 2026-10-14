import io
import uuid

import psycopg
import pytest
from PIL import Image

from admaker.media_review import MediaReviewPending
from admaker.photo_attempt import generate_photo_attempt
from admaker.photo_provider import PhotoOutputRejected
from admaker.veo import SubmissionUnknown
from test_provider_graph import provider_job
from test_worker_leases import URL, queued_job


@pytest.fixture
def photo_attempt(provider_job, monkeypatch):
    account, job, reservation, _ = provider_job
    run, attempt = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setenv("PHOTO_DAILY_BUDGET_MICROUSD", "100000000000")
    monkeypatch.setenv("PHOTO_MAX_CONCURRENT_OPERATIONS", "10")
    with psycopg.connect(URL) as connection:
        connection.execute("UPDATE app.jobs SET state='running',settings='{" + '"outputKind":"photo"' + "}'::jsonb WHERE id=%s", (job,))
        connection.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state,lease_owner,lease_until,fence) VALUES (%s,%s,1,%s,'running','photo',clock_timestamp()+interval '5 minutes',1)", (run, job, str(run)))
        connection.execute("UPDATE app.jobs SET active_run_id=%s WHERE id=%s", (run, job))
        connection.execute("INSERT INTO app.job_attempts(id,run_id,reservation_id,sequence,state,request_hash) VALUES (%s,%s,%s,1,'running','fixture')", (attempt, run, reservation))
    yield account, job, run, attempt
    with psycopg.connect(URL) as connection:
        connection.execute("DELETE FROM app.provider_budget_holds WHERE attempt_id=%s", (attempt,))


def test_photo_commit_precedes_call_and_exact_output_replays(photo_attempt, tmp_path):
    account, _, _, attempt = photo_attempt
    calls, reviews = [], []
    image = io.BytesIO()
    Image.new("RGB", (32, 32), "blue").save(image, format="PNG")
    output = image.getvalue()
    def reviewer(root, manifest):
        reviews.append(manifest)
        return {"policyAllowed": True, "qualityPassed": True, "offerFree": True}
    def generate(request, *, account_id):
        assert account_id == str(account)
        assert request.image_bytes == (tmp_path / "test.png").read_bytes()
        with psycopg.connect(URL) as connection:
            assert connection.execute("SELECT provider_state FROM app.job_attempts WHERE id=%s", (attempt,)).fetchone() == ("submitting",)
            assert connection.execute("SELECT media_kind,amount_microusd FROM app.provider_budget_holds WHERE attempt_id=%s", (attempt,)).fetchone() == ("photo", 7)
        calls.append(True)
        return output
    args = (URL, attempt, "photo", 1, "Soft white background", "1:1", 7, reviewer)
    assert generate_photo_attempt(*args, generate=generate) == output
    assert generate_photo_attempt(*args, generate=generate) == output
    assert calls == [True] and len(reviews) == 1
    with pytest.raises(MediaReviewPending, match="changed"):
        generate_photo_attempt(URL, attempt, "photo", 1, "Different direction", "1:1", 7, reviewer, generate=generate)
    with psycopg.connect(URL) as connection:
        assert connection.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
        assert connection.execute("SELECT data FROM app.photo_attempt_outputs WHERE attempt_id=%s", (attempt,)).fetchone() == (output,)
        connection.execute("DELETE FROM app.job_attempts WHERE id=%s", (attempt,))
        assert connection.execute("SELECT count(*) FROM app.photo_attempt_outputs WHERE attempt_id=%s", (attempt,)).fetchone() == (0,)


@pytest.mark.parametrize("crash", [False, True])
def test_lost_photo_response_never_reissues_paid_call(photo_attempt, crash):
    _, _, run, attempt = photo_attempt
    calls = []
    class Crash(BaseException):
        pass
    def generate(*args, **kwargs):
        calls.append(True)
        raise Crash() if crash else TimeoutError("response lost")
    def reviewer(*args):
        return {"policyAllowed": True, "qualityPassed": True, "offerFree": True}
    with pytest.raises(Crash if crash else SubmissionUnknown):
        generate_photo_attempt(URL, attempt, "photo", 1, "Soft light", "1:1", 7, reviewer, generate=generate)
    with psycopg.connect(URL) as connection:
        connection.execute("UPDATE app.job_runs SET fence=2 WHERE id=%s", (run,))
    with pytest.raises(SubmissionUnknown):
        generate_photo_attempt(URL, attempt, "photo", 2, "Soft light", "1:1", 7, reviewer, generate=generate)
    assert calls == [True]
    with psycopg.connect(URL) as connection:
        assert connection.execute("SELECT provider_state FROM app.job_attempts WHERE id=%s", (attempt,)).fetchone() == ("submission_unknown",)
        assert connection.execute("SELECT count(*) FROM app.provider_budget_holds WHERE attempt_id=%s", (attempt,)).fetchone() == (1,)


def test_rejected_photo_is_terminal_without_success_or_retry(photo_attempt):
    _, _, _, attempt = photo_attempt
    calls = []
    def generate(*args, **kwargs):
        calls.append(True)
        return b"not a generated image"
    def reviewer(*args):
        return {"policyAllowed": True, "qualityPassed": True, "offerFree": True}
    for _ in range(2):
        with pytest.raises(PhotoOutputRejected):
            generate_photo_attempt(URL, attempt, "photo", 1, "Soft light", "1:1", 7, reviewer, generate=generate)
    assert calls == [True]
    with psycopg.connect(URL) as connection:
        assert connection.execute("SELECT provider_state FROM app.job_attempts WHERE id=%s", (attempt,)).fetchone() == ("failed",)
        assert connection.execute("SELECT count(*) FROM app.photo_attempt_outputs WHERE attempt_id=%s", (attempt,)).fetchone() == (0,)
