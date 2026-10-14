import io

import pytest
from fastapi import HTTPException
from PIL import Image, PngImagePlugin

from admaker.api import _verify_image


def test_image_validation_checks_format_dimensions_and_metadata(monkeypatch):
    output = io.BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("private", "remove me")
    Image.new("RGB", (32, 32)).save(output, format="PNG", pnginfo=metadata)
    data = output.getvalue()
    with pytest.raises(HTTPException, match="image type does not match bytes"):
        _verify_image(data, "image/jpeg")
    with Image.open(io.BytesIO(_verify_image(data, "image/png"))) as normalized:
        assert "private" not in normalized.info
    monkeypatch.setattr("admaker.api.MAX_IMAGE_PIXELS", 100)
    with pytest.raises(HTTPException, match="image is too large"):
        _verify_image(data, "image/png")
    with pytest.raises(HTTPException, match="invalid image bytes"):
        _verify_image(b"broken", "image/png")
