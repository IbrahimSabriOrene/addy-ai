"""Local campaign video layout; source media is immutable and audio is copied."""
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from admaker.campaign_layouts import campaign_text
from admaker.media import validate_video


def render_campaign_video(source: Path, destination: Path, brief: dict, logo: Path | None = None) -> dict:
    offer, cta, color = brief.get("offer", ""), brief.get("cta", ""), brief.get("color", "#FFFFFF")
    contact, family = brief.get("contact", ""), brief.get("font", "sans")
    if not isinstance(contact, str) or len(contact) > 100 or any(ord(char) < 32 or ord(char) == 127 for char in contact):
        raise ValueError("Invalid campaign contact")
    if (not isinstance(offer, str) or len(offer) > 300 or not isinstance(cta, str) or len(cta) > 100
            or not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color)
            or any(ord(char) < 32 and char != "\n" for char in offer + cta)):
        raise ValueError("Invalid campaign video fields")
    validate_video(source, (1080, 1920))
    canvas = Image.new("RGB", (1080, 1920), color)
    rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    linear = [v / 3294.6 if v <= 10 else ((v / 255 + 0.055) / 1.055) ** 2.4 for v in rgb]
    ink = "#000000" if sum(v * w for v, w in zip(linear, (0.2126, 0.7152, 0.0722))) > 0.179 else "#FFFFFF"
    draw = ImageDraw.Draw(canvas)
    campaign_text(draw, brief, "video", ink, logo is not None)
    if logo is not None:
        with Image.open(logo) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"} or image.width * image.height > 25_000_000:
                raise ValueError("Invalid campaign logo")
            mark = ImageOps.contain(ImageOps.exif_transpose(image).convert("RGBA"), (360, 110))
        canvas.paste(mark, ((1080 - mark.width) // 2, 70), mark)
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / "video.mp4"
    if source.resolve() == output.resolve():
        raise ValueError("Campaign source must not be overwritten")
    with tempfile.TemporaryDirectory(dir=destination) as temporary:
        background, partial = Path(temporary) / "layout.png", Path(temporary) / "video.mp4"
        canvas.save(background, "PNG")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-xerror", "-y", "-protocol_whitelist", "file",
             "-i", str(source.resolve()), "-protocol_whitelist", "file", "-loop", "1", "-framerate", "24", "-i", str(background.resolve()),
             "-filter_complex", "[0:v]scale=1080:1200:force_original_aspect_ratio=decrease,setsar=1[clip];[1:v][clip]overlay=x=(W-w)/2:y=480+(1200-h)/2:shortest=1[v]",
             "-map", "[v]", "-map", "0:a:0", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-c:a", "copy", "-map_metadata", "-1", "-movflags", "+faststart", str(partial)],
            check=True, capture_output=True, timeout=120,
        )
        metadata = validate_video(partial, (1080, 1920))
        partial.replace(output)
    return {"path": str(output), "mimeType": "video/mp4", "offer": offer, "cta": cta, **metadata}
