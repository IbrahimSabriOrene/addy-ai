import hashlib

import pytest
from PIL import Image

from admaker.campaign_layouts import render_campaign_layouts


def test_logo_is_composited_without_changing_product_or_covering_offer(tmp_path):
    source, logo = tmp_path / "product.png", tmp_path / "logo.png"
    Image.new("RGB", (80, 120), "red").save(source)
    mark = Image.new("RGBA", (360, 110), (0, 0, 255, 128))
    mark.save(logo)
    original = hashlib.sha256(source.read_bytes()).digest()
    brief = {"offer": "Save 20%", "cta": "Shop now", "color": "#FFFFFF"}
    outputs = render_campaign_layouts(source, tmp_path / "with-logo", brief, logo)
    plain = render_campaign_layouts(source, tmp_path / "plain", brief)
    for kind in ("story", "feed"):
        with Image.open(outputs[kind]["path"]) as image, Image.open(plain[kind]["path"]) as before:
            assert image.size == before.size
            assert image.getpixel((540, 70)) == (127, 127, 255)
            assert before.getpixel((540, 35)) == (255, 255, 255)
            assert image.getpixel((540, 600)) == (255, 0, 0)
            assert outputs[kind]["offer"] == "Save 20%"
            # Text occupies its own band below the logo.
            assert min(image.crop((70, 160, 1010, 300)).convert("L").getdata()) == 0
    assert hashlib.sha256(source.read_bytes()).digest() == original
    invalid = tmp_path / "logo.gif"
    mark.convert("RGB").save(invalid)
    with pytest.raises(ValueError, match="Invalid campaign logo"):
        render_campaign_layouts(source, tmp_path / "invalid", brief, invalid)
    assert not (tmp_path / "invalid").exists()
