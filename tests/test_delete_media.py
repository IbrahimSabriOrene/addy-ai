from pathlib import Path
import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

from admaker.account_deletion import request_account_deletion
from admaker.delete_media import delete_requested_media
from admaker.media_drain import lock_media_writer
from test_worker_leases import URL, queued_job


def test_unsafe_inventory_prevents_any_unlink(queued_job, tmp_path):
    account, job, reservation, queue = queued_job
    (tmp_path / "test.png").write_bytes(b"must remain")
    try:
        with psycopg.connect(URL) as c:
            c.execute("UPDATE app.jobs SET result=%s WHERE id=%s", (Jsonb({"exports": {"video": {"key": "../outside.mp4"}}}), job))
            request_account_deletion(c, account)
        with pytest.raises(ValueError, match="Unsafe media references"):
            delete_requested_media(URL, account, tmp_path)
        assert (tmp_path / "test.png").read_bytes() == b"must remain"
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT media_deleted_at FROM app.account_deletions WHERE account_id=%s", (account,)).fetchone() == (None,)
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.account_deletions WHERE account_id=%s", (account,))


def test_cleanup_drains_retries_partial_unlink_and_preserves_shared_data(queued_job, tmp_path, monkeypatch):
    account, job, reservation, queue = queued_job
    other, asset = uuid.uuid4(), uuid.uuid4()
    keys = [f"incoming/{account}/first.png", f"incoming/{account}/second.png", "test.png", "shared.png"]
    for key in keys:
        path = tmp_path / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    with psycopg.connect(URL) as c:
        c.execute("INSERT INTO app.accounts(id,email) VALUES (%s,'other@example.com')", (other,))
        c.execute("INSERT INTO app.assets(asset_key,owner_id,storage_key,mime_type) VALUES (%s,%s,'shared.png','image/png')", (asset, other))
        c.execute("UPDATE app.jobs SET result=%s WHERE id=%s", (Jsonb({"exports": {"image": {"key": "shared.png"}}}), job))
    original = Path.unlink
    try:
        with pytest.raises(ValueError):
            delete_requested_media(URL, account, tmp_path)
        with psycopg.connect(URL) as writer:
            lock_media_writer(writer, account)
            with psycopg.connect(URL) as c:
                request_account_deletion(c, account)
            assert delete_requested_media(URL, account, tmp_path) == {"state": "waiting_for_writers"}

        def fail_second(path, *args, **kwargs):
            if path.name == "second.png":
                raise PermissionError("Injected interruption")
            return original(path, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(Path, "unlink", fail_second)
            with pytest.raises(PermissionError):
                delete_requested_media(URL, account, tmp_path)
        assert not (tmp_path / keys[0]).exists()
        assert (tmp_path / keys[1]).exists()
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT media_deleted_at FROM app.account_deletions WHERE account_id=%s", (account,)).fetchone() == (None,)
        result = delete_requested_media(URL, account, tmp_path)
        assert result["state"] == "media_removed" and result["preservedShared"] == 1
        assert all(not (tmp_path / key).exists() for key in keys[:3])
        assert (tmp_path / "shared.png").read_bytes() == b"fixture"
        assert delete_requested_media(URL, account, tmp_path) == {"state": "media_removed", "alreadyComplete": True}
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT state,completed_at FROM app.account_deletions WHERE account_id=%s", (account,)).fetchone() == ("requested", None)
            assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.account_deletions WHERE account_id=%s", (account,))
            c.execute("DELETE FROM app.assets WHERE asset_key=%s", (asset,))
            c.execute("DELETE FROM app.accounts WHERE id=%s", (other,))
