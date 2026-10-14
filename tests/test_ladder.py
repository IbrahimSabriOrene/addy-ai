"""The cost-aware ladder, per PLAN.md "Cost-aware retry ladder"."""

from admaker.config import MAX_AUTO_REGENS, POST_PROC_CAP
from admaker.ladder import (
    LadderAction,
    TechnicalAction,
    on_paid_failure,
    on_technical_failure,
    paid_call_cap,
    user_regen_allowed,
)


def test_cap_is_first_call_plus_auto_regens():
    assert paid_call_cap() == 1 + MAX_AUTO_REGENS


def test_paid_failure_regens_while_under_cap():
    # First call failed (1 submitted) -> spend an automatic regen.
    assert on_paid_failure(1).action is LadderAction.REGEN
    assert on_paid_failure(2).action is LadderAction.REGEN


def test_paid_failure_at_cap_asks_the_user():
    # 1 initial + MAX_AUTO_REGENS submitted -> budget spent, human decides.
    assert on_paid_failure(1 + MAX_AUTO_REGENS).action is LadderAction.USER_DECISION


def test_granted_extra_lifts_cap_by_exactly_one():
    at_cap = 1 + MAX_AUTO_REGENS
    # Without a grant: user decision. With one grant: one more paid call.
    assert on_paid_failure(at_cap, extra_regens_granted=0).action is (
        LadderAction.USER_DECISION
    )
    assert on_paid_failure(at_cap, extra_regens_granted=1).action is LadderAction.REGEN
    # ...but only one — the next failure returns to the human.
    assert on_paid_failure(at_cap + 1, extra_regens_granted=1).action is (
        LadderAction.USER_DECISION
    )


def test_technical_failure_reruns_while_under_cap():
    assert on_technical_failure(1) is TechnicalAction.RERUN
    assert on_technical_failure(POST_PROC_CAP - 1) is TechnicalAction.RERUN


def test_technical_failure_escalates_at_cap():
    assert on_technical_failure(POST_PROC_CAP) is TechnicalAction.ESCALATE


def test_user_regen_allowance_is_a_separate_counter():
    assert user_regen_allowed(0, allowance=1) is True
    assert user_regen_allowed(1, allowance=1) is False
    assert user_regen_allowed(2, allowance=3) is True
