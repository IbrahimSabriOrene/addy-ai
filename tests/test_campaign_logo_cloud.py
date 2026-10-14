import hashlib
import uuid

import psycopg
import pytest

from admaker.campaign_logo import stage_campaign_logo
from admaker.cloud_objects import publish_private_object
from test_worker_leases import URL, queued_job


def test_logo_recovers_private_upload_once_and_rejects_other_accounts(queued_job, monkeypatch, tmp_path):
    account, job, _, _ = queued_job
    monkeypatch.setenv("DATABASE_URL", URL)
    data = b"verified logo fixture; decoder covered by renderer tests"
    class Store:
        origin, bucket = "https://logo.test", "private"
        objects = {}
        uploads = 0
        reads = 0
        def upload(self, key, content, content_type):
            self.uploads += 1
            self.objects[key] = content
            raise OSError("Lost acknowledgement")
        def download(self, key, max_bytes=None):
            self.reads += 1
            return self.objects.get(key)
    store = Store()
    monkeypatch.setattr("admaker.cloud_objects.configured_cloud_storage", lambda: store)
    with psycopg.connect(URL) as c:
        asset = c.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (job,)).fetchone()[0]
        c.execute("UPDATE app.assets SET checksum=%s WHERE asset_key=%s", (hashlib.sha256(data).hexdigest(), asset))
    try:
        with pytest.raises(OSError):
            publish_private_object(URL, account, "test.png", data, "image/png", store=store)
        publish_private_object(URL, account, "test.png", data, "image/png", store=store)
        assert store.uploads == 1
        brief = {"logoAssetKey": str(asset)}
        with psycopg.connect(URL) as c:
            reads = store.reads
            with pytest.raises(ValueError, match="belonging"):
                stage_campaign_logo(c, uuid.uuid4(), brief, tmp_path)
            assert store.reads == reads and not (tmp_path / "test.png").exists()
            path = stage_campaign_logo(c, account, brief, tmp_path)
            assert path.read_bytes() == data
            assert store.uploads == 1
            path.unlink()
            store.objects = {key: b"corrupt" for key in store.objects}
            with pytest.raises((ValueError, OSError)):
                stage_campaign_logo(c, account, brief, tmp_path)
            assert not path.exists()
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.cloud_objects WHERE account_id=%s", (account,))
