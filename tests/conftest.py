"""Shared fakes: scripted runners + service fakes exercising every route in
the topology diagram offline (PLAN.md "Next step")."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from admaker.config import AdMakerConfig
from admaker.graph import build_graph
from admaker.nodes import RUNNER_NAMES
from admaker.services import (
    FakeCompositor,
    FakeImageCleaner,
    FakeImageProbe,
    FakeVideoService,
)

# -- scripted LLM replies ---------------------------------------------------
INTAKE_OK = json.dumps(
    {"product_visible": True, "product_guess": "sneaker", "reason": "clear single product"}
)
INTAKE_REJECT = json.dumps(
    {"product_visible": False, "product_guess": "", "reason": "no clear product"}
)
PLAN = json.dumps(
    {
        "video_prompt": "a sneaker on a pedestal, slow 360 spin",
        "ad_copy": "Step up your game.",
        "captions": {"tiktok": "New drop 🔥", "reels": "New drop"},
        "music_mood": "upbeat_clean",
        "candidates": [
            {
                "id": "pedestal_spin",
                "name": "Pedestal spin",
                "one_liner": "Slow studio 360",
                "caption_preview": "New drop 🔥",
            }
        ],
    }
)
QA_PASS = json.dumps({"passed": True, "score": 0.9, "reasons": []})
QA_FAIL = json.dumps({"passed": False, "score": 0.3, "reasons": ["warped product edge"]})


class ScriptedRunner:
    """Returns scripted replies in order; repeats the last one after.
    Signature matches the uniform runner: ``(prompt, image_url=None)``."""

    def __init__(self, *responses: str):
        self.responses = list(responses)
        self.calls: list[str] = []

    def __call__(self, prompt: str, image_url: str | None = None) -> str:
        self.calls.append(prompt)
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]


@dataclass
class ScriptedGate:
    """HumanGate fake: scripted replies for the two interrupt gates."""

    style_responses: list = field(default_factory=list)
    budget_responses: list = field(default_factory=list)
    style_calls: list = field(default_factory=list)
    budget_calls: list = field(default_factory=list)

    def choose_style(self, context: dict) -> dict:
        self.style_calls.append(context)
        if self.style_responses:
            return self.style_responses.pop(0)
        return {"choice": "pedestal_spin"}

    def decide_budget(self, context: dict) -> dict:
        self.budget_calls.append(context)
        if self.budget_responses:
            return self.budget_responses.pop(0)
        return {"action": "accept"}


class FakeAssetStore:
    """Records finals; ``put_url`` just echoes the external URL."""

    def __init__(self):
        self.finals: dict[str, str] = {}

    def put(self, key: str, data: bytes) -> str:
        return f"mem://{key}"

    def put_url(self, key: str, source_url: str) -> str:
        self.finals[key] = source_url
        return f"mem://{key}"

    def get(self, key: str) -> bytes:
        raise KeyError(key)

    def presign(self, key: str) -> str:
        return f"mem://{key}"

    def delete(self, key: str) -> None:
        self.finals.pop(key, None)


def happy_runners() -> dict[str, ScriptedRunner]:
    scripts = {
        "intake": INTAKE_OK,
        "style_planner": PLAN,
        "qa_content": QA_PASS,
    }
    assert set(scripts) == set(RUNNER_NAMES)
    return {name: ScriptedRunner(script) for name, script in scripts.items()}


@dataclass
class Harness:
    """Bundles the compiled app with the fakes so tests can assert calls."""

    app: object
    runners: dict
    probe: FakeImageProbe
    cleaner: FakeImageCleaner
    video: FakeVideoService
    compositor: FakeCompositor
    store: FakeAssetStore
    cleanup_cache: dict


def make_harness(
    *,
    runners: dict | None = None,
    probe: FakeImageProbe | None = None,
    cleaner: FakeImageCleaner | None = None,
    video: FakeVideoService | None = None,
    compositor: FakeCompositor | None = None,
    store: FakeAssetStore | None = None,
    cleanup_cache: dict | None = None,
    config: AdMakerConfig | None = None,
) -> Harness:
    runners = runners or happy_runners()
    probe = probe or FakeImageProbe()
    cleaner = cleaner or FakeImageCleaner()
    video = video or FakeVideoService(outcomes=["completed"])
    compositor = compositor or FakeCompositor()
    store = store or FakeAssetStore()
    cleanup_cache = cleanup_cache if cleanup_cache is not None else {}
    app = build_graph(
        runners,
        config=config,
        image_probe=probe,
        image_cleaner=cleaner,
        video_service=video,
        compositor=compositor,
        asset_store=store,
        cleanup_cache=cleanup_cache,
        sleep=lambda _s: None,  # never wait on poll backoff
    )
    return Harness(app, runners, probe, cleaner, video, compositor, store, cleanup_cache)


def initial_state(**overrides) -> dict:
    state = {
        "job_id": "job-1",
        "user_id": "u1",
        "tier": "free",
        "source_image_url": "https://example.com/shoe.png",
        "fast_mode": True,
        "target_platforms": ["tiktok"],
    }
    state.update(overrides)
    return state


@pytest.fixture
def harness():
    return make_harness()
