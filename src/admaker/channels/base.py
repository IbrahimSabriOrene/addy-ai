"""Channel interfaces (copied from the orchestrator, PLAN.md "Human-in-the-
loop points").

Interface segregation: the Documenter only ever needs fire-and-forget
``NotificationChannel``; the interactive ``HumanGate`` services the two
graph interrupts. The same mobile-app back-end can implement both, but
observability is never coupled to the interactive machinery.

Both interrupts resume via ``Command(resume=payload)`` with correlation
``thread_id == job_id`` — exactly the orchestrator's escalation mechanics.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class NotificationChannel(Protocol):
    def notify(self, message: str) -> None:
        """One-way, fire-and-forget."""
        ...


@runtime_checkable
class HumanGate(Protocol):
    def choose_style(self, context: dict) -> dict:
        """``human_checkpoint``: given style candidates, return either
        ``{"choice": "<candidate_id>"}`` or
        ``{"direction": "<note>"}`` to re-plan."""
        ...

    def decide_budget(self, context: dict) -> dict:
        """``user_decision``: given the best attempt so far, return one of
        ``{"action": "accept"}`` / ``{"action": "spend_more"}`` /
        ``{"action": "abort"}``."""
        ...


class ConsoleChannel:
    """Local-dev implementation of both interfaces (stdin/stdout)."""

    def notify(self, message: str) -> None:
        print(f"[admaker] {message}")

    def choose_style(self, context: dict) -> dict:
        print(f"[admaker] style candidates: {context.get('candidates')}")
        raw = input("[admaker] choice id (or 'note: ...')> ").strip()
        if raw.startswith("note:"):
            return {"direction": raw[len("note:"):].strip()}
        return {"choice": raw}

    def decide_budget(self, context: dict) -> dict:
        print(f"[admaker] budget exhausted. best so far: {context.get('best')}")
        raw = input("[admaker] accept / spend_more / abort> ").strip() or "accept"
        return {"action": raw}
