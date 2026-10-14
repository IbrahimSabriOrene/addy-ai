import importlib.util
from pathlib import Path
import zipfile

import pytest

spec = importlib.util.spec_from_file_location("media_restore", Path(__file__).parents[1] / "tools/rehearse_media_restore.py")
media = importlib.util.module_from_spec(spec)
spec.loader.exec_module(media)


def test_media_backup_restores_exact_bytes_and_rejects_tampering(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "product.png").write_bytes(b"fixture product bytes")
    (source / "campaign.mp4").write_bytes(b"fixture video bytes")
    archive = tmp_path / "media.zip"
    manifest = media.backup_media(source, archive)
    media.restore_media(archive, tmp_path / "restored", manifest)
    for name in manifest:
        assert (source / name).read_bytes() == (tmp_path / "restored" / name).read_bytes()
    with zipfile.ZipFile(tmp_path / "corrupt.zip", "w") as bad:
        for name in manifest:
            bad.writestr(name, b"changed")
    with pytest.raises(ValueError, match="checksum"):
        media.restore_media(tmp_path / "corrupt.zip", tmp_path / "bad-restore", manifest)
    with zipfile.ZipFile(tmp_path / "escape.zip", "w") as bad:
        bad.writestr("../outside", b"bad")
    with pytest.raises(ValueError, match="escapes"):
        media.restore_media(tmp_path / "escape.zip", tmp_path / "escape", {"../outside": "irrelevant"})
    assert not (tmp_path / "outside").exists()
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="no media"):
        media.backup_media(empty, tmp_path / "empty.zip")
