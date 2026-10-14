"""Offline demo: run one job end-to-end against the fakes, no network.

    python -m admaker

Proves the happy fast path (screenshot in -> delivered manifest out) using
the same injected fakes the test suite uses. Swap in ``default_runners`` /
``default_services`` + real Decart/FFmpeg adapters for a live run.
"""

from __future__ import annotations

import json
import tempfile

from admaker.assets import LocalDiskAssetStore
from admaker.channels.base import ConsoleChannel
from admaker.graph import build_graph, run_job
from admaker.observability.documenter import ProgressLoggingCallbackHandler
from admaker.observability.sinks import ConsoleSink
from admaker.services import (
    FakeCompositor,
    FakeImageCleaner,
    FakeImageProbe,
    FakeVideoService,
)


def _fake_runners() -> dict:
    def intake(prompt, image_url=None):
        return json.dumps({"product_visible": True, "product_guess": "sneaker"})

    def planner(prompt, image_url=None):
        return json.dumps(
            {
                "video_prompt": "a sneaker on a pedestal, slow 360 spin",
                "ad_copy": "Step up your game.",
                "captions": {"tiktok": "New drop 🔥"},
                "music_mood": "upbeat_clean",
                "candidates": [
                    {"id": "pedestal_spin", "name": "Pedestal spin",
                     "one_liner": "Slow studio 360", "caption_preview": "New drop 🔥"}
                ],
            }
        )

    def qa(prompt, image_url=None):
        return json.dumps({"passed": True, "score": 0.92, "reasons": []})

    return {"intake": intake, "style_planner": planner, "qa_content": qa}


def main() -> None:
    app = build_graph(
        _fake_runners(),
        image_probe=FakeImageProbe(),
        image_cleaner=FakeImageCleaner(),
        video_service=FakeVideoService(outcomes=["completed"]),
        compositor=FakeCompositor(),
        asset_store=LocalDiskAssetStore(tempfile.mkdtemp()),
        sleep=lambda _s: None,
    )
    callbacks = [ProgressLoggingCallbackHandler([ConsoleSink()])]
    result = run_job(
        app,
        {
            "job_id": "demo-1",
            "source_image_url": "file:///tmp/shoe.png",
            "fast_mode": True,
            "target_platforms": ["tiktok"],
        },
        ConsoleChannel(),
        thread_id="demo-1",
        callbacks=callbacks,
    )
    print("\n=== RESULT ===")
    print("status:", result["status"])
    print("manifest:", json.dumps(result.get("manifest", {}), indent=2))


if __name__ == "__main__":
    main()
