"""AssetStore interface (PLAN.md "Storage").

put/get/presign/delete behind one interface: local-disk impl for MVP,
S3/GCS for v1 — a swap at ``build_graph`` time, nothing in the nodes
changes. Retention policy (source + finals 90d, intermediates 7d, cleaned-
image cache survives intermediate cleanup) is a storage-layer concern, not
encoded in the graph.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class AssetStore(Protocol):
    def put(self, key: str, data: bytes) -> str:
        """Store bytes under key; return a URL/URI the pipeline can pass on."""
        ...

    def put_url(self, key: str, source_url: str) -> str:
        """Register an already-hosted asset (e.g. a Decart output URL) under
        key without re-uploading; return the canonical URL."""
        ...

    def get(self, key: str) -> bytes: ...

    def presign(self, key: str) -> str:
        """A shareable URL for the app to hand to the client."""
        ...

    def delete(self, key: str) -> None: ...


class LocalDiskAssetStore:
    """MVP impl: a directory tree under ``root``. ``put_url`` just records the
    mapping (the URL stays external) so we don't download Decart outputs
    during offline runs."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._url_map: dict[str, str] = {}

    def _path(self, key: str) -> Path:
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def put(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.write_bytes(data)
        return path.as_uri()

    def put_url(self, key: str, source_url: str) -> str:
        self._url_map[key] = source_url
        return source_url

    def get(self, key: str) -> bytes:
        if key in self._url_map:
            raise KeyError(f"{key} is an external URL, not local bytes")
        return self._path(key).read_bytes()

    def presign(self, key: str) -> str:
        if key in self._url_map:
            return self._url_map[key]
        return self._path(key).as_uri()

    def delete(self, key: str) -> None:
        self._url_map.pop(key, None)
        path = self.root / key
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()
