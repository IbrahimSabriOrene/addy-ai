"""Opt-in real-media recovery proof using the local FFmpeg container image."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess

from PIL import Image
import pytest

spec = importlib.util.spec_from_file_location("restore_formats", Path(__file__).parents[1] / "tools/rehearse_media_restore.py")
media = importlib.util.module_from_spec(spec)
spec.loader.exec_module(media)


@pytest.mark.skipif(os.environ.get("RUN_DOCKER_MEDIA_TESTS") != "true", reason="Opt-in local FFmpeg container test")
def test_restored_real_png_and_audible_mp4_decode(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    Image.new("RGB", (320, 480), "teal").save(source / "product.png")
    docker = ["docker", "run", "--rm", "--network", "none", "--mount", f"type=bind,source={tmp_path},target=/media", "mobileadmaker-api"]
    subprocess.run(docker + ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=180x320:r=24:d=8",
                            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=8",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", "-shortest", "/media/source/video.mp4"], check=True)
    manifest = media.backup_media(source, tmp_path / "media.zip")
    media.restore_media(tmp_path / "media.zip", tmp_path / "restored", manifest)
    with Image.open(tmp_path / "restored/product.png") as image:
        image.load()
        assert image.size == (320, 480)
        assert image.getpixel((0, 0)) == (0, 128, 128)
    probe = subprocess.run(docker + ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", "/media/restored/video.mp4"], capture_output=True, check=True)
    metadata = json.loads(probe.stdout)
    assert {stream["codec_type"] for stream in metadata["streams"]} == {"audio", "video"}
    assert 7.9 <= float(metadata["format"]["duration"]) <= 8.2
    subprocess.run(docker + ["ffmpeg", "-v", "error", "-xerror", "-i", "/media/restored/video.mp4", "-f", "null", "-"], check=True)
    audio = subprocess.run(docker + ["ffmpeg", "-v", "error", "-i", "/media/restored/video.mp4", "-vn", "-f", "s16le", "-"], capture_output=True, check=True).stdout
    assert any(audio), "Restored native audio must contain a non-silent test tone"
    assert all(media.digest(source / name) == media.digest(tmp_path / "restored" / name) for name in manifest)
