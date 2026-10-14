"""Compose all pack assets locally from an approved image and generated video."""
import uuid
import hashlib
from pathlib import Path

from PIL import Image

from admaker.campaign_layouts import render_campaign_layouts
from admaker.campaign_video import render_campaign_video
from admaker.media import validate_video


def require_available_pack(root: Path, manifest: dict):
    """Settlement guard, in addition to the worker's bound technical/policy verdict."""
    if set(manifest) != {"cleanImage", "video", "story", "feed", "copy"}:
        raise ValueError("Complete campaign pack required")
    copy = manifest.get("copy")
    if not isinstance(copy, dict) or any(not isinstance(copy.get(field), str) for field in ("caption", "cta")):
        raise ValueError("Campaign copy is unavailable")
    root = root.resolve()
    for kind in ("cleanImage", "video", "story", "feed"):
        item = manifest[kind]
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            raise ValueError("Campaign media is unavailable")
        path = (root / item["key"]).resolve()
        if not path.is_relative_to(root) or not path.is_file() or not 0 < path.stat().st_size <= 100 * 1024 * 1024:
            raise ValueError("Campaign media is unavailable")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != item.get("sha256"):
                raise ValueError("Campaign media has changed or cannot be verified")


def compose_campaign_pack(root: Path, image_key: str, video_key: str, brief: dict, run_id=None, logo: Path | None = None) -> dict:
    """Return a complete private manifest only after every media output validates.

    Caller persists this in a fenced durable stage. No provider calls or credit
    settlement occur here; a layout retry reuses both paid input assets.
    """
    root = root.resolve()
    paths = []
    for key in (image_key, video_key):
        path = (root / key).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("Campaign media is unavailable")
        paths.append(path)
    source, video = paths
    caption, cta = brief.get("caption", ""), brief.get("cta", "")
    if not isinstance(caption, str) or len(caption) > 2200 or not isinstance(cta, str) or len(cta) > 100:
        raise ValueError("Invalid campaign copy")
    validate_video(video, (1080, 1920))
    with Image.open(source) as image:
        if image.format not in {"JPEG", "PNG", "WEBP"} or image.width * image.height > 25_000_000:
            raise ValueError("Invalid approved image")
        image.load()
        image_metadata = {"width": image.width, "height": image.height,
                          "mimeType": Image.MIME[image.format]}
    # Unique attempt directory prevents a retry overwriting a published layout.
    parent = root / "campaign-runs" / str(uuid.UUID(str(run_id))) if run_id is not None else root / "campaign-packs"
    destination = parent / str(uuid.uuid4())
    if not destination.resolve().is_relative_to(root):
        raise ValueError("Invalid campaign output directory")
    layouts = render_campaign_layouts(source, destination, brief, **({"logo": logo} if logo else {}))
    rendered_video = render_campaign_video(video, destination, brief, **({"logo": logo} if logo else {}))
    video_output = Path(rendered_video["path"]).resolve()
    if not video_output.is_relative_to(destination.resolve()):
        raise ValueError("Invalid campaign video path")
    manifest = {
        "cleanImage": {"key": source.relative_to(root).as_posix(), **image_metadata},
        "video": {**{k: v for k, v in rendered_video.items() if k != "path"},
                  "key": video_output.relative_to(root).as_posix()},
        "copy": {"caption": caption, "cta": cta},
    }
    for kind, expected in (("story", (1080, 1920)), ("feed", (1080, 1080))):
        item = layouts[kind]
        path = Path(item["path"]).resolve()
        if not path.is_relative_to(destination.resolve()):
            raise ValueError("Invalid campaign layout path")
        with Image.open(path) as image:
            image.load()
            if image.format != "PNG" or image.size != expected:
                raise ValueError("Invalid campaign layout output")
        manifest[kind] = {k: v for k, v in item.items() if k != "path"}
        manifest[kind]["key"] = path.relative_to(root).as_posix()
    for kind in ("cleanImage", "video", "story", "feed"):
        with (root / manifest[kind]["key"]).open("rb") as stream:
            manifest[kind]["sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    return manifest
