"""Private local upload storage for local development and contract tests."""

from __future__ import annotations

from pathlib import Path


class LocalPrivateStorage:
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        return self.root / key

    def write(self, key: str, content: bytes) -> None:
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def read(self, key: str) -> bytes:
        return self.path(key).read_bytes()
