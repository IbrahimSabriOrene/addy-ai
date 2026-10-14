"""Graph topology (PLAN.md "Graph topology") and the run driver.

Linear spine with two loops and two human gates:

    START -> intake_validation --ok--> image_cleanup -> style_planner
    style_planner --fast/already-generated--> video_generation
    style_planner --normal, first pass--> human_checkpoint
    human_checkpoint --approved--> video_generation
    human_checkpoint --new direction--> style_planner
    video_generation --> post_processing -> qa_review
    video_generation --failed/timeout--> ladder
    qa_review --pass--> delivery
    qa_review --technical fail--> post_processing        (free)
    qa_review --content fail--> ladder                   (paid)
    ladder --regen--> style_planner
    ladder --budget spent--> user_decision (accept | spend_more | abort)
    delivery -> END

Routing convention: nodes whose output decides the route return
``Command(update=..., goto=...)``; the only plain conditional edge is the
deterministic fast-mode gate (``route_mode``).

Everything external is injectable — the three LLM runners and the
image/video/compositing adapters and the AssetStore — so tests drive every
route offline (see tests/) and the real back-ends are a swap at build time.
"""

from __future__ import annotations

import time
from typing import Callable

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from admaker.config import AdMakerConfig
from admaker.nodes import make_nodes
from admaker.state import AdMakerState


WORKER_GRAPH_VERSION = "worker-fixture-v1"


def build_worker_graph(render: Callable, checkpointer):
    """Durable worker path. Paid retries and CLI human gates are not implicit."""
    from admaker.state import WorkerState

    graph = StateGraph(WorkerState)
    graph.add_node("render", render)
    graph.add_edge(START, "render")
    graph.add_edge("render", END)
    return graph.compile(checkpointer=checkpointer)


def default_runners(config: AdMakerConfig | None = None, *, account_id: str | None = None) -> dict[str, Callable]:
    """Real Gemini-backed runners built from AgentSpecs, lazily imported."""
    from admaker.agents import prompts
    from admaker.agents.spec import AgentSpec, build_agent_runner, build_vision_runner

    config = config or AdMakerConfig()
    models = config.models

    intake_vision = build_vision_runner(
        AgentSpec("intake", models["intake"], prompts.INTAKE), account_id=account_id
    )
    qa_vision = build_vision_runner(
        AgentSpec("qa_content", models["qa_content"], prompts.QA_CONTENT), account_id=account_id
    )
    planner_text = build_agent_runner(
        AgentSpec("style_planner", models["style_planner"], prompts.STYLE_PLANNER), account_id=account_id
    )
    return {
        # Uniform ``runner(prompt, image_url=None)`` signature.
        "intake": lambda prompt, image_url=None: intake_vision(prompt, image_url),
        "qa_content": lambda prompt, image_url=None: qa_vision(prompt, image_url),
        "style_planner": lambda prompt, image_url=None: planner_text(prompt),
    }


def default_services(config: AdMakerConfig | None = None) -> dict:
    """Real external adapters. Stubs where a live account is needed — verify
    against current Decart docs (PLAN.md decision #6) before wiring."""
    from admaker.assets import LocalDiskAssetStore
    from admaker.services import pillow_probe

    config = config or AdMakerConfig()
    return {
        "image_probe": pillow_probe,
        # image_cleaner / video_service / compositor need the real Decart +
        # FFmpeg integrations; left unset so an incomplete wiring fails loudly
        # rather than silently no-op.
        "asset_store": LocalDiskAssetStore(config.asset_root),
    }


def build_graph(
    runners: dict[str, Callable] | None = None,
    *,
    account_id: str | None = None,
    config: AdMakerConfig | None = None,
    checkpointer=None,
    image_probe: Callable | None = None,
    image_cleaner: Callable | None = None,
    video_service=None,
    compositor: Callable | None = None,
    asset_store=None,
    cleanup_cache: dict | None = None,
    sleep: Callable[[float], None] = time.sleep,
):
    """Compile the production graph.

    Injectables mirror the orchestrator's ``build_graph``: ``runners`` (fakes
    in tests), the four service adapters, the ``AssetStore``, a
    ``cleanup_cache`` (content-hash keyed), the ``checkpointer`` (in-memory ->
    Postgres is a swap here, per decision #3), and ``sleep`` (so poll backoff
    never waits in tests).
    """
    config = config or AdMakerConfig()
    if runners is None:
        runners = default_runners(config, account_id=account_id)

    services = default_services(config) if any(
        x is None for x in (image_probe, asset_store)
    ) else {}
    image_probe = image_probe or services.get("image_probe")
    asset_store = asset_store or services.get("asset_store")

    nodes = make_nodes(
        runners,
        image_probe=image_probe,
        image_cleaner=image_cleaner,
        video_service=video_service,
        compositor=compositor,
        asset_store=asset_store,
        cleanup_cache=cleanup_cache,
        poll_max_attempts=config.poll_max_attempts,
        sleep=sleep,
    )
    route_mode = nodes.pop("route_mode")

    graph = StateGraph(AdMakerState)
    for name, fn in nodes.items():
        graph.add_node(name, fn)

    graph.add_edge(START, "intake_validation")
    # intake_validation -> {image_cleanup | END} via Command
    graph.add_edge("image_cleanup", "style_planner")
    # style_planner -> {video_generation | human_checkpoint}: deterministic
    # fast-mode gate, the one plain conditional edge.
    graph.add_conditional_edges(
        "style_planner", route_mode, ["video_generation", "human_checkpoint"]
    )
    # human_checkpoint, video_generation, qa_review, user_decision all route
    # via Command(goto=...).
    graph.add_edge("post_processing", "qa_review")
    graph.add_edge("delivery", END)

    return graph.compile(checkpointer=checkpointer or InMemorySaver())


def run_job(
    app,
    initial_state: AdMakerState,
    gate,
    *,
    thread_id: str | None = None,
    callbacks: list | None = None,
):
    """Drive a job to a terminal state, servicing the two human gates.

    ``gate`` implements ``HumanGate`` (channels/base.py). Correlation is by
    ``thread_id == job_id`` — the same interrupt/resume mechanics as the
    orchestrator's escalations, with the mobile app playing Telegram's role.
    Fast-mode jobs hit no interrupts and return directly.
    """
    thread_id = thread_id or initial_state.get("job_id") or "job-1"
    graph_config: dict = {"configurable": {"thread_id": thread_id}}
    if callbacks:
        graph_config["callbacks"] = callbacks

    result = app.invoke(initial_state, config=graph_config)
    while "__interrupt__" in result:
        payloads = []
        for intr in result["__interrupt__"]:
            ctx = intr.value
            kind = ctx.get("kind")
            if kind == "style_choice":
                payloads.append(gate.choose_style(ctx))
            elif kind == "budget_decision":
                payloads.append(gate.decide_budget(ctx))
            else:
                payloads.append({})
        # One interrupt per superstep in this linear graph; resume with its
        # payload.
        result = app.invoke(Command(resume=payloads[0]), config=graph_config)
    return result


__all__ = ["build_graph", "run_job", "default_runners", "default_services"]
