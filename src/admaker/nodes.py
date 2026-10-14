"""Node functions for the production graph.

Control-flow convention (PLAN.md "Routing convention"): nodes whose *output*
decides the route return ``Command(update=..., goto=...)`` so "what happened"
and "what's next" stay atomic; the only plain conditional edge is the cheap
deterministic fast-mode gate (``route_mode``).

Every external touch-point is injected — the three LLM ``runners`` plus the
image/video/compositing service adapters — so the whole topology runs
offline against fakes with zero network (PLAN.md "Next step"). ``RUNNER_NAMES``
lists the LLM runners that must be provided.
"""

from __future__ import annotations

import hashlib
import time
from typing import Callable

from langgraph.graph import END
from langgraph.types import Command, interrupt

from admaker.agents.prompts import INTAKE, QA_CONTENT, STYLE_PLANNER
from admaker.agents.spec import parse_json_verdict
from admaker.config import (
    ALLOWED_FORMATS,
    ASPECT_TOLERANCE,
    COST_CENTS,
    DEFAULT_PLATFORMS,
    EXTRA_REGENS,
    MAX_BLUR_SCORE,
    MIN_RESOLUTION,
    PLATFORM_SPECS,
    POST_PROC,
    VIDEO_GEN,
)
from admaker.ladder import (
    LadderAction,
    TechnicalAction,
    on_paid_failure,
    on_technical_failure,
)
from admaker.presets import resolve_preset
from admaker.services import poll_until_terminal
from admaker.state import AdMakerState

# LLM runners the graph needs. Each is ``runner(prompt, image_url=None) -> str``
# so vision (intake, qa_content) and text (style_planner) share one signature.
RUNNER_NAMES = ("intake", "style_planner", "qa_content")

Runner = Callable[..., str]

# Short human-side prompts; the system prompts (agents/prompts.py) carry the
# actual contract.
_INTAKE_HUMAN = "Assess whether a single clear product is visible in this photo."
_QA_HUMAN = "Review these sampled frames of the generated ad video."


# --------------------------------------------------------------------------
# Small pure helpers
# --------------------------------------------------------------------------

def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _planner_prompt(preset, product: str, platforms: list[str], feedback: list[str]) -> str:
    parts = [
        f"Chosen style preset: {preset.name} ({preset.id})",
        f"Prompt template to fill: {preset.prompt_template}",
        f"Motion params: {preset.motion_params}",
        f"Music mood: {preset.music_mood}",
        f"Safe duration range (seconds): {preset.safe_duration}",
        f"Product: {product}",
        f"Target platforms: {', '.join(platforms)}",
    ]
    if feedback:
        joined = "\n".join(f"- {f}" for f in feedback)
        parts.append(
            "Prior feedback to address (QA failures and/or user regen notes) "
            f"— every item must be addressed:\n{joined}"
        )
    return "\n".join(parts)


def _technical_checks(meta: dict, platforms: list[str]) -> list[str]:
    """Pure-code technical QA tier: duration, aspect, audio present."""
    reasons: list[str] = []
    for p in platforms:
        m = meta.get(p)
        if not m:
            reasons.append(f"{p}: no render produced")
            continue
        spec = PLATFORM_SPECS.get(p)
        if spec:
            if m.get("duration", 0) > spec["max_duration"]:
                reasons.append(
                    f"{p}: duration {m['duration']}s exceeds "
                    f"{spec['max_duration']}s max"
                )
            want = spec["aspect"][0] / spec["aspect"][1]
            h = m.get("height") or 1
            got = m.get("width", 0) / h
            if abs(want - got) > ASPECT_TOLERANCE:
                reasons.append(f"{p}: aspect {got:.3f} != target {want:.3f}")
        if not m.get("has_audio"):
            reasons.append(f"{p}: no audio track")
    return reasons


def _best_content_attempt(state: AdMakerState) -> dict | None:
    reports = [r for r in (state.get("qa_reports") or []) if r.get("tier") == "content"]
    if not reports:
        return None
    return max(reports, key=lambda r: r.get("score", 0.0))


# --------------------------------------------------------------------------
# Node factories
# --------------------------------------------------------------------------

def make_nodes(
    runners: dict[str, Runner],
    *,
    image_probe: Callable[[str], dict],
    image_cleaner: Callable[[str], str],
    video_service,
    compositor: Callable[[str, dict, list[str]], dict],
    asset_store,
    cleanup_cache: dict | None = None,
    poll_max_attempts: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
):
    """Build all node callables around the injected runners and services.

    ``cleanup_cache`` is a dict-like keyed by source-image hash so a re-style
    of the same photo never pays for cleanup twice (PLAN.md image_cleanup).
    ``sleep`` is injected so the video-poll backoff never waits in tests.
    """
    missing = [n for n in RUNNER_NAMES if n not in runners]
    if missing:
        raise ValueError(f"Missing runners: {missing}")
    cache = cleanup_cache if cleanup_cache is not None else {}

    from admaker.config import POLL_MAX_ATTEMPTS

    max_attempts = poll_max_attempts or POLL_MAX_ATTEMPTS

    # -- the cost-aware ladder, applied at both paid-failure sites -----------

    def _paid_failure(
        state: AdMakerState, video_gen_attempts: int, base_update: dict, reason: str
    ) -> Command:
        extra = (state.get("attempt_count") or {}).get(EXTRA_REGENS, 0)
        decision = on_paid_failure(video_gen_attempts, extra)
        update = dict(base_update)
        update["feedback"] = [reason]
        if decision.action is LadderAction.REGEN:
            return Command(update=update, goto="style_planner")
        update["status"] = "awaiting_user_decision"
        return Command(update=update, goto="user_decision")

    # -- 1. intake ----------------------------------------------------------

    def intake_validation(state: AdMakerState) -> Command:
        src = state["source_image_url"]
        probe = image_probe(src)
        reasons: list[str] = []
        if (
            probe.get("width", 0) < MIN_RESOLUTION[0]
            or probe.get("height", 0) < MIN_RESOLUTION[1]
        ):
            reasons.append(
                f"resolution {probe.get('width')}x{probe.get('height')} "
                f"below minimum {MIN_RESOLUTION[0]}x{MIN_RESOLUTION[1]}"
            )
        if probe.get("blur_score", 0.0) > MAX_BLUR_SCORE:
            reasons.append("image too blurry")
        if probe.get("format") not in ALLOWED_FORMATS:
            reasons.append(f"unsupported format {probe.get('format')}")
        if reasons:
            return Command(
                update={"status": "needs_reshoot", "feedback": reasons},
                goto=END,
            )

        verdict = parse_json_verdict(runners["intake"](_INTAKE_HUMAN, src))
        if not verdict.get("product_visible"):
            return Command(
                update={
                    "status": "needs_reshoot",
                    "feedback": [verdict.get("reason", "no clear product")],
                },
                goto=END,
            )
        # Stash the product guess in the style seed so the planner can fill
        # the preset template; the planner overwrites style wholesale but
        # carries product forward.
        return Command(
            update={
                "status": "running",
                "assets": {"source": src},
                "style": {"product": verdict.get("product_guess", "product")},
            },
            goto="image_cleanup",
        )

    # -- 2. image cleanup (cached by source-image hash) ---------------------

    def image_cleanup(state: AdMakerState) -> dict:
        src = state["source_image_url"]
        key = _hash(src)
        cached = cache.get(key)
        if cached is not None:
            return {"assets": {"cleaned_image": cached}, "cost_cents": {"cleanup": 0}}
        cleaned = image_cleaner(src)
        cache[key] = cleaned
        return {
            "assets": {"cleaned_image": cleaned},
            "cost_cents": {"cleanup": COST_CENTS["cleanup"]},
        }

    # -- 3. style planner (the one creative brain) --------------------------

    def style_planner(state: AdMakerState) -> dict:
        preset = resolve_preset(state.get("requested_preset"))
        prev_style = state.get("style") or {}
        product = prev_style.get("product", "product")
        platforms = state.get("target_platforms") or DEFAULT_PLATFORMS
        feedback = state.get("feedback") or []
        prompt = _planner_prompt(preset, product, platforms, feedback)
        verdict = parse_json_verdict(runners["style_planner"](prompt))
        style = {
            "preset": preset.id,
            "product": product,
            "video_prompt": verdict.get(
                "video_prompt", preset.prompt_template.format(product=product)
            ),
            "ad_copy": verdict.get("ad_copy", ""),
            "captions": verdict.get("captions", {}),
            "music_mood": verdict.get("music_mood", preset.music_mood),
        }
        return {
            "style": style,
            "style_candidates": verdict.get("candidates", []),
        }

    def route_mode(state: AdMakerState) -> str:
        # Deterministic fast-mode gate (plain conditional edge). The human
        # checkpoint is a PRE-FIRST-PAID-CALL gate (PLAN.md HITL table), so it
        # is skipped in fast mode AND once any paid job already ran — that
        # keeps automatic regens automatic instead of re-prompting the human.
        if state.get("fast_mode"):
            return "video_generation"
        if (state.get("attempt_count") or {}).get(VIDEO_GEN, 0) > 0:
            return "video_generation"
        return "human_checkpoint"

    # -- 4. human checkpoint (interrupt, pre-first-paid-call) ---------------

    def human_checkpoint(state: AdMakerState) -> Command:
        payload = interrupt(
            {
                "kind": "style_choice",
                "candidates": state.get("style_candidates", []),
                "style": state.get("style", {}),
            }
        )
        if isinstance(payload, dict) and payload.get("direction"):
            return Command(
                update={"feedback": [f"user direction: {payload['direction']}"]},
                goto="style_planner",
            )
        update: dict = {"status": "running"}
        choice = payload.get("choice") if isinstance(payload, dict) else None
        if choice:
            update["style"] = {**(state.get("style") or {}), "preset": choice}
        return Command(update=update, goto="video_generation")

    # -- 5. video generation (Decart, async; the metered step) --------------

    def video_generation(state: AdMakerState) -> Command:
        style = state.get("style") or {}
        image = (state.get("assets") or {}).get("cleaned_image") or state[
            "source_image_url"
        ]
        submitted = video_service.submit(style.get("video_prompt", ""), image)
        # Every SUBMITTED paid job counts (including a later timeout — we may
        # still be billed). Additive reducer -> increments.
        video_gen_attempts = (state.get("attempt_count") or {}).get(VIDEO_GEN, 0) + 1
        base: dict = {
            "attempt_count": {VIDEO_GEN: 1},
            "cost_cents": {VIDEO_GEN: COST_CENTS[VIDEO_GEN]},
            "video_job": {
                "id": submitted["id"],
                "status": "submitted",
                "submitted_at": submitted.get("submitted_at"),
            },
        }
        result = poll_until_terminal(
            video_service, submitted["id"], max_attempts=max_attempts, sleep=sleep
        )
        if result.get("status") == "completed":
            base["video_job"] = {
                "id": result["id"],
                "status": "completed",
                "submitted_at": submitted.get("submitted_at"),
                "completed_at": time.time(),
            }
            base["assets"] = {"raw_video": result["video_url"]}
            return Command(update=base, goto="post_processing")
        # failed or timeout -> ladder (the paid job already counted)
        base["video_job"] = {
            "id": result.get("id", submitted["id"]),
            "status": result.get("status"),
            "error": result.get("error", ""),
        }
        return _paid_failure(
            state,
            video_gen_attempts,
            base,
            f"video job {result.get('status')}: {result.get('error', '')}",
        )

    # -- 6. post processing (FFmpeg; deterministic, idempotent) -------------

    def post_processing(state: AdMakerState) -> dict:
        style = state.get("style") or {}
        raw = (state.get("assets") or {}).get("raw_video", "")
        platforms = state.get("target_platforms") or DEFAULT_PLATFORMS
        rendered = compositor(raw, style, platforms)
        assets = {f"composited_{p}": meta["url"] for p, meta in rendered.items()}
        return {
            "assets": assets,
            "render_meta": rendered,
            # Additive: counts compositing passes for the free-rerun cap.
            "attempt_count": {POST_PROC: 1},
        }

    # -- 7. QA review (technical tier, then content vision tier) ------------

    def qa_review(state: AdMakerState) -> Command:
        meta = state.get("render_meta") or {}
        platforms = state.get("target_platforms") or DEFAULT_PLATFORMS

        tech_reasons = _technical_checks(meta, platforms)
        if tech_reasons:
            report = {
                "tier": "technical",
                "passed": False,
                "reasons": tech_reasons,
                "score": 0.0,
            }
            post_proc_attempts = (state.get("attempt_count") or {}).get(POST_PROC, 0)
            if on_technical_failure(post_proc_attempts) is TechnicalAction.RERUN:
                # Free re-run of the deterministic compositor.
                return Command(
                    update={
                        "qa_reports": [report],
                        "feedback": [f"[technical] {'; '.join(tech_reasons)}"],
                    },
                    goto="post_processing",
                )
            # Structural — compositor keeps producing a bad master; hand it up.
            return Command(
                update={
                    "qa_reports": [report],
                    "feedback": [f"[technical, unrecoverable] {'; '.join(tech_reasons)}"],
                    "status": "awaiting_user_decision",
                },
                goto="user_decision",
            )

        # Content tier (vision). MVP: an injected always-pass stub.
        frame_ref = (state.get("assets") or {}).get("raw_video", "")
        verdict = parse_json_verdict(runners["qa_content"](_QA_HUMAN, frame_ref))
        report = {
            "tier": "content",
            "passed": bool(verdict.get("passed")),
            "score": verdict.get("score", 1.0),
            "reasons": verdict.get("reasons", []),
        }
        if verdict.get("passed"):
            return Command(update={"qa_reports": [report]}, goto="delivery")
        # Content failure costs money -> ladder (paid job already counted).
        video_gen_attempts = (state.get("attempt_count") or {}).get(VIDEO_GEN, 0)
        return _paid_failure(
            state,
            video_gen_attempts,
            {"qa_reports": [report]},
            f"content QA failed: {'; '.join(report['reasons']) or 'low score'}",
        )

    # -- 8. user decision (interrupt; budget exhausted) ---------------------

    def user_decision(state: AdMakerState) -> Command:
        payload = interrupt(
            {
                "kind": "budget_decision",
                "best": _best_content_attempt(state),
                "cost_cents": state.get("cost_cents", {}),
                "attempts": state.get("attempt_count", {}),
            }
        )
        action = payload.get("action") if isinstance(payload, dict) else "accept"
        if action == "spend_more":
            return Command(
                update={
                    "attempt_count": {EXTRA_REGENS: 1},
                    "status": "running",
                    "feedback": ["user granted one more paid regen"],
                },
                goto="style_planner",
            )
        if action == "abort":
            return Command(update={"status": "aborted"}, goto=END)
        # accept (default): ship the best attempt as-is.
        return Command(
            update={"status": "running", "feedback": ["user accepted best attempt"]},
            goto="delivery",
        )

    # -- deliver ------------------------------------------------------------

    def delivery(state: AdMakerState) -> dict:
        platforms = state.get("target_platforms") or DEFAULT_PLATFORMS
        assets = state.get("assets") or {}
        style = state.get("style") or {}
        captions = style.get("captions", {})
        job = state.get("job_id", "job")
        manifest: dict = {}
        for p in platforms:
            url = assets.get(f"composited_{p}")
            if not url:
                continue
            final = asset_store.put_url(f"{job}/final_{p}.mp4", url)
            manifest[p] = {"url": final, "caption": captions.get(p, "")}
        return {"status": "delivered", "manifest": manifest}

    return {
        "intake_validation": intake_validation,
        "image_cleanup": image_cleanup,
        "style_planner": style_planner,
        "route_mode": route_mode,  # conditional-edge router, not a node
        "human_checkpoint": human_checkpoint,
        "video_generation": video_generation,
        "post_processing": post_processing,
        "qa_review": qa_review,
        "user_decision": user_decision,
        "delivery": delivery,
    }
