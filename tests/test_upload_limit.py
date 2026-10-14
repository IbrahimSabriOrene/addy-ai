import asyncio
import uuid
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from admaker.api import upload_bytes
from admaker.auth import Subject


def test_upload_stops_reading_at_limit(monkeypatch):
    monkeypatch.setattr("admaker.api.MAX_IMAGE_BYTES", 4)
    monkeypatch.setattr("admaker.api.lock_media_writer", lambda *args: None)  # Real locking is covered by test_media_drain.
    connection = SimpleNamespace(execute=lambda *args: SimpleNamespace(
        fetchone=lambda: ("incoming/test.jpg", "image/jpeg", "pending", True)))
    monkeypatch.setattr("admaker.api._connection", lambda: nullcontext(connection))
    chunks = iter([b"123", b"45"])

    async def receive():
        # Reading again after crossing the limit fails the test.
        return {"type": "http.request", "body": next(chunks), "more_body": True}

    request = Request({"type": "http", "headers": [(b"content-type", b"image/jpeg")]}, receive)
    with pytest.raises(HTTPException) as error:
        asyncio.run(upload_bytes(uuid.uuid4(), request, Subject(str(uuid.uuid4()), "test@example.com")))
    assert error.value.status_code == 422
