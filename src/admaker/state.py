"""State schema with explicit reducers.

Reducer choice is the design decision (PLAN.md "State schema"). This graph
is mostly linear, so clobbering risk is lower than the orchestrator's
fan-out — but four fields still need merge semantics because QA re-entry
paths, the delivery/regen loop, and late async webhook resumes (v1) can
write concurrently with the main path:

- ``assets``        -> keyed merge (stages never clobber each other's URLs)
- ``video_job``     -> keyed merge (submit vs. completion vs. late webhook)
- ``attempt_count`` -> keyed merge (per expensive stage)
- ``cost_cents``    -> keyed merge (per-stage actual spend)
- ``qa_reports`` / ``feedback`` -> append, so the planner always sees the
  FULL failure history on a retry, not just the last reason.

``keyed_merge`` is copied verbatim from the orchestrator (PLAN.md decision
#8: patterns are copied in, not imported).
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class WorkerState(TypedDict, total=False):
    run_id: str
    graph_version: str
    request_hash: str
    exports: dict


def keyed_merge(left: dict | None, right: dict | None) -> dict:
    """Per-key overwrite, cross-key union. Concurrent writers touching
    different keys never clobber each other."""
    merged = dict(left or {})
    merged.update(right or {})
    return merged


def additive_merge(left: dict | None, right: dict | None) -> dict:
    """Per-key numeric addition, cross-key union. Used for cost_cents and
    attempt_count so a concurrent write ADDS rather than overwrites — a late
    webhook resume that also spent money must not erase the main path's
    tally. Non-numeric values fall back to right-wins."""
    merged = dict(left or {})
    for key, value in (right or {}).items():
        if key in merged and isinstance(merged[key], int) and isinstance(value, int):
            merged[key] += value
        else:
            merged[key] = value
    return merged


class AdMakerState(TypedDict, total=False):
    # -- Identity & inputs --------------------------------------------------
    job_id: str                  # == LangGraph thread_id (correlation key)
    user_id: str
    tier: str                    # "free" | "paid" (gates regen allowance)
    source_image_url: str
    fast_mode: bool              # skip human_checkpoint
    target_platforms: list[str]  # ["tiktok", "reels", "feed_square", ...]
    requested_preset: str | None  # user pick, or None = planner chooses

    # -- Pipeline artifacts (keyed merge — stages never clobber) ------------
    # keys: cleaned_image, raw_video, composited_<platform>, thumbnail, ...
    assets: Annotated[dict[str, str], keyed_merge]
    # Per-platform render metadata the technical-QA tier checks (duration,
    # aspect, audio). Only the compositor knows it, so it must ride in state.
    render_meta: Annotated[dict, keyed_merge]

    # -- Planning output (overwritten wholesale on each planning pass) ------
    # {preset, video_prompt, ad_copy, captions{platform: str}, music_mood}
    style: dict
    style_candidates: list[dict]  # what human_checkpoint showed

    # -- Async job tracking -------------------------------------------------
    # {id, status, submitted_at, completed_at, error}
    video_job: Annotated[dict, keyed_merge]

    # -- QA & feedback history (append — full history informs each retry) ---
    qa_reports: Annotated[list[dict], operator.add]  # {tier, passed, reasons, score}
    feedback: Annotated[list[str], operator.add]     # regen notes + QA reasons

    # -- Cost-aware retry ladder (additive per expensive stage) -------------
    attempt_count: Annotated[dict[str, int], additive_merge]  # {"video_gen": n, ...}
    cost_cents: Annotated[dict[str, int], additive_merge]     # per-stage spend

    # -- Terminal / gate status for the app ---------------------------------
    status: str   # running | awaiting_style_choice | awaiting_user_decision |
                  # needs_reshoot | delivered | aborted

    # -- Delivery output ----------------------------------------------------
    manifest: dict  # per-platform final asset manifest
