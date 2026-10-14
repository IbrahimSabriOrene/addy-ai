"""Durable ownership before remote writes; uncertain uploads retain their cleanup record."""
import hashlib
import os
import uuid
from pathlib import Path
import tempfile

import psycopg

from admaker.cloud_storage import PrivateCloudStorage
from admaker.media_drain import lock_media_writer, try_lock_media_cleanup


class CloudPublicationPending(OSError):
    """Keep the current run and reservation while private output transfer is unconfirmed."""


def publish_job_outputs(database_url, job_id, root, exports, *, store=None):
    with psycopg.connect(database_url) as c:
        row = c.execute("SELECT owner_id FROM app.jobs WHERE id=%s", (job_id,)).fetchone()
        if row is None:
            raise ValueError("Owned job is unavailable")
        account_id = row[0]
    return publish_account_outputs(database_url, account_id, root, exports, store=store)


def publish_account_outputs(database_url, account_id, root, exports, *, store=None):
    root = Path(root).resolve()
    try:
        for item in exports.values():
            if not isinstance(item, dict) or not item.get('key'):
                continue  # Caption/CTA remain in the private database result.
            key = PrivateCloudStorage._key(item['key'])
            path = root / key
            if not path.exists():
                stage_private_object(database_url, account_id, key, root, store=store)
            if not path.resolve().is_relative_to(root) or any(p.is_symlink() for p in [path, *path.parents] if p != root and p.is_relative_to(root)):
                raise ValueError("Unsafe output publication path")
            if not path.is_file() or not 0 < path.stat().st_size <= 128 * 1024 * 1024:
                raise OSError("Output file is unavailable or exceeds the storage limit")
            content_type = item.get('mimeType') or {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.mp4': 'video/mp4', '.json': 'application/json'}.get(path.suffix.lower())
            content = path.read_bytes()
            if 'sha256' in item and hashlib.sha256(content).hexdigest() != item['sha256']:
                raise ValueError("Output differs from its recorded checksum")
            publish_private_object(database_url, account_id, key, content, content_type, store=store)
    except (OSError, ValueError):
        raise CloudPublicationPending("Private output publication is unconfirmed") from None


def configured_cloud_storage():
    return PrivateCloudStorage(os.environ.get("SUPABASE_URL", ""),
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""), os.environ.get("SUPABASE_STORAGE_BUCKET", ""))


def private_object_download_url(database_url, account_id, local_key, *, store=None):
    with psycopg.connect(database_url) as c:
        lock_media_writer(c, account_id)
        row = c.execute("SELECT object_key,origin,bucket,state FROM app.cloud_objects WHERE account_id=%s AND local_key=%s FOR SHARE", (account_id, local_key)).fetchone()
        if row is None:
            return None
        store = store or configured_cloud_storage()
        if row[3] != 'ready' or (row[1], row[2]) != (store.origin, store.bucket):
            raise ValueError("Private object is not ready at the configured destination")
        return store.signed_download(row[0], 60)


def stage_job_source(database_url, job_id, root, *, store=None):
    with psycopg.connect(database_url) as c:
        source = c.execute("SELECT j.owner_id,a.storage_key FROM app.jobs j JOIN app.assets a ON a.asset_key=j.source_asset_id AND a.owner_id=j.owner_id WHERE j.id=%s", (job_id,)).fetchone()
        if source is None:
            raise ValueError("Owned job source is unavailable")
        account_id, local_key = source
    return stage_private_object(database_url, account_id, local_key, root, store=store)


def stage_private_object(database_url, account_id, local_key, root, *, store=None):
    with psycopg.connect(database_url) as c:
        lock_media_writer(c, account_id)
        row = c.execute("SELECT object_key,origin,bucket,checksum,size_bytes,state FROM app.cloud_objects WHERE account_id=%s AND local_key=%s", (account_id, local_key)).fetchone()
        if row is None:
            return False
        PrivateCloudStorage._key(local_key)
        root = Path(root).resolve()
        destination = root / local_key
        if not destination.resolve().is_relative_to(root) or any(path.is_symlink() for path in [destination, *destination.parents] if path != root and path.is_relative_to(root)):
            raise ValueError("Unsafe private source staging path")
        if row[5] != 'ready':
            raise OSError("Cloud source is not verified")
        if destination.is_file():
            if destination.stat().st_size != row[4] or hashlib.sha256(destination.read_bytes()).hexdigest() != row[3]:
                raise OSError("Local source differs from verified cloud content")
            return True
        store = store or configured_cloud_storage()
        if (row[1], row[2]) != (store.origin, store.bucket):
            raise ValueError("Cloud source destination changed")
        content = store.download(row[0], row[4])
        if content is None or len(content) != row[4] or hashlib.sha256(content).hexdigest() != row[3]:
            raise OSError("Downloaded source failed content verification")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as file:
                temporary = Path(file.name)
                file.write(content)
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return True


def publish_private_object(database_url, account_id, local_key, content, content_type, *, store=None):
    account_id = uuid.UUID(str(account_id))
    store = store or configured_cloud_storage()
    PrivateCloudStorage._key(local_key)
    if not isinstance(content, bytes) or not 0 < len(content) <= 128 * 1024 * 1024:
        raise ValueError("Invalid private object content size")
    if content_type not in {"image/png", "image/jpeg", "image/webp", "video/mp4", "application/json"}:
        raise ValueError("Unsupported private media type")
    checksum = hashlib.sha256(content).hexdigest()
    object_key = f"objects/{account_id}/{hashlib.sha256(local_key.encode()).hexdigest()}/{checksum}"
    with psycopg.connect(database_url) as c:
        lock_media_writer(c, account_id)
        registered = c.execute("""INSERT INTO app.cloud_objects(account_id,local_key,object_key,origin,bucket,checksum,size_bytes,content_type,state)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending') ON CONFLICT(account_id,local_key) DO NOTHING RETURNING object_key""",
            (account_id, local_key, object_key, store.origin, store.bucket, checksum, len(content), content_type)).fetchone()
        if not registered:
            registered = c.execute("""UPDATE app.cloud_objects SET state='pending' WHERE account_id=%s AND local_key=%s
                AND state='verified_absent' AND object_key=%s AND origin=%s AND bucket=%s AND checksum=%s
                AND size_bytes=%s AND content_type=%s RETURNING object_key""",
                (account_id, local_key, object_key, store.origin, store.bucket, checksum, len(content), content_type)).fetchone()
    # Registration commits first so a crash during the external write cannot orphan the key.
    with psycopg.connect(database_url) as c:
        lock_media_writer(c, account_id)
        row = c.execute("""SELECT object_key,origin,bucket,checksum,size_bytes,content_type FROM app.cloud_objects
            WHERE account_id=%s AND local_key=%s FOR UPDATE""", (account_id, local_key)).fetchone()
        if row != (object_key, store.origin, store.bucket, checksum, len(content), content_type):
            raise ValueError("Private object content or storage destination changed")
        remote = store.download(object_key, len(content))
        if remote is None:
            if not registered:
                raise OSError("Prior cloud upload is unconfirmed; retain the record for reconciliation")
            store.upload(object_key, content, content_type)
            remote = store.download(object_key, len(content))
        if remote is None or len(remote) != len(content) or hashlib.sha256(remote).hexdigest() != checksum:
            raise OSError("Private object content was not verified")
        c.execute("UPDATE app.cloud_objects SET state='ready' WHERE account_id=%s AND local_key=%s", (account_id, local_key))
    return object_key


def delete_requested_cloud_objects(database_url, account_id, *, store=None):
    account_id = uuid.UUID(str(account_id))
    with psycopg.connect(database_url) as c:
        if not try_lock_media_cleanup(c, account_id):
            return {"state": "waiting_for_writers"}
        rows = c.execute("SELECT object_key,origin,bucket,state FROM app.cloud_objects WHERE account_id=%s ORDER BY object_key FOR UPDATE", (account_id,)).fetchall()
        if rows:
            store = store or configured_cloud_storage()
            if any((origin, bucket) != (store.origin, store.bucket) for _, origin, bucket, _ in rows):
                raise ValueError("Cloud cleanup destination differs from recorded ownership")
            for key, _, _, state in rows:
                if state == 'pending' and store.download(key) is None:
                    raise OSError("Pending cloud upload is unconfirmed; cleanup cannot complete")
                store.remove(key)
                if store.download(key) is not None:
                    raise OSError("Cloud object deletion was not confirmed")
            c.execute("DELETE FROM app.cloud_objects WHERE account_id=%s", (account_id,))
    return {"state": "cloud_removed"}
