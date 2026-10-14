import hashlib

import pytest

from admaker import cloud_objects


def test_publication_rejects_changed_reviewed_bytes_before_remote_write(tmp_path, monkeypatch):
    path = tmp_path / "video.mp4"
    original = b"reviewed output"
    manifest = {"video": {"key": path.name, "sha256": hashlib.sha256(original).hexdigest()}}
    writes = []
    monkeypatch.setattr(cloud_objects, "publish_private_object", lambda *args, **kwargs: writes.append(args[3]))
    path.write_bytes(b"changed output")
    with pytest.raises(cloud_objects.CloudPublicationPending):
        cloud_objects.publish_account_outputs("unused", "unused", tmp_path, manifest)
    assert writes == []
    path.write_bytes(original)
    cloud_objects.publish_account_outputs("unused", "unused", tmp_path, manifest)
    assert writes == [original]
