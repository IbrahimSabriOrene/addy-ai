import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from admaker import worker, photo_graph
from admaker.photo_provider import PHOTO_MODEL
from admaker.run_compatibility import pause_incompatible_run, resume_compatible_run
from admaker.submission_review import resolve_submission
from test_provider_graph import provider_job
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("resolution", ["compatible", "verified_no_output", "goodwill_release"])
def test_photo_operator_preserves_attempt_and_finances(provider_job, monkeypatch, tmp_path, resolution):
    account, job, reservation, queue = provider_job
    monkeypatch.setenv("PHOTO_DAILY_BUDGET_MICROUSD", "100000000000")
    with psycopg.connect(URL) as connection:
        connection.execute("UPDATE app.jobs SET settings=%s WHERE id=%s", (Jsonb({"outputKind": "photo",
            "photoProvider": True, "preparedPhotoPrompt": "Soft light", "photoModel": PHOTO_MODEL,
            "renderPlatforms": ["feed_square"]}), job))
    calls = []
    def generate(*args, **kwargs):
        calls.append(True)
        if resolution != "compatible":
            raise TimeoutError("Unknown photo outcome")
        return (tmp_path / "test.png").read_bytes()
    options = dict(photo_generate=generate, estimated_cost_microusd=7,
        video_review=lambda *args: {"policyAllowed": True, "qualityPassed": True, "offerFree": True})
    try:
        if resolution == "compatible":
            original = photo_graph.run_photo_graph
            def crash(*args):
                raise RuntimeError("Before graph")
            monkeypatch.setattr(photo_graph, "run_photo_graph", crash)
            with pytest.raises(RuntimeError, match="Before graph"):
                worker.process_one(URL, "photo-old", queue, **options)
            with psycopg.connect(URL) as connection:
                run, fence = connection.execute("SELECT id,fence FROM app.job_runs WHERE job_id=%s", (job,)).fetchone()
                message = connection.execute(sql.SQL("SELECT msg_id FROM pgmq.{}").format(sql.Identifier("q_" + queue))).fetchone()[0]
            assert pause_incompatible_run(URL, run, "photo-old", fence, "unsupported", queue, message)
            with pytest.raises(ValueError, match="cannot resume"):
                resume_compatible_run(URL, run, fence, "operator", "Compatible build", "provider", queue)
            with pytest.raises(ValueError, match="dedicated"):
                resume_compatible_run(URL, run, fence, "operator", "Compatible build", "photo")
            args = (URL, run, fence, "operator", "Compatible build", "photo", queue)
            assert resume_compatible_run(*args)
            assert not resume_compatible_run(*args)
            monkeypatch.setattr(photo_graph, "run_photo_graph", original)
            assert worker.process_one(URL, "photo-compatible", queue, **options)
        else:
            assert worker.process_one(URL, "photo-unknown", queue, **options)
            with psycopg.connect(URL) as connection:
                attempt = connection.execute("SELECT a.id FROM app.job_attempts a JOIN app.job_runs r ON r.id=a.run_id WHERE r.job_id=%s", (job,)).fetchone()[0]
            args = (URL, attempt, "operator", resolution, "Independently investigated outcome")
            assert resolve_submission(*args)
            assert resolve_submission(*args)
            assert worker.recover_expired_runs(URL, queue, str(job)) == 0
            assert not worker.process_one(URL, "no-photo-retry", queue, **options)
            with psycopg.connect(URL) as connection:
                assert connection.execute("SELECT provider_state FROM app.job_attempts WHERE id=%s", (attempt,)).fetchone() == ("failed" if resolution == "verified_no_output" else "submission_unknown",)
        with psycopg.connect(URL) as connection:
            assert connection.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("consumed" if resolution == "compatible" else "released",)
            assert connection.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (1 if resolution == "compatible" else 0,)
            assert connection.execute("SELECT count(*) FROM app.job_attempts a JOIN app.job_runs r ON r.id=a.run_id WHERE r.job_id=%s", (job,)).fetchone() == (1,)
        assert calls == [True]
    finally:
        with psycopg.connect(URL) as connection:
            connection.execute("DELETE FROM app.provider_budget_holds WHERE attempt_id IN (SELECT a.id FROM app.job_attempts a JOIN app.job_runs r ON r.id=a.run_id WHERE r.job_id=%s)", (job,))
