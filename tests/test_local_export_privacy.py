import uuid
import hashlib

import psycopg
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from test_worker_leases import URL, queued_job


def test_local_export_is_owner_only_and_not_cacheable(queued_job, monkeypatch, tmp_path):
    owner, job, *_ = queued_job
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("LOCAL_ASSET_ROOT", str(tmp_path))
    (tmp_path / "output.mp4").write_bytes(b"private fixture")
    with psycopg.connect(URL) as c:
        c.execute("UPDATE app.jobs SET state='delivered',result=%s WHERE id=%s",
                  (Jsonb({"exports": {"tiktok": {"key": "output.mp4", "sha256": hashlib.sha256(b"private fixture").hexdigest()}}}), job))
    try:
        app.dependency_overrides[authenticated_subject] = lambda: Subject(str(owner), "fixture@example.test")
        with TestClient(app) as client:
            path = f"/v1/jobs/{job}/exports/tiktok"
            response = client.get(path)
            assert response.status_code == 200 and response.content == b"private fixture"
            assert response.headers["cache-control"] == "private, no-store"
            (tmp_path / "output.mp4").write_bytes(b"changed")
            assert client.get(path).status_code == 503
            app.dependency_overrides[authenticated_subject] = lambda: Subject(str(uuid.uuid4()), "other@example.test")
            assert client.get(path).status_code == 404
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
