"""Real FFmpeg checks: run in the application image when unavailable on the host."""
import shutil
import subprocess

import pytest

from admaker.media import compose_video, validate_video


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="Requires FFmpeg application image")
def test_composition_preserves_audio_reuses_portrait_and_rejects_bad_media(tmp_path):
    source = tmp_path / "source with spaces.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=90x160:r=24",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "8",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)], check=True,
    )
    exports = compose_video(source, tmp_path, "job/run/1", ["tiktok", "reels", "stories", "feed"])
    assert exports["tiktok"]["key"] == exports["reels"]["key"] == exports["stories"]["key"]
    assert len(list((tmp_path / "runs").rglob("*.mp4"))) == 2
    for platform in ("tiktok", "feed"):
        path = tmp_path / exports[platform]["key"]
        assert validate_video(path)["hasAudio"]
        # The known audible source must survive composition, not be replaced with silence.
        audio = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
                                "-f", "s16le", "-"], check=True, capture_output=True).stdout
        assert any(audio)
        data = path.read_bytes()
        assert data.index(b"moov") < data.index(b"mdat")
    silent = tmp_path / "no-audio.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), "-an", "-c:v", "copy", str(silent)], check=True)
    with pytest.raises(subprocess.SubprocessError):
        compose_video(silent, tmp_path, "bad", ["tiktok"])
    assert not (tmp_path / "runs/bad").exists()
    with pytest.raises(ValueError):
        compose_video(source, tmp_path, "../../escape", ["tiktok"])
    with pytest.raises(ValueError):
        compose_video(source, tmp_path, "bad", ["../../escape"])
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(source.read_bytes()[:100])
    with pytest.raises(subprocess.SubprocessError):
        validate_video(broken)
    short_audio = tmp_path / "short-audio.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), "-filter:a", "atrim=duration=1",
                    "-c:v", "copy", str(short_audio)], check=True)
    with pytest.raises(subprocess.SubprocessError, match="full clip"):
        validate_video(short_audio)
    # Retain valid container metadata but corrupt compressed video/audio payloads.
    data = bytearray(source.read_bytes())
    start = data.index(b"mdat")
    end = start - 4 + int.from_bytes(data[start - 4:start], "big")
    data[start + 4:end] = b"\x00" * (end - start - 4)
    broken.write_bytes(data)
    with pytest.raises(subprocess.SubprocessError):
        validate_video(broken)
