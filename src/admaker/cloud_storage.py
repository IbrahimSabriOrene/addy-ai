"""Server-only private object operations; owner authorization belongs to callers."""
from contextlib import contextmanager
import json
import re
from urllib.parse import urlsplit

import httpx
from storage3 import SyncStorageClient


class PrivateCloudStorage:
    def __init__(self, origin, service_key, bucket, *, transport=None):
        url = urlsplit(origin)
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.path not in {"", "/"} or url.query or url.fragment or not service_key.strip()
                or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", bucket)):
            raise ValueError("Secure storage origin, server key and private bucket are required")
        self.origin, self.bucket = origin.rstrip("/"), bucket
        self._headers = {"Authorization": f"Bearer {service_key}", "apikey": service_key}
        self._transport = transport

    @staticmethod
    def _key(key):
        if (not isinstance(key, str) or not 1 <= len(key) <= 1024
                or not re.fullmatch(r"[A-Za-z0-9_./-]+", key)
                or any(part in {"", ".", ".."} for part in key.split("/"))):
            raise ValueError("Invalid private object key")
        return key

    @contextmanager
    def _files(self):
        with httpx.Client(headers=self._headers, timeout=30, follow_redirects=False, transport=self._transport) as http:
            storage = SyncStorageClient(self.origin + "/storage/v1/", self._headers, http_client=http)
            try:
                bucket = storage.get_bucket(self.bucket)
                if bucket.public is not False:
                    raise ValueError("Storage bucket must be private")
                yield storage.from_(self.bucket)
            except Exception:
                # SDK exceptions can include response data and authenticated URLs.
                raise OSError("Private storage operation was not confirmed") from None

    def upload(self, key, content, content_type):
        key = self._key(key)
        if content_type not in {"image/png", "image/jpeg", "image/webp", "video/mp4", "application/json"}:
            raise ValueError("Unsupported private media type")
        if not isinstance(content, bytes) or not 0 < len(content) <= 128 * 1024 * 1024:
            raise ValueError("Private media must contain at most 128 MiB")
        with self._files() as files:
            files.upload(key, content, {"content-type": content_type, "upsert": "false", "cache-control": "0"})

    def signed_download(self, key, expires_in=60):
        key = self._key(key)
        if type(expires_in) is not int or not 1 <= expires_in <= 300:
            raise ValueError("Signed download lifetime must be 1..300 seconds")
        with self._files() as files:
            value = files.create_signed_url(key, expires_in)["signedURL"]
        parsed = urlsplit(value)
        expected = urlsplit(self.origin)
        if (parsed.scheme != "https" or parsed.netloc != expected.netloc or parsed.username or parsed.password
                or parsed.path != f"/storage/v1/object/sign/{self.bucket}/{key}" or not parsed.query or parsed.fragment):
            raise OSError("Invalid private download response")
        return value

    def download(self, key, max_bytes=128 * 1024 * 1024):
        key = self._key(key)
        if type(max_bytes) is not int or not 1 <= max_bytes <= 128 * 1024 * 1024:
            raise ValueError("Invalid private download size limit")
        with self._files():
            with httpx.Client(headers=self._headers, timeout=30, follow_redirects=False, transport=self._transport) as http:
                with http.stream("GET", f"{self.origin}/storage/v1/object/authenticated/{self.bucket}/{key}") as response:
                    if response.status_code == 404:
                        error_body = bytearray()
                        for chunk in response.iter_bytes():
                            if len(error_body) + len(chunk) > 4096:
                                raise OSError("Unrecognized missing-object response")
                            error_body.extend(chunk)
                        if json.loads(error_body).get("code") == "NoSuchKey":
                            return None
                        raise OSError("Unrecognized missing-object response")
                    response.raise_for_status()
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        if len(data) + len(chunk) > max_bytes:
                            raise OSError("Private object exceeds its recorded size")
                        data.extend(chunk)
                    return bytes(data)

    def remove(self, key):
        key = self._key(key)
        with self._files() as files:
            result = files.remove([key])
            if not isinstance(result, list):
                raise OSError("Private object deletion was not confirmed")
