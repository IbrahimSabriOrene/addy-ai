"""The cost-aware retry ladder as pure functions (no LLM, no I/O).

The orchestrator's ladder protects *time*; this one protects *money*
(PLAN.md "Cost-aware retry ladder"). Video generation is the metered step,
so the ladder counts **paid video-gen calls**, not failures in general.

Per job:

1. Automatic content-QA regens: max ``MAX_AUTO_REGENS``. A content-tier QA
   failure (or a failed/timed-out video job) routes back to ``style_planner``
   for a re-plan and a new paid video call — as long as the paid-call budget
   isn't spent. ``attempt_count[VIDEO_GEN]`` increments on every *submitted*
   job (including timeouts — we may still be billed).
2. Budget exhausted -> a user decision, never a silent failure. The graph
   ``interrupt()``s with the best attempt so far: accept it / spend one more
   paid regen / abort. "Human input is a hint" — the user chooses; the
   system never burns unbounded spend.
3. Each granted "spend one more" lifts the cap by exactly one paid call
   (``EXTRA_REGENS``), so control returns to the human after every extra
   call, not just at the automatic cap.
4. Technical failures are FREE retries (FFmpeg re-runs) with their own cap
   (``POST_PROC_CAP``); they never consume the video-gen budget. Only a
   newly submitted paid job does.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from admaker.config import MAX_AUTO_REGENS, POST_PROC_CAP


class LadderAction(Enum):
    REGEN = "regen"                  # re-plan + a new paid video call
    USER_DECISION = "user_decision"  # budget spent; ask the human about money


@dataclass(frozen=True)
class LadderDecision:
    action: LadderAction


def paid_call_cap(extra_regens_granted: int = 0) -> int:
    """Total paid video-gen calls allowed before the user must decide:
    the first call + the automatic regens + any human-granted extras."""
    return 1 + MAX_AUTO_REGENS + extra_regens_granted


def on_paid_failure(
    video_gen_attempts: int, extra_regens_granted: int = 0
) -> LadderDecision:
    """Decide what happens when a paid path fails (a failed/timed-out video
    job, or a content-tier QA rejection of a generated clip).

    ``video_gen_attempts`` is the number of paid jobs already SUBMITTED
    (>= 1 whenever this is reached). While under the cap we spend another
    automatic regen; once the cap is hit the human decides.
    """
    if video_gen_attempts < paid_call_cap(extra_regens_granted):
        return LadderDecision(LadderAction.REGEN)
    return LadderDecision(LadderAction.USER_DECISION)


class TechnicalAction(Enum):
    RERUN = "rerun"        # free FFmpeg re-run
    ESCALATE = "escalate"  # something structural; hand to the user decision


def on_technical_failure(post_proc_attempts: int) -> TechnicalAction:
    """Technical QA failures are free re-runs, but bounded — a compositor
    that keeps producing a bad master is structural, not transient, so after
    ``POST_PROC_CAP`` re-runs we escalate instead of looping forever.

    ``post_proc_attempts`` counts compositing passes already made (>= 1 here).
    """
    if post_proc_attempts < POST_PROC_CAP:
        return TechnicalAction.RERUN
    return TechnicalAction.ESCALATE


def user_regen_allowed(user_regens_used: int, allowance: int) -> bool:
    """Post-delivery, user-triggered regenerations (a SEPARATE counter from
    the automatic video-gen budget) are capped by the account tier's
    allowance. Enforced when the app re-invokes the graph on the same thread.
    """
    return user_regens_used < allowance
