"""End-to-end routing through the compiled graph with scripted fakes.

Exercises every route in the PLAN.md topology diagram offline: intake
reject, the happy fast path, the cleanup cache, the human checkpoint (accept
and new-direction), the video-failure and content-QA regen loops, the
technical free-rerun loop, and the budget-exhausted user decision (accept /
spend_more / abort).
"""

from __future__ import annotations

from conftest import (
    INTAKE_REJECT,
    QA_FAIL,
    QA_PASS,
    ScriptedGate,
    ScriptedRunner,
    happy_runners,
    initial_state,
    make_harness,
)
from admaker.config import EXTRA_REGENS, VIDEO_GEN
from admaker.graph import run_job
from admaker.services import FakeCompositor, FakeImageProbe, FakeVideoService

FAST = {"fast_mode": True}
NORMAL = {"fast_mode": False}


def run(h, gate=None, **state_overrides):
    gate = gate or ScriptedGate()
    return run_job(h.app, initial_state(**state_overrides), gate, thread_id="t"), gate


# -- intake -----------------------------------------------------------------

def test_intake_rejects_low_resolution():
    h = make_harness(probe=FakeImageProbe(result={
        "width": 100, "height": 100, "blur_score": 0.1, "format": "PNG"
    }))
    result, _ = run(h)
    assert result["status"] == "needs_reshoot"
    assert "resolution" in result["feedback"][0]
    # Never paid for cleanup or video.
    assert h.cleaner.calls == []
    assert h.video.submits == []


def test_intake_rejects_when_no_product_visible():
    runners = happy_runners()
    runners["intake"] = ScriptedRunner(INTAKE_REJECT)
    h = make_harness(runners=runners)
    result, _ = run(h)
    assert result["status"] == "needs_reshoot"
    assert h.video.submits == []


# -- happy path -------------------------------------------------------------

def test_happy_fast_path_delivers(harness):
    result, gate = run(harness)
    assert result["status"] == "delivered"
    assert "tiktok" in result["manifest"]
    assert result["assets"]["composited_tiktok"].endswith("#tiktok")
    assert result["attempt_count"][VIDEO_GEN] == 1
    # Fast mode: the style checkpoint is never shown.
    assert gate.style_calls == []
    # One QA content report, passed.
    content = [r for r in result["qa_reports"] if r["tier"] == "content"]
    assert content and content[-1]["passed"]


def test_cost_is_tracked_per_stage(harness):
    result, _ = run(harness)
    assert result["cost_cents"][VIDEO_GEN] > 0
    assert result["cost_cents"]["cleanup"] > 0


def test_cleanup_is_cached_across_restyle():
    # Two jobs, same source image, shared content-hash cache: cleanup runs
    # once (PLAN.md: a re-style never pays for cleanup twice).
    cache: dict = {}
    h1 = make_harness(cleanup_cache=cache)
    run(h1)
    h2 = make_harness(cleanup_cache=cache)
    run(h2)
    assert len(h1.cleaner.calls) + len(h2.cleaner.calls) == 1


# -- human checkpoint -------------------------------------------------------

def test_normal_mode_shows_checkpoint_then_generates():
    h = make_harness()
    gate = ScriptedGate(style_responses=[{"choice": "pedestal_spin"}])
    result, gate = run(h, gate=gate, **NORMAL)
    assert result["status"] == "delivered"
    assert len(gate.style_calls) == 1
    # Checkpoint fired BEFORE the first paid video call.
    assert h.video.submits and result["attempt_count"][VIDEO_GEN] == 1


def test_checkpoint_new_direction_replans_without_paying():
    h = make_harness()
    gate = ScriptedGate(
        style_responses=[{"direction": "make it warmer"}, {"choice": "pedestal_spin"}]
    )
    result, gate = run(h, gate=gate, **NORMAL)
    assert result["status"] == "delivered"
    # Checkpoint shown twice; planner re-ran; still only one paid video call.
    assert len(gate.style_calls) == 2
    assert len(h.runners["style_planner"].calls) == 2
    assert result["attempt_count"][VIDEO_GEN] == 1
    # The direction reached the re-plan as feedback.
    assert any("warmer" in f for f in result["feedback"])


# -- paid regen loops -------------------------------------------------------

def test_video_failure_triggers_automatic_regen():
    h = make_harness(video=FakeVideoService(outcomes=["failed", "completed"]))
    result, _ = run(h, **FAST)
    assert result["status"] == "delivered"
    assert result["attempt_count"][VIDEO_GEN] == 2  # failed call + successful regen


def test_video_timeout_counts_as_a_paid_attempt():
    from admaker.config import AdMakerConfig

    h = make_harness(
        video=FakeVideoService(outcomes=["processing", "completed"]),
        config=AdMakerConfig(poll_max_attempts=3),
    )
    result, _ = run(h, **FAST)
    assert result["status"] == "delivered"
    assert result["attempt_count"][VIDEO_GEN] == 2


def test_content_qa_failure_triggers_automatic_regen():
    runners = happy_runners()
    runners["qa_content"] = ScriptedRunner(QA_FAIL, QA_PASS)
    h = make_harness(runners=runners)
    result, _ = run(h, **FAST)
    assert result["status"] == "delivered"
    assert result["attempt_count"][VIDEO_GEN] == 2


# -- budget-exhausted user decision -----------------------------------------

def test_budget_exhausted_user_accepts_best():
    runners = happy_runners()
    runners["qa_content"] = ScriptedRunner(QA_FAIL)  # never passes content QA
    h = make_harness(runners=runners)
    gate = ScriptedGate(budget_responses=[{"action": "accept"}])
    result, gate = run(h, gate=gate, **FAST)
    assert result["status"] == "delivered"
    # 1 initial + 2 automatic regens = 3 paid calls, then the human decided.
    assert result["attempt_count"][VIDEO_GEN] == 3
    assert len(gate.budget_calls) == 1
    assert gate.budget_calls[0]["best"] is not None


def test_budget_exhausted_spend_more_grants_exactly_one_call():
    runners = happy_runners()
    runners["qa_content"] = ScriptedRunner(QA_FAIL)
    h = make_harness(runners=runners)
    gate = ScriptedGate(
        budget_responses=[{"action": "spend_more"}, {"action": "accept"}]
    )
    result, gate = run(h, gate=gate, **FAST)
    assert result["status"] == "delivered"
    assert result["attempt_count"][EXTRA_REGENS] == 1
    assert result["attempt_count"][VIDEO_GEN] == 4  # 3 + one granted extra
    assert len(gate.budget_calls) == 2


def test_budget_exhausted_user_aborts():
    runners = happy_runners()
    runners["qa_content"] = ScriptedRunner(QA_FAIL)
    h = make_harness(runners=runners)
    gate = ScriptedGate(budget_responses=[{"action": "abort"}])
    result, _ = run(h, gate=gate, **FAST)
    assert result["status"] == "aborted"
    assert result["attempt_count"][VIDEO_GEN] == 3


# -- technical QA tier (free re-runs) ---------------------------------------

def test_technical_failure_reruns_compositing_for_free():
    h = make_harness(compositor=FakeCompositor(bad_first=True))
    result, _ = run(h, **FAST)
    assert result["status"] == "delivered"
    # Compositor re-ran once; no paid video regen was spent.
    assert len(h.compositor.calls) == 2
    assert result["attempt_count"][VIDEO_GEN] == 1
    assert any(r["tier"] == "technical" and not r["passed"] for r in result["qa_reports"])


def test_unrecoverable_technical_failure_escalates_to_user():
    h = make_harness(compositor=FakeCompositor(bad_all=True))
    gate = ScriptedGate(budget_responses=[{"action": "accept"}])
    result, gate = run(h, gate=gate, **FAST)
    # After POST_PROC_CAP free re-runs, it hands off to the user decision.
    from admaker.config import POST_PROC_CAP

    assert len(h.compositor.calls) == POST_PROC_CAP
    assert len(gate.budget_calls) == 1
    # Still no paid video regen was burned on a compositing problem.
    assert result["attempt_count"][VIDEO_GEN] == 1
