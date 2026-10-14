"""Documenter — the orchestrator's ``ProgressLoggingCallbackHandler`` pattern
verbatim (PLAN.md "Observability"). NOT an LLM agent: a deterministic
cross-cutting concern registered once at graph invocation
(``config={"callbacks": [handler]}``), never touched per-node.

Scoping: only the 8 pipeline node checkpoints (plus the ladder gate nodes)
on the watch-list are logged. Each event carries the per-stage
``cost_cents`` so spend per job is queryable from day one.
"""

from __future__ import annotations

import datetime
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

# Fixed watch-list: the 8 pipeline nodes + the ladder gate nodes.
WATCHED_CHECKPOINTS = frozenset(
    {
        "intake_validation",
        "image_cleanup",
        "style_planner",
        "human_checkpoint",
        "video_generation",
        "post_processing",
        "qa_review",
        "delivery",
        "user_decision",
    }
)


class ProgressLoggingCallbackHandler(BaseCallbackHandler):
    """Fans each watched checkpoint out to every configured sink.

    Sinks are objects with ``emit(event: dict) -> None`` (see sinks.py).
    Sink failures are swallowed — observability must never break a run.
    """

    def __init__(self, sinks: list, watch_list: frozenset[str] = WATCHED_CHECKPOINTS):
        self._sinks = sinks
        self._watch_list = watch_list

    @staticmethod
    def _node_name(kwargs: dict, serialized: dict | None = None) -> str | None:
        metadata = kwargs.get("metadata") or {}
        name = kwargs.get("name") or metadata.get("langgraph_node")
        if not name and serialized:
            name = serialized.get("name")
        return name

    def _emit(self, event: dict) -> None:
        for sink in self._sinks:
            try:
                sink.emit(event)
            except Exception:  # noqa: BLE001 — observability must not raise
                pass

    def _make_event(
        self, checkpoint: str, status: str, detail: str = "", cost_cents: dict | None = None
    ) -> dict:
        return {
            "checkpoint": checkpoint,
            "status": status,
            "detail": detail,
            "cost_cents": cost_cents or {},
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        name = self._node_name(kwargs)
        if name in self._watch_list:
            detail = ""
            cost = {}
            if isinstance(outputs, dict):
                cost = outputs.get("cost_cents") or {}
                status = outputs.get("status")
                if status is not None:
                    detail = f"status={status}"
            self._emit(self._make_event(name, "ok", detail, cost))

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        name = self._node_name(kwargs)
        if name in self._watch_list:
            self._emit(self._make_event(name, f"error: {error}"))
