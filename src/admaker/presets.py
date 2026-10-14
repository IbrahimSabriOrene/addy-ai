"""Style preset library (PLAN.md "Style presets").

v1 ships a fixed library, freeform prompting is v2. Fixed presets keep
video-gen prompts in distribution (fewer QA failures = fewer paid regens)
and make the checkpoint UI a picker instead of a free text box. The planner
*fills* a preset's prompt template rather than free-writing prompts.

Each preset carries everything a planning pass needs: the video-prompt
template, motion params, caption layout, a music mood, and a safe duration
range the compositor and technical-QA tier both respect.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StylePreset:
    id: str
    name: str
    description: str            # one line shown in the checkpoint picker
    prompt_template: str        # {product} is filled by the planner
    motion_params: dict = field(default_factory=dict)
    caption_layout: str = "lower_third"
    music_mood: str = "neutral"
    safe_duration: tuple[int, int] = (15, 30)  # (min, max) seconds


PRESETS: dict[str, StylePreset] = {
    "pedestal_spin": StylePreset(
        id="pedestal_spin",
        name="Pedestal spin",
        description="Product centered, slow 360° on a studio backdrop.",
        prompt_template=(
            "A single {product} centered on a seamless studio backdrop, "
            "slow smooth 360-degree turntable rotation, soft key lighting, "
            "shallow depth of field, premium commercial look."
        ),
        motion_params={"rotation_deg": 360, "camera": "locked"},
        caption_layout="lower_third",
        music_mood="upbeat_clean",
        safe_duration=(15, 25),
    ),
    "unboxing_pan": StylePreset(
        id="unboxing_pan",
        name="Unboxing pan",
        description="Top-down reveal, hands-free, soft shadows.",
        prompt_template=(
            "Top-down view of a {product} being revealed, gentle push-in "
            "and lateral pan, soft directional shadows, tactile materials, "
            "warm inviting tone."
        ),
        motion_params={"camera": "pan", "angle": "top_down"},
        caption_layout="center_lower",
        music_mood="warm_acoustic",
        safe_duration=(15, 30),
    ),
    "lifestyle_zoom": StylePreset(
        id="lifestyle_zoom",
        name="Lifestyle zoom",
        description="Product in-context, slow push-in, warm grade.",
        prompt_template=(
            "A {product} in a natural lifestyle setting, slow cinematic "
            "push-in, warm color grade, bokeh background, aspirational "
            "everyday scene."
        ),
        motion_params={"camera": "dolly_in"},
        caption_layout="lower_third",
        music_mood="uplifting",
        safe_duration=(15, 30),
    ),
    "feature_pop": StylePreset(
        id="feature_pop",
        name="Feature pop",
        description="Static hero + animated callout captions (cheapest).",
        prompt_template=(
            "A {product} as a crisp static hero shot on a clean gradient, "
            "minimal ambient motion, space reserved for animated callout "
            "captions."
        ),
        # Mostly a compositing effect, so motion asks little of the video model.
        motion_params={"camera": "locked", "ambient_motion": "subtle"},
        caption_layout="animated_callouts",
        music_mood="energetic",
        safe_duration=(10, 20),
    ),
}

DEFAULT_PRESET = "pedestal_spin"  # MVP single preset


def resolve_preset(requested: str | None) -> StylePreset:
    """Honor the user's pick, else fall back to the default. Unknown ids
    fall back too — the planner never free-writes in v1."""
    if requested and requested in PRESETS:
        return PRESETS[requested]
    return PRESETS[DEFAULT_PRESET]
