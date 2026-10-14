"""Local video composition and technical delivery checks; no provider calls."""

import json
import hashlib
import math
import subprocess
import tempfile
from pathlib import Path


def validate_video(path: Path, size: tuple[int, int] | None = None) -> dict:
    if not 0 < path.stat().st_size <= 100 * 1024 * 1024:
        raise subprocess.SubprocessError("Video is empty or exceeds 100 MB")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-protocol_whitelist", "file", "-show_streams",
         "-show_format", "-of", "json", str(path.resolve())],
        check=True, capture_output=True, text=True, timeout=15,
    )
    data = json.loads(probe.stdout)
    videos = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    audio = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    duration = float(data.get("format", {}).get("duration", 0))
    if len(videos) != 1 or len(audio) != 1 or not math.isfinite(duration) or not 7.5 <= duration <= 8.5:
        raise subprocess.SubprocessError("Expected one eight-second video and one audio stream")
    if "mp4" not in data.get("format", {}).get("format_name", "").split(","):
        raise subprocess.SubprocessError("Expected an MP4 container")
    if any(not 7.5 <= float(stream.get("duration", 0)) <= 8.5 for stream in (videos[0], audio[0])):
        raise subprocess.SubprocessError("Video and audio must cover the full clip")
    video = videos[0]
    dimensions = (video.get("width", 0), video.get("height", 0))
    if not all(0 < d <= 4096 for d in dimensions):
        raise subprocess.SubprocessError("Unsupported video dimensions")
    if size and (dimensions != size or video.get("codec_name") != "h264"
                 or audio[0].get("codec_name") != "aac" or video.get("pix_fmt") != "yuv420p"):
        raise subprocess.SubprocessError("Export does not match the H.264/AAC layout")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-xerror", "-err_detect", "explode",
         "-protocol_whitelist", "file", "-i", str(path.resolve()),
         "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],
        check=True, capture_output=True, timeout=60,
    )
    return {"width": dimensions[0], "height": dimensions[1],
            "duration": duration, "hasAudio": True}


def compose_video(source: Path, root: Path, output_id: str, platforms: list[str]) -> dict:
    """Fit/pad a generated clip, preserving its audio and reusing portrait exports."""
    layouts = {"tiktok": (1080, 1920), "reels": (1080, 1920),
               "stories": (1080, 1920), "feed": (1080, 1080), "feed_square": (1080, 1080)}
    if not platforms or any(p not in layouts for p in platforms):
        raise ValueError("Unsupported video platform")
    directory = (root / "runs" / output_id).resolve()
    if not directory.is_relative_to((root / "runs").resolve()) or directory == (root / "runs").resolve():
        raise ValueError("Invalid output directory")
    validate_video(source)
    directory.mkdir(parents=True, exist_ok=True)
    rendered = {}
    exports = {}
    for platform in platforms:
        size = layouts[platform]
        if size not in rendered:
            width, height = size
            destination = directory / f"final_{width}x{height}.mp4"
            with tempfile.NamedTemporaryFile(dir=directory, suffix=".mp4", delete=False) as file:
                partial = Path(file.name)
            try:
                subprocess.run(
                    ["ffmpeg", "-v", "error", "-xerror", "-y", "-protocol_whitelist", "file",
                     "-i", str(source.resolve()), "-map", "0:v:0", "-map", "0:a:0",
                     "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
                     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                     "-map_metadata", "-1", "-movflags", "+faststart", str(partial)],
                    check=True, capture_output=True, timeout=120,
                )
                metadata = validate_video(partial, size)
                partial.replace(destination)
            finally:
                partial.unlink(missing_ok=True)
            rendered[size] = {"key": destination.relative_to(root.resolve()).as_posix(),
                              "caption": "", "mimeType": "video/mp4",
                              "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), **metadata}
        exports[platform] = dict(rendered[size])
    return exports
