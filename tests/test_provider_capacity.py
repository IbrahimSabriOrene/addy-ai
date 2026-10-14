from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
import uuid

from google.genai import types
import psycopg

from admaker.provider_budget import ProviderCapacityBusy, provider_operations_inflight, reserve_provider_budget
from admaker.veo import VeoRequest
from admaker import worker
from test_provider_graph import provider_job, allow_review
from test_worker_leases import URL, queued_job


def test_capacity_serializes_new_submissions(queued_job, monkeypatch):
    account, job, reservation, queue = queued_job
    attempts = [uuid.uuid4(), uuid.uuid4()]
    with psycopg.connect(URL) as c:
        baseline = provider_operations_inflight(c)
        for sequence, attempt in enumerate(attempts, 1):
            run, held = uuid.uuid4(), reservation if sequence == 1 else uuid.uuid4()
            if sequence == 2:
                c.execute("INSERT INTO app.credit_reservations(id,account_id,job_id,amount,state) VALUES (%s,%s,%s,1,'held')", (held, account, job))
            c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state) VALUES (%s,%s,%s,%s,'running')", (run, job, sequence, str(run)))
            c.execute("INSERT INTO app.job_attempts(id,run_id,reservation_id,sequence,state,request_hash) VALUES (%s,%s,%s,1,'running','fixture')", (attempt, run, held))
    monkeypatch.setenv("VEO_DAILY_BUDGET_MICROUSD", "1000000000000")
    monkeypatch.setenv("VEO_MAX_CONCURRENT_OPERATIONS", str(baseline + 1))
    barrier = Barrier(2)

    def submit(attempt):
        barrier.wait(timeout=5)
        try:
            with psycopg.connect(URL) as c:
                reserve_provider_budget(c, attempt, 1)
                c.execute("UPDATE app.job_attempts SET provider_state='submitting' WHERE id=%s", (attempt,))
            return True
        except ProviderCapacityBusy:
            return False
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(submit, attempts)) == [False, True]
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT count(*) FROM app.provider_budget_holds WHERE attempt_id=ANY(%s)", (attempts,)).fetchone() == (1,)
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.provider_budget_holds WHERE attempt_id=ANY(%s)", (attempts,))


def test_deleted_unknown_operation_keeps_slot_and_waiting_worker_resumes_without_charge(provider_job, monkeypatch):
    account, job, reservation, queue = provider_job
    blocker = uuid.uuid4()
    with psycopg.connect(URL) as c:
        baseline = provider_operations_inflight(c)
        c.execute("INSERT INTO app.provider_budget_holds(attempt_id,amount_microusd) VALUES (%s,1)", (blocker,))
        c.execute("INSERT INTO app.deleted_attempt_finances(attempt_id,account_id,reservation_id,credits,reservation_state,provider_state) VALUES (%s,%s,%s,1,'released','submission_unknown')", (blocker, account, uuid.uuid4()))
    monkeypatch.setenv("VEO_DAILY_BUDGET_MICROUSD", "1000000000000")
    monkeypatch.setenv("VEO_MAX_CONCURRENT_OPERATIONS", str(baseline + 1))
    calls = []

    def submit(request, **kwargs):
        calls.append(request)
        return f"operations/{uuid.uuid4()}"
    service = SimpleNamespace(submit=submit, poll=lambda name: types.GenerateVideosOperation(name=name, done=False))
    options = dict(video_service=service, video_request=VeoRequest("Fixture product"), estimated_cost_microusd=400, video_review=allow_review)
    try:
        assert worker.process_one(URL, "capacity-worker", queue, **options)
        assert not calls
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("held",)
            assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
            assert c.execute("SELECT state,next_work_at>now() FROM app.job_runs WHERE job_id=%s", (job,)).fetchone() == ("running", True)
            # Inject a confirmed terminal provider outcome, not a customer goodwill release.
            c.execute("UPDATE app.deleted_attempt_finances SET provider_state='failed' WHERE attempt_id=%s", (blocker,))
            c.execute("UPDATE app.job_runs SET next_work_at=now()-interval '1 second' WHERE job_id=%s", (job,))
        assert worker.recover_expired_runs(URL, queue, str(job)) == 1
        assert worker.process_one(URL, "resumed-worker", queue, **options)
        assert len(calls) == 1
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT count(*) FROM app.job_attempts WHERE run_id IN (SELECT id FROM app.job_runs WHERE job_id=%s)", (job,)).fetchone() == (1,)
            assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.provider_budget_holds WHERE attempt_id=%s OR attempt_id IN (SELECT a.id FROM app.job_attempts a JOIN app.job_runs r ON r.id=a.run_id WHERE r.job_id=%s)", (blocker, job))
            c.execute("DELETE FROM app.deleted_attempt_finances WHERE attempt_id=%s", (blocker,))
