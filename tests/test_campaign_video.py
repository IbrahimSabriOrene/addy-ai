"""Real codec evidence, executable offline in the application image."""
import hashlib
import shutil
import subprocess

import pytest
from PIL import Image

from admaker.campaign_video import render_campaign_video


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="Requires FFmpeg application image")
def test_video_offer_edits_preserve_source_and_exact_audio(tmp_path):
    source = tmp_path / "source with spaces.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=1080x1920:r=24",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "8",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)], check=True)
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (40, 40), "blue").save(logo)
    audio = lambda path: subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
                                        "-c:a", "copy", "-f", "adts", "-"], check=True, capture_output=True).stdout
    expected_audio = audio(source)
    frames = []
    for index, offer in enumerate(("20% ' : [x]", "15% ' : [x]")):
        item = render_campaign_video(source, tmp_path / str(index), {"offer": offer, "cta": "Shop", "color": "#FFFFFF"}, logo)
        assert item["offer"] == offer and item["hasAudio"] and item["width"] == 1080
        assert audio(item["path"]) == expected_audio
        frame = subprocess.run(["ffmpeg", "-v", "error", "-i", item["path"], "-frames:v", "1",
                                "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, capture_output=True).stdout
        image = Image.frombytes("RGB", (1080, 1920), frame)
        red, green, blue = image.getpixel((540, 960))
        assert red > 240 and green < 20 and blue < 20
        red, green, blue = image.getpixel((540, 100))
        assert blue > 240 and red < 20 and green < 20
        frames.append(image.crop((90, 200, 990, 460)).tobytes())
    assert frames[0] != frames[1]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original
    assert not list(tmp_path.glob("*/tmp*"))
    with pytest.raises(ValueError):
        render_campaign_video(source, tmp_path / "invalid", {"offer": "bad\x00"})
    assert not (tmp_path / "invalid").exists()
