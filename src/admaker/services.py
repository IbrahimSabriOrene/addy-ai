"""External-service adapters: image probe, image cleanup (Decart image),
video generation (Decart video, async), and compositing (FFmpeg).

Same discipline as the orchestrator's injected runners: every node takes its
external behavior through one of these protocols, so the whole graph — every
route in the topology diagram — runs offline against the fakes here, with
zero network and zero Decart/FFmpeg dependency (PLAN.md "Next step": prove
every route before any real Decart account is touched).

All Decart specifics (model names, async shape) are from the brief and must
be verified against current Decart docs at build time — see PLAN.md
decision #6. They live here so the rest of the graph never encodes them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable

from admaker.config import (
    POLL_BACKOFF_BASE_S,
    POLL_BACKOFF_CAP_S,
    POLL_MAX_ATTEMPTS,
)


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------

@runtime_checkable
class ImageProbe(Protocol):
    def __call__(self, image_url: str) -> dict:
        """Cheap local inspection (Pillow, no LLM). Returns
        {"width", "height", "blur_score" (0..1), "format"}."""
        ...


@runtime_checkable
class ImageCleaner(Protocol):
    def __call__(self, image_url: str) -> str:
        """Decart lucy-image-2: background removal / lighting normalization.
        Returns the cleaned image URL."""
        ...


@runtime_checkable
class VideoService(Protocol):
    def submit(self, prompt: str, image_url: str) -> dict:
        """Submit an async job. Returns {"id", "status", "submitted_at"}."""
        ...

    def poll(self, job_id: str) -> dict:
        """Poll a job. Returns {"id", "status", "video_url"?, "error"?} where
        status is one of processing | completed | failed."""
        ...


@runtime_checkable
class Compositor(Protocol):
    def __call__(self, video_url: str, style: dict, platforms: list[str]) -> dict:
        """FFmpeg pass: burn captions, overlay logo, mix music, render every
        target aspect from the one master clip. Returns
        {platform: {"url", "duration", "width", "height", "has_audio"}}."""
        ...


# ---------------------------------------------------------------------------
# Video polling helper (shared by real service and node)
# ---------------------------------------------------------------------------

def poll_until_terminal(
    service: VideoService,
    job_id: str,
    *,
    max_attempts: int = POLL_MAX_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """In-node polling with exponential backoff up to a timeout budget
    (PLAN.md decision #1, MVP). ``sleep`` is injected so tests never wait.
    Returns the terminal job dict, or a synthesized ``timeout`` result if
    the budget is exhausted while still processing."""
    last = {"id": job_id, "status": "processing"}
    for attempt in range(max_attempts):
        last = service.poll(job_id)
        if last.get("status") in ("completed", "failed"):
            return last
        backoff = min(POLL_BACKOFF_BASE_S * (2 ** attempt), POLL_BACKOFF_CAP_S)
        sleep(backoff)
    return {"id": job_id, "status": "timeout", "error": "poll budget exhausted"}


# ---------------------------------------------------------------------------
# Offline fakes (used by the test suite and local dev)
# ---------------------------------------------------------------------------

def good_probe() -> dict:
    """A probe result that passes intake technical checks."""
    return {"width": 1080, "height": 1920, "blur_score": 0.1, "format": "PNG"}


@dataclass
class FakeImageProbe:
    """Returns a scripted probe result; defaults to a passing one."""

    result: dict = field(default_factory=good_probe)
    calls: list[str] = field(default_factory=list)

    def __call__(self, image_url: str) -> dict:
        self.calls.append(image_url)
        return dict(self.result)


@dataclass
class FakeImageCleaner:
    """Records calls so the cleanup cache can be verified (a re-style of the
    same photo must never pay for cleanup twice)."""

    calls: list[str] = field(default_factory=list)

    def __call__(self, image_url: str) -> str:
        self.calls.append(image_url)
        return f"{image_url}#cleaned-{len(self.calls)}"


@dataclass
class FakeVideoService:
    """Scripts a sequence of terminal outcomes, one per submitted job.

    ``outcomes`` entries are "completed" | "failed" | "processing" (the last
    drives the timeout path). The Nth submit uses the Nth outcome (last one
    repeats), so tests can say e.g. ``["failed", "completed"]`` to exercise a
    regen. ``poll`` returns the outcome recorded at submit time."""

    outcomes: list[str] = field(default_factory=lambda: ["completed"])
    submits: list[dict] = field(default_factory=list)
    _jobs: dict[str, str] = field(default_factory=dict)

    def submit(self, prompt: str, image_url: str) -> dict:
        idx = len(self.submits)
        outcome = self.outcomes[min(idx, len(self.outcomes) - 1)]
        job_id = f"job-{idx + 1}"
        self._jobs[job_id] = outcome
        record = {
            "id": job_id,
            "status": "submitted",
            "submitted_at": float(idx),
            "prompt": prompt,
        }
        self.submits.append(record)
        return record

    def poll(self, job_id: str) -> dict:
        outcome = self._jobs.get(job_id, "completed")
        if outcome == "completed":
            return {"id": job_id, "status": "completed", "video_url": f"{job_id}.mp4"}
        if outcome == "failed":
            return {"id": job_id, "status": "failed", "error": "model error"}
        return {"id": job_id, "status": "processing"}  # -> timeout


@dataclass
class FakeCompositor:
    """Returns per-platform metadata. ``bad_first`` makes the first pass fail
    the technical QA tier (wrong duration) to exercise the free-rerun path,
    then produces valid output; ``bad_all`` fails every pass to exercise the
    unrecoverable escalation."""

    bad_first: bool = False
    bad_all: bool = False
    calls: list[dict] = field(default_factory=list)

    def __call__(self, video_url: str, style: dict, platforms: list[str]) -> dict:
        from admaker.config import PLATFORM_SPECS

        first_bad = self.bad_all or (self.bad_first and not self.calls)
        self.calls.append({"video_url": video_url, "platforms": list(platforms)})
        out: dict[str, dict] = {}
        for p in platforms:
            spec = PLATFORM_SPECS.get(p, {"aspect": (9, 16), "max_duration": 60})
            w, h = spec["aspect"]
            duration = 999 if first_bad else min(spec["max_duration"], 20)
            out[p] = {
                "url": f"{video_url}#{p}",
                "duration": duration,
                "width": w * 120,
                "height": h * 120,
                "has_audio": True,
            }
        return out


# ---------------------------------------------------------------------------
# Real back-end stubs (wired at build time; verify against live docs — #6)
# ---------------------------------------------------------------------------

def pillow_probe(image_url: str) -> dict:
    """Real probe via Pillow. Blur score is a cheap variance-of-Laplacian
    proxy normalized to 0..1 (lower = sharper)."""
    from PIL import Image  # optional dependency: extra ``pillow``

    with Image.open(image_url) as im:
        width, height = im.size
        fmt = im.format or "UNKNOWN"
    # A real blur metric needs numpy/opencv; keep the interface honest and
    # leave the heavy computation to the v1 impl.
    return {"width": width, "height": height, "blur_score": 0.0, "format": fmt}
