"""Deterministic campaign layouts. Approved product pixels are fitted, never regenerated."""
import os
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


def fitted_text(draw, text: str, box: tuple, fill: str, maximum: int, family: str = "sans"):
    if family not in {"sans", "serif"}:
        raise ValueError("Unsupported campaign font")
    font_path = (os.environ.get("CAMPAIGN_SERIF_FONT_PATH", "C:/Windows/Fonts/times.ttf" if os.name == "nt"
                                else "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf") if family == "serif" else
                 os.environ.get("CAMPAIGN_FONT_PATH", "C:/Windows/Fonts/arial.ttf" if os.name == "nt"
                                else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
    left, top, right, bottom = box
    for size in range(maximum, 23, -2):
        font = ImageFont.truetype(font_path, size)
        missing = bytes(font.getmask("\U0010ffff"))
        if any(not char.isspace() and bytes(font.getmask(char)) == missing for char in set(text)):
            raise ValueError("The layout font does not support a character in the offer or CTA")
        lines = [""]
        for char in text:
            if char == "\n":
                lines.append("")
            elif font.getlength(lines[-1] + char) <= right - left:
                lines[-1] += char
            else:
                lines.append(char)
        line_height = sum(font.getmetrics())
        if len(lines) * line_height <= bottom - top:
            for index, line in enumerate(lines):
                draw.text(((left + right) / 2, top + index * line_height), line,
                          font=font, fill=fill, anchor="mt")
            return
    raise ValueError("Offer or CTA does not fit; shorten it before rendering")


def campaign_text(draw, brief: dict, kind: str, ink: str, has_logo: bool = False):
    """Shared by preflight and final render so font/fit rules cannot drift."""
    offer, cta, color = brief.get("offer", ""), brief.get("cta", ""), brief.get("color", "#FFFFFF")
    contact, family = brief.get("contact", ""), brief.get("font", "sans")
    if not isinstance(contact, str) or len(contact) > 100 or any(ord(char) < 32 or ord(char) == 127 for char in contact):
        raise ValueError("Invalid campaign contact")
    if (not isinstance(offer, str) or len(offer) > 300 or not isinstance(cta, str) or len(cta) > 100
            or not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color)):
        raise ValueError("Invalid campaign layout fields")
    if any(ord(char) < 32 and char != "\n" for char in offer + cta):
        raise ValueError("Unsupported control character in campaign text")
    boxes = {
        "story": ((90, 170, 990, 490), (90, 1550, 990, 1730), 76),
        "feed": ((70, 160 if has_logo else 60, 1010, 300), (70, 850, 1010, 1010), 62),
        "video": ((90, 200, 990, 460), (90, 1700, 990, 1850), 76),
    }
    offer_box, cta_box, maximum = boxes[kind]
    fitted_text(draw, offer, offer_box, ink, maximum, family)
    fitted_text(draw, "\n".join(filter(None, (cta, contact))), cta_box, ink, 48, family)


def preflight_campaign_text(brief: dict):
    """No media, disk writes or provider calls; use the deployed render fonts."""
    with Image.new("RGB", (1, 1)) as canvas:
        draw = ImageDraw.Draw(canvas)
        for kind in ("story", "feed", "video"):
            try:
                campaign_text(draw, brief, kind, "#000000", bool(brief.get("logoAssetKey")))
            except ValueError as error:
                raise ValueError(f"Check {kind} text before generating: {error}. No new credits were reserved.") from error


def render_campaign_layouts(source: Path, destination: Path, brief: dict, logo: Path | None = None) -> dict:
    offer, cta, color = brief.get("offer", ""), brief.get("cta", ""), brief.get("color", "#FFFFFF")
    with Image.open(source) as image:
        if image.width * image.height > 25_000_000:
            raise ValueError("Approved image exceeds the layout size limit")
        product = ImageOps.exif_transpose(image).convert("RGBA")
    mark = None
    if logo is not None:
        with Image.open(logo) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"} or image.width * image.height > 25_000_000:
                raise ValueError("Invalid campaign logo")
            mark = ImageOps.contain(ImageOps.exif_transpose(image).convert("RGBA"), (360, 110))
    rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    linear = [value / 3294.6 if value <= 10 else ((value / 255 + 0.055) / 1.055) ** 2.4 for value in rgb]
    luminance = sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    ink = "#000000" if luminance > 0.179 else "#FFFFFF"
    outputs = {}
    destination.mkdir(parents=True, exist_ok=True)
    for kind, height in (("story", 1920), ("feed", 1080)):
        canvas = Image.new("RGB", (1080, height), color)
        draw = ImageDraw.Draw(canvas)
        if kind == "story":
            image_box = (90, 530, 990, 1470)
        else:
            image_box = (170, 330, 910, 800)
        if mark is not None:
            canvas.paste(mark, ((1080 - mark.width) // 2, 30), mark)
        campaign_text(draw, brief, kind, ink, mark is not None)
        left, top, right, bottom = image_box
        fitted = ImageOps.contain(product, (right - left, bottom - top))
        canvas.paste(fitted, (left + (right - left - fitted.width) // 2,
                              top + (bottom - top - fitted.height) // 2), fitted)
        path = destination / f"{kind}.png"
        canvas.save(path, "PNG")
        outputs[kind] = {"path": str(path), "width": 1080, "height": height, "mimeType": "image/png",
                         "offer": offer, "cta": cta}
    return outputs
