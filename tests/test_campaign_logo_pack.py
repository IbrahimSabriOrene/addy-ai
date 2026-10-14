import hashlib

from PIL import Image

from admaker import campaign_pack


def test_pack_passes_same_logo_to_video_and_layouts_without_mutating_inputs(tmp_path, monkeypatch):
    source, video, logo = (tmp_path / name for name in ("product.png", "source.mp4", "logo.png"))
    Image.new("RGB", (100, 200), "red").save(source)
    Image.new("RGBA", (360, 110), "blue").save(logo)
    video.write_bytes(b"source video; codec boundary injected")
    before = [hashlib.sha256(path.read_bytes()).digest() for path in (source, video, logo)]
    received = []
    monkeypatch.setattr(campaign_pack, "validate_video", lambda *args: {})
    def render_video(source_path, destination, brief, logo=None):
        received.append(logo)
        assert source_path == video
        assert logo is not None and logo.read_bytes() == (tmp_path / "logo.png").read_bytes()
        path = destination / "video.mp4"
        path.write_bytes(b"composed video")
        return {"path": str(path), "mimeType": "video/mp4", "offer": brief["offer"], "cta": brief["cta"]}
    monkeypatch.setattr(campaign_pack, "render_campaign_video", render_video)
    result = campaign_pack.compose_campaign_pack(tmp_path, source.name, video.name,
        {"offer": "Save 20%", "cta": "Shop", "caption": "Summer"}, logo=logo)
    assert received == [logo]
    assert result["cleanImage"]["key"] == source.name
    assert result["video"]["key"] != video.name
    for kind in ("story", "feed"):
        with Image.open(tmp_path / result[kind]["key"]) as image:
            assert image.getpixel((540, 70)) == (0, 0, 255)
            assert image.getpixel((540, 600)) == (255, 0, 0)
        assert result[kind]["offer"] == "Save 20%"
    assert [hashlib.sha256(path.read_bytes()).digest() for path in (source, video, logo)] == before
