from PIL import Image

from admaker.worker import _render_photo_fake


def test_photo_fixture_preserves_product_without_video(monkeypatch, tmp_path):
    def no_video(*args, **kwargs):
        raise AssertionError("Photo fixture invoked video tools")

    monkeypatch.setattr("admaker.worker.subprocess.run", no_video)
    source = tmp_path / "source.png"
    Image.new("RGB", (64, 64), "red").save(source)
    exports = _render_photo_fake(source, tmp_path, "job/run/fence", ["feed_square", "stories"])
    for platform, size in (("feed_square", (1080, 1080)), ("stories", (1080, 1920))):
        with Image.open(tmp_path / exports[platform]["key"]) as image:
            assert image.size == size
            assert image.getpixel((540, size[1] // 2)) == (255, 0, 0)
            assert image.format == "PNG"
