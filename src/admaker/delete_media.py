"""Retryable local-file cleanup after account cutoff and writer drain."""
from pathlib import Path
import uuid

import psycopg
from admaker.deletion_media import account_media_inventory
from admaker.media_drain import try_lock_media_cleanup


def delete_requested_media(database_url, account_id, root):
    account_id = uuid.UUID(str(account_id))
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("A private storage directory is required")
    with psycopg.connect(database_url) as connection:
        if not try_lock_media_cleanup(connection, account_id):
            return {"state": "waiting_for_writers"}
        connection.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (account_id,)).fetchone()
        phase = connection.execute("SELECT media_deleted_at FROM app.account_deletions WHERE account_id=%s FOR UPDATE", (account_id,)).fetchone()
        if phase[0] is not None:
            return {"state": "media_removed", "alreadyComplete": True}
        inventory = account_media_inventory(connection, account_id, root)
        if inventory["pendingJobs"]:
            raise ValueError("Pending account jobs or reservations must be closed before cleanup")
        if any(item["status"] not in {"owned_file", "missing", "shared_reference"} for item in inventory["files"]):
            raise ValueError("Unsafe media references require review before cleanup")
        removed, shared = 0, 0
        for item in inventory["files"]:
            if item["status"] == "shared_reference":
                shared += 1
                continue
            path = root / item["key"]
            resolved = path.resolve()
            # Verify the final absolute target immediately before each unlink.
            if not resolved.is_relative_to(root) or resolved != path.absolute() or path.is_symlink():
                raise ValueError("Media path changed during cleanup")
            if path.exists():
                path.unlink()
                removed += 1
        connection.execute("UPDATE app.account_deletions SET media_deleted_at=clock_timestamp() WHERE account_id=%s", (account_id,))
    return {"state": "media_removed", "removedFiles": removed, "preservedShared": shared}
