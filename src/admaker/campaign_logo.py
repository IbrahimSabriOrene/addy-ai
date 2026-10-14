"""Resolve a campaign logo through the existing private verified upload store."""
import hashlib
import os
import uuid
from pathlib import Path


def owned_logo(connection, account_id, asset_key):
    key = uuid.UUID(str(asset_key))
    row = connection.execute(
        "SELECT storage_key,checksum FROM app.assets WHERE asset_key=%s AND owner_id=%s "
        "AND verification_state='verified' AND mime_type IN ('image/png','image/jpeg','image/webp')",
        (key, account_id),
    ).fetchone()
    if not row:
        raise ValueError("A verified logo belonging to this account is required")
    return row


def stage_campaign_logo(connection, account_id, brief, root: Path):
    key = brief.get("logoAssetKey")
    if key is None:
        return None
    storage_key, checksum = owned_logo(connection, account_id, key)
    root = root.resolve()
    path = (root / storage_key).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Campaign logo is unavailable")
    from admaker.cloud_objects import stage_private_object
    stage_private_object(os.environ["DATABASE_URL"], account_id, storage_key, root)
    with path.open("rb") as stream:
        data = stream.read(10 * 1024 * 1024 + 1)
    if not data or len(data) > 10 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != checksum:
        raise ValueError("Campaign logo failed verification")
    return path
