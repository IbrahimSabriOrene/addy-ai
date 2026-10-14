import uuid

import psycopg

from admaker.retention import expire_uploads
from admaker.media_drain import lock_media_writer
from test_worker_leases import URL, queued_job


def test_expiry_preserves_verified_media_and_active_writers(queued_job, tmp_path):
    owner, _, _, _ = queued_job
    pending, verified = uuid.uuid4(), uuid.uuid4()
    paths = []
    try:
        with psycopg.connect(URL) as c:
            for asset, state in ((pending, "pending"), (verified, "verified")):
                key = f"incoming/{owner}/{asset}.png"
                path = tmp_path / key
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"retained input")
                paths.append(path)
                c.execute("INSERT INTO app.assets(asset_key,owner_id,storage_key,mime_type,verification_state,created_at) VALUES (%s,%s,%s,'image/png',%s,now()-interval '1 hour')", (asset, owner, key, state))
        assert expire_uploads(URL, tmp_path)["removedUploads"] == 0
        assert all(path.exists() for path in paths)
        with psycopg.connect(URL) as writer:
            lock_media_writer(writer, owner)
            assert expire_uploads(URL, tmp_path, apply=True)["removedUploads"] == 0
        result = expire_uploads(URL, tmp_path, apply=True)
        assert result["removedUploads"] == 1
        assert not paths[0].exists() and paths[1].exists()
        assert expire_uploads(URL, tmp_path, apply=True)["removedUploads"] == 0
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT asset_key FROM app.assets WHERE asset_key=ANY(%s)", ([pending, verified],)).fetchall() == [(verified,)]
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.assets WHERE asset_key=ANY(%s)", ([pending, verified],))
