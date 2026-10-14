"""Server-only Supabase identity deletion for an already admitted deletion request."""
from contextlib import nullcontext
import os
from urllib.parse import urlsplit
import uuid

import httpx
import psycopg


def delete_requested_identity(database_url, account_id, *, client=None):
    account_id = uuid.UUID(str(account_id))
    with psycopg.connect(database_url) as connection:
        row = connection.execute("SELECT identity_deleted_at FROM app.account_deletions WHERE account_id=%s FOR UPDATE", (account_id,)).fetchone()
        if row is None:
            raise ValueError("An admitted account deletion request is required")
        if row[0] is not None:
            return False
        base = os.environ.get("SUPABASE_URL", "").rstrip("/")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        url = urlsplit(base)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.path or url.query or url.fragment or not key.strip():
            raise ValueError("A secure Supabase project URL and server-only service key are required")
        with (nullcontext(client) if client is not None else httpx.Client()) as http:
            try:
                response = http.request("DELETE", f"{base}/auth/v1/admin/users/{account_id}",
                    headers={"Authorization": f"Bearer {key}", "apikey": key},
                    json={"should_soft_delete": False}, follow_redirects=False, timeout=30)
            except httpx.TransportError:
                raise RuntimeError("Identity deletion outcome is unconfirmed; retry the recorded request") from None
        missing = False
        if response.status_code == 404:
            try:
                body = response.json()
                missing = isinstance(body, dict) and body.get("code") == "user_not_found"
            except ValueError:
                pass
        if response.status_code not in {200, 204} and not missing:
            raise RuntimeError("Identity deletion was not confirmed; check service configuration and retry")
        connection.execute("UPDATE app.account_deletions SET identity_deleted_at=clock_timestamp() WHERE account_id=%s", (account_id,))
    return True
