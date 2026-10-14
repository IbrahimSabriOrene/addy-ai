"""Freeze creative choices at creation; private prompts never enter public DTOs."""
from admaker.catalogue import TEMPLATES, require_template


def prepare_photo_prompt(template: str, direction: str = "") -> str:
    prompt = "Create one still product photo using this visual style; ignore motion, audio and timing directions: "
    prompt += template.replace("{product}", "the product in the reference image")
    if direction.strip():
        prompt += " Merchant's creative direction: " + direction.strip()
    if len(prompt) > 4000:
        raise ValueError("Prepared photo prompt exceeds the supported limit")
    return prompt


def snapshot_styles(candidates: list[dict]) -> list[dict]:
    return [{**candidate, "templateVersion": TEMPLATES[candidate["id"]]["version"],
             "prompt": require_template(candidate["id"], TEMPLATES[candidate["id"]]["version"], "video")["prompt"]}
            for candidate in candidates]


def prepare_video_prompt(template: str, direction: str = "") -> str:
    prompt = template.replace("{product}", "product shown in the supplied image")
    prompt += " Create one eight-second vertical video with native audio. Preserve the product's visible details. Leave text and offer overlays to composition."
    if direction.strip():
        prompt += " Merchant's creative direction: " + direction.strip()
    if len(prompt) > 4000:
        raise ValueError("Prepared video prompt exceeds the supported limit")
    return prompt
