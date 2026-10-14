"""Render the repository-owned geometric Addy mark; requires Pillow."""
from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1] / "assets" / "brand"
root.mkdir(parents=True, exist_ok=True)
# A compact A silhouette with a play-shaped negative space; no fonts or stock assets.
outer = [(512, 246), (768, 778), (645, 778), (592, 661), (432, 661), (379, 778), (256, 778)]
cutout = [(467, 421), (467, 563), (577, 492)]
points = " ".join(f"{x},{y}" for x, y in outer)
hole = " ".join(f"{x},{y}" for x, y in cutout)
svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024"><rect width="1024" height="1024" fill="#0e0e11"/><polygon points="{points}" fill="#00c2a8"/><polygon points="{hole}" fill="#0e0e11"/></svg>'
(root / "icon.svg").write_text(svg, encoding="utf-8")
for name, transparent in [("icon.png", False), ("adaptive.png", True), ("splash.png", True)]:
    scale = 4
    image = Image.new("RGBA", (1024 * scale, 1024 * scale), (0, 0, 0, 0) if transparent else "#0e0e11")
    draw = ImageDraw.Draw(image)
    draw.polygon([(x * scale, y * scale) for x, y in outer], fill="#00c2a8")
    draw.polygon([(x * scale, y * scale) for x, y in cutout], fill=(0, 0, 0, 0) if transparent else "#0e0e11")
    image = image.resize((1024, 1024), Image.Resampling.LANCZOS)
    if not transparent:
        image = image.convert("RGB")
    image.save(root / name)
print("Rendered Addy vector mark and three 1024px PNG exports")
