import hashlib
import json

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.cloud_objects import publish_private_object, delete_requested_cloud_objects
from admaker.delete_media import delete_requested_media
from admaker.deletion_media import account_media_inventory
from test_provider_graph import provider_job
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("cutoff_during_download", [False, True])
def test_photo_registration_cloud_restore_and_deletion_cutoff(provider_job, monkeypatch, tmp_path, cutoff_during_download):
    account, job, reservation, _ = provider_job
    content = (tmp_path / "test.png").read_bytes()
    key = f"runs/{job}/photo.png"
    checksum = hashlib.sha256(content).hexdigest()
    result = {"exports": {"feed_square": {"key": key, "sha256": checksum, "mimeType": "image/png"}}}
    with psycopg.connect(URL) as connection:
        connection.execute("UPDATE app.jobs SET state='delivered',settings=%s,result=%s WHERE id=%s",
            (Jsonb({"outputKind": "photo"}), Jsonb(result), job))
        connection.execute("UPDATE app.credit_reservations SET state='released' WHERE id=%s", (reservation,))
    class Store:
        origin, bucket = "https://fixture.test", "private"
        armed = False
        uploads = 0
        objects = {}
        def upload(self, name, data, mime):
            self.uploads += 1
            self.objects[name] = data
        def download(self, name, max_bytes=None):
            if self.armed and cutoff_during_download:
                self.armed = False
                with psycopg.connect(URL) as connection:
                    connection.execute("INSERT INTO app.account_deletions(account_id) VALUES (%s)", (account,))
                assert delete_requested_media(URL, account, tmp_path) == {"state": "waiting_for_writers"}
            return self.objects.get(name)
        def remove(self, name):
            self.objects.pop(name, None)
    store = Store()
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "photo-cloud@example.test")
    monkeypatch.setattr("admaker.cloud_objects.configured_cloud_storage", lambda: store)
    try:
        publish_private_object(URL, account, key, content, "image/png", store=store)
        store.armed = True
        with TestClient(app) as client:
            route = f"/v1/jobs/{job}/photo-asset"
            payload = {"platform": "feed", "expectedResultVersion": hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()}
            response = client.post(route, json=payload)
            assert response.status_code == (410 if cutoff_during_download else 200), response.text
            assert (tmp_path / key).read_bytes() == content
            with psycopg.connect(URL) as connection:
                assert connection.execute("SELECT count(*) FROM app.assets WHERE owner_id=%s AND storage_key=%s", (account, key)).fetchone() == (0 if cutoff_during_download else 1,)
                inventory = account_media_inventory(connection, account, tmp_path)
                assert [item for item in inventory["files"] if item["key"] == key] == [{"key": key, "status": "owned_file"}]
            if not cutoff_during_download:
                assert client.post(route, json=payload).json() == response.json()
                with psycopg.connect(URL) as connection:
                    connection.execute("INSERT INTO app.account_deletions(account_id) VALUES (%s)", (account,))
            assert client.post(route, json=payload).status_code == 410
        assert store.uploads == 1
        assert delete_requested_cloud_objects(URL, account, store=store) == {"state": "cloud_removed"}
        assert delete_requested_media(URL, account, tmp_path)["state"] == "media_removed"
        assert not store.objects and not (tmp_path / key).exists()
    finally:
        app.dependency_overrides.clear()
        with psycopg.connect(URL) as connection:
            connection.execute("DELETE FROM app.cloud_objects WHERE account_id=%s", (account,))
            connection.execute("DELETE FROM app.account_deletions WHERE account_id=%s", (account,))
            connection.execute("DELETE FROM app.assets WHERE owner_id=%s AND storage_key=%s", (account, key))
