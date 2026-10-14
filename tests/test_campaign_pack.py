import hashlib
import subprocess

import pytest
from PIL import Image

from admaker import campaign_pack


def test_pack_reuses_inputs_and_edits_only_layouts(tmp_path, monkeypatch):
    source, video = tmp_path / "approved.png", tmp_path / "video.mp4"
    Image.new("RGB", (120, 200), "blue").save(source)
    video.write_bytes(b"fake video; decoder boundary injected")
    before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in (source, video)]
    calls = []

    def validate(path, size):
        calls.append(path)
        assert size == (1080, 1920)
        return {"width": 1080, "height": 1920, "duration": 8, "hasAudio": True}

    monkeypatch.setattr(campaign_pack, "validate_video", validate)
    def render_video(source, destination, brief):
        path = destination / "video.mp4"
        path.write_bytes(brief["offer"].encode())
        return {"path": str(path), "mimeType": "video/mp4", "offer": brief["offer"], "cta": brief["cta"],
                "width": 1080, "height": 1920, "duration": 8, "hasAudio": True}
    monkeypatch.setattr(campaign_pack, "render_campaign_video", render_video)
    first = campaign_pack.compose_campaign_pack(tmp_path, source.name, video.name,
        {"offer": "20%", "caption": "First", "cta": "Shop", "color": "#123456"})
    second = campaign_pack.compose_campaign_pack(tmp_path, source.name, video.name,
        {"offer": "15%", "caption": "Second", "cta": "Explore", "color": "#654321"})
    assert set(first) == {"cleanImage", "video", "story", "feed", "copy"}
    for manifest in (first, second):
        campaign_pack.require_available_pack(tmp_path, manifest)
    assert first["cleanImage"] == second["cleanImage"]
    assert first["video"]["key"] != second["video"]["key"]
    assert first["video"]["offer"] == "20%" and second["video"]["offer"] == "15%"
    assert first["copy"] == {"caption": "First", "cta": "Shop"}
    for kind in ("story", "feed"):
        assert first[kind]["offer"] == "20%" and second[kind]["offer"] == "15%"
        assert first[kind]["key"] != second[kind]["key"]
        assert (tmp_path / first[kind]["key"]).read_bytes() != (tmp_path / second[kind]["key"]).read_bytes()
    assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in (source, video)] == before
    assert calls == [video, video]


def test_pack_rejects_missing_or_invalid_video_before_layouts(tmp_path, monkeypatch):
    Image.new("RGB", (8, 8)).save(tmp_path / "approved.png")
    with pytest.raises(ValueError, match="unavailable"):
        campaign_pack.compose_campaign_pack(tmp_path, "approved.png", "missing.mp4", {})
    (tmp_path / "video.mp4").write_bytes(b"invalid")

    def reject(*args):
        raise subprocess.SubprocessError("No audio")

    monkeypatch.setattr(campaign_pack, "validate_video", reject)
    with pytest.raises(subprocess.SubprocessError, match="No audio"):
        campaign_pack.compose_campaign_pack(tmp_path, "approved.png", "video.mp4", {})
    assert not (tmp_path / "campaign-packs").exists()
