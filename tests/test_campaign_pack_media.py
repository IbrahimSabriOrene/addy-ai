"""Run the current pack compositor with actual FFmpeg and Pillow, offline."""
import json
import os
from pathlib import Path
import subprocess

import pytest
from PIL import Image


@pytest.mark.skipif(os.environ.get("RUN_DOCKER_MEDIA_TESTS") != "true", reason="Opt-in local FFmpeg container test")
def test_real_pack_media_and_audio_validation(tmp_path):
    Image.new("RGB", (320, 480), "teal").save(tmp_path / "approved.png")
    source = Path(__file__).parents[1] / "src"
    docker = ["docker", "run", "--rm", "--network", "none",
              "--mount", f"type=bind,source={tmp_path},target=/media",
              "--mount", f"type=bind,source={source},target=/current-src,readonly",
              "-e", "PYTHONPATH=/current-src", "mobileadmaker-api"]
    subprocess.run(docker + ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:r=24:d=8",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=8",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-movflags", "+faststart", "-shortest", "/media/video.mp4"], check=True, timeout=90)
    script = '''
import hashlib, json, subprocess
from pathlib import Path
from admaker.campaign_pack import compose_campaign_pack
root = Path('/media')
paths = [root / 'approved.png', root / 'video.mp4']
before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
manifest = compose_campaign_pack(root, 'approved.png', 'video.mp4',
    {'offer': '20% off', 'cta': 'Shop now', 'caption': 'Campaign caption'})
assert set(manifest) == {'cleanImage', 'video', 'story', 'feed', 'copy'}
assert manifest['video']['hasAudio'] and manifest['video']['height'] == 1920
assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths] == before
audio = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(paths[1]), '-vn', '-f', 's16le', '-'], capture_output=True, check=True).stdout
assert any(audio), 'Fixture audio must actually be audible'
subprocess.run(['ffmpeg', '-v', 'error', '-i', str(paths[1]), '-c:v', 'copy', '-an', '/media/no-audio.mp4'], check=True)
try:
    compose_campaign_pack(root, 'approved.png', 'no-audio.mp4', {})
except subprocess.SubprocessError:
    pass
else:
    raise AssertionError('Pack must reject missing audio')
(root / 'manifest.json').write_text(json.dumps(manifest))
'''
    subprocess.run(docker + ["python", "-c", script], check=True, timeout=90)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    for kind, size in (("story", (1080, 1920)), ("feed", (1080, 1080))):
        with Image.open(tmp_path / manifest[kind]["key"]) as image:
            image.load()
            assert image.size == size
        assert manifest[kind]["offer"] == "20% off"
        assert manifest[kind]["cta"] == "Shop now"
    assert manifest["copy"] == {"caption": "Campaign caption", "cta": "Shop now"}
