"""Central configuration: models, the cost-aware ladder caps, platform
export matrix, and per-stage cost placeholders.

Model assignment follows PLAN.md "Model assignment": nothing here needs a
deep-reasoning model — the expensive resource is Decart (video), not the
LLM — so the ceiling is Sonnet for the one creative brain and the vision QA,
and Haiku for the high-volume intake check.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# -- Expensive-stage keys (used across attempt_count / cost_cents) ----------
# The ladder counts PAID VIDEO-GEN CALLS, so this is the key that matters.
VIDEO_GEN = "video_gen"
USER_REGEN = "user_regen"      # post-delivery, user-triggered regenerations
EXTRA_REGENS = "extra_regens"  # granted one-at-a-time at the user_decision gate
POST_PROC = "post_proc"        # free technical re-runs of compositing

# -- Cost-aware retry ladder (PLAN.md "Cost-aware retry ladder") ------------
# The ladder protects MONEY: it caps paid video-gen calls, not failures.
MAX_AUTO_REGENS = 2   # automatic content-QA regens before asking the human
POST_PROC_CAP = 3     # free FFmpeg re-runs on technical QA failure (decision 4)

# Per-tier post-delivery regen allowances (open decision #5 — placeholder,
# meant to be config the product tunes on data).
REGEN_ALLOWANCE = {"free": 1, "paid": 3}

# -- Cost telemetry placeholders (cents) ------------------------------------
# Real numbers come from decision #6's Decart pricing spike; these keep the
# cost_cents channel populated from day one so spend-per-job is queryable.
COST_CENTS = {
    VIDEO_GEN: 50,   # the metered step
    "cleanup": 5,
}

# -- Video-job polling (MVP in-node poll; decision #1) ----------------------
POLL_MAX_ATTEMPTS = 30       # give up -> timeout -> ladder (paid job counts)
POLL_BACKOFF_BASE_S = 2.0    # exponential backoff base
POLL_BACKOFF_CAP_S = 30.0

# -- Model assignment (PLAN.md "Model assignment") --------------------------
MODELS = {
    "intake": "gemini-2.5-flash",
    "style_planner": "gemini-2.5-flash",
    "qa_content": "gemini-2.5-flash",
}

# -- Platform export matrix (PLAN.md "Platform export matrix") --------------
# One post_processing pass renders every target from the master 9:16 clip.
PLATFORM_SPECS = {
    "tiktok":      {"aspect": (9, 16), "max_duration": 60},
    "reels":       {"aspect": (9, 16), "max_duration": 60},
    "shorts":      {"aspect": (9, 16), "max_duration": 60},
    "feed_square": {"aspect": (1, 1),  "max_duration": 60},
    "feed_45":     {"aspect": (4, 5),  "max_duration": 60},
    "stories":     {"aspect": (9, 16), "max_duration": 15},
}
DEFAULT_PLATFORMS = ["tiktok"]  # MVP: single 9:16 target

# -- Intake technical thresholds (Pillow checks, no LLM) --------------------
MIN_RESOLUTION = (512, 512)      # (w, h) minimum
MAX_BLUR_SCORE = 0.6             # probe returns 0..1, higher = blurrier
ALLOWED_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "HEIC"})

# Aspect-match tolerance for technical QA (ratio comparison).
ASPECT_TOLERANCE = 0.02


@dataclass
class AdMakerConfig:
    models: dict[str, str] = field(default_factory=lambda: dict(MODELS))
    max_auto_regens: int = MAX_AUTO_REGENS
    post_proc_cap: int = POST_PROC_CAP
    regen_allowance: dict[str, int] = field(
        default_factory=lambda: dict(REGEN_ALLOWANCE)
    )
    cost_cents: dict[str, int] = field(default_factory=lambda: dict(COST_CENTS))
    poll_max_attempts: int = POLL_MAX_ATTEMPTS
    asset_root: str = "assets"
