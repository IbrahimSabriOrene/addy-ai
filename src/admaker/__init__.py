"""MobileAdMaker — product screenshot -> social/ad video, as a LangGraph.

Architectural toolkit copied from the AI Orchestrator (typed state with
explicit reducers, a cost-aware retry ladder as pure functions,
``Command(update=..., goto=...)`` for decision-bearing nodes, ``interrupt()``
for human gates, callback-hook observability), applied to a different
product. See PLAN.md.
"""

from __future__ import annotations

__all__ = ["build_graph", "run_job", "AdMakerState"]


def __getattr__(name: str):  # lazy re-exports; keep import side effects light
    if name in ("build_graph", "run_job"):
        from admaker.graph import build_graph, run_job

        return {"build_graph": build_graph, "run_job": run_job}[name]
    if name == "AdMakerState":
        from admaker.state import AdMakerState

        return AdMakerState
    raise AttributeError(name)
