"""Owned Gemini file intents survive lost upload replies and gate account cleanup."""
import base64
import hashlib
import io
import os
import uuid
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace

import psycopg
from google import genai
from google.genai import errors, types

from admaker.consent import require_ai_consent
from admaker.media_drain import lock_media_writer, try_lock_media_cleanup


MAX_REVIEW_FILE_BYTES = 128 * 1024 * 1024


class ReviewFileProcessing(OSError):
    """A verified named upload is processing; poll it without another upload."""


@contextmanager
def review_file_client():
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    if not key.strip() or os.environ.get("GOOGLE_API_KEY", key) != key:
        raise ValueError("Consistent review credentials are required")
    # A key fingerprint prevents treating another project's 404 as deletion proof.
    with genai.Client(api_key=key, vertexai=False, http_options=types.HttpOptions(
        api_version="v1beta", timeout=60000, retry_options=types.HttpRetryOptions(attempts=1),
    )) as client:
        yield SimpleNamespace(files=client.files, credential_hash=hashlib.sha256(key.encode()).hexdigest())


def get_review_file(store, name):
    try:
        return store.files.get(name=name)
    except errors.ClientError as error:
        if error.code == 404:
            return None
        raise


def verified_review_file(remote, name, checksum, size, mime):
    if (remote.name != name or remote.size_bytes != size or remote.mime_type != mime
            or remote.sha256_hash != base64.b64encode(bytes.fromhex(checksum)).decode()
            or remote.uri != f"https://generativelanguage.googleapis.com/v1beta/{name}"):
        raise ValueError("Provider file identity was not verified")
    return remote.state == types.FileState.ACTIVE


def stage_review_file(database_url, job_id, data, mime, *, store):
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_REVIEW_FILE_BYTES:
        raise ValueError("Review file exceeds the storage limit")
    if mime not in {"image/png", "image/jpeg", "image/webp", "video/mp4"}:
        raise ValueError("Unsupported review media")
    checksum = hashlib.sha256(data).hexdigest()
    with psycopg.connect(database_url) as connection:
        row = connection.execute("SELECT owner_id FROM app.jobs WHERE id=%s", (job_id,)).fetchone()
        if not row:
            raise ValueError("Owned review job is unavailable")
        account = row[0]
        lock_media_writer(connection, account)
        require_ai_consent(str(account))
        inserted = connection.execute("""INSERT INTO app.review_files
            (account_id,checksum,mime_type,size_bytes,file_name,credential_hash,state)
            VALUES (%s,%s,%s,%s,%s,%s,'pending') ON CONFLICT DO NOTHING RETURNING file_name""",
            (account, checksum, mime, len(data), f"files/addy-{uuid.uuid4().hex}", store.credential_hash)).fetchone()
        if not inserted:
            inserted = connection.execute("""UPDATE app.review_files SET file_name=%s,state='pending',created_at=clock_timestamp()
                WHERE account_id=%s AND checksum=%s AND mime_type=%s AND size_bytes=%s
                AND credential_hash=%s AND state='verified_absent' RETURNING file_name""",
                (f"files/addy-{uuid.uuid4().hex}", account, checksum, mime, len(data), store.credential_hash)).fetchone()
    # Commit intent before network I/O. Only the inserter may issue the upload.
    with psycopg.connect(database_url) as connection:
        lock_media_writer(connection, account)
        name, size, credential = connection.execute("""SELECT file_name,size_bytes,credential_hash
            FROM app.review_files WHERE account_id=%s AND checksum=%s AND mime_type=%s FOR UPDATE""",
            (account, checksum, mime)).fetchone()
        if size != len(data) or credential != store.credential_hash:
            raise ValueError("Review file destination changed")
        require_ai_consent(str(account))
        remote = get_review_file(store, name)
        if remote is None:
            if not inserted:
                raise OSError("Previous review file upload is unconfirmed; never automatically re-upload")
            remote = store.files.upload(file=io.BytesIO(data), config=types.UploadFileConfig(name=name, mime_type=mime))
        active = verified_review_file(remote, name, checksum, size, mime)
        if remote.state not in {types.FileState.ACTIVE, types.FileState.PROCESSING}:
            raise OSError("Provider file processing failed")
        connection.execute("UPDATE app.review_files SET state=%s WHERE file_name=%s", ("ready" if active else "processing", name))
    if not active:
        raise ReviewFileProcessing("Review file is processing; resume by checking the same file")
    return remote.uri


def delete_requested_review_files(database_url, account_id, *, store=None):
    account_id = uuid.UUID(str(account_id))
    with psycopg.connect(database_url) as connection:
        if not try_lock_media_cleanup(connection, account_id):
            return {"state": "waiting_for_writers"}
        rows = connection.execute("""SELECT file_name,credential_hash,state,checksum,size_bytes,mime_type
            FROM app.review_files WHERE account_id=%s ORDER BY file_name""", (account_id,)).fetchall()
        if rows:
            with nullcontext(store) if store is not None else review_file_client() as client:
                for name, credential, state, checksum, size, mime in rows:
                    if credential != client.credential_hash:
                        raise ValueError("Review cleanup credentials differ from the recorded destination")
                    remote = get_review_file(client, name)
                    if remote is None and state == "pending":
                        raise OSError("Unconfirmed upload cannot be forgotten during deletion")
                    if remote is not None:
                        verified_review_file(remote, name, checksum, size, mime)
                        # The exclusive account cleanup lock remains held by the outer
                        # connection. Persist observed acceptance before a lossy DELETE.
                        if state == "pending":
                            with psycopg.connect(database_url) as receipt:
                                receipt.execute("UPDATE app.review_files SET state='processing' WHERE account_id=%s AND file_name=%s", (account_id, name))
                        client.files.delete(name=name)
                        if get_review_file(client, name) is not None:
                            raise OSError("Provider file deletion was not confirmed")
                connection.execute("DELETE FROM app.review_files WHERE account_id=%s", (account_id,))
    return {"state": "review_files_removed"}
