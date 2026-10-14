import uuid

import psycopg
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.db import migrate
from test_uploads import _image
from test_worker_leases import URL


def test_upload_cloud_recovery_and_owner_only_signed_asset(monkeypatch, tmp_path):
    migrate(URL)
    owner = Subject(str(uuid.uuid4()), 'cloud-upload@example.test')
    monkeypatch.setenv('DATABASE_URL', URL)
    monkeypatch.setenv('LOCAL_ASSET_ROOT', str(tmp_path))
    monkeypatch.setenv('PUBLISH_PRIVATE_UPLOADS', 'true')
    class Store:
        origin, bucket = 'https://cloud.test', 'private'
        objects = {}
        uploads = 0
        signed = 0
        def download(self, key, max_bytes=None):
            return self.objects.get(key)
        def upload(self, key, content, content_type):
            self.uploads += 1
            self.objects[key] = content
            if self.uploads == 1:
                raise OSError('Lost acknowledgement')
        def signed_download(self, key, expires_in):
            assert expires_in == 60
            self.signed += 1
            return f'https://cloud.test/storage/v1/object/sign/private/{key}?token=fixture'
    store = Store()
    monkeypatch.setattr('admaker.cloud_objects.configured_cloud_storage', lambda: store)
    app.dependency_overrides[authenticated_subject] = lambda: owner
    try:
        with TestClient(app) as client:
            image = _image()
            created = client.post('/v1/uploads/presign', json={'mimeType': 'image/jpeg', 'sizeBytes': len(image)})
            asset = created.json()['assetKey']
            assert client.put(f'/v1/uploads/{asset}', content=image, headers={'Content-Type': 'image/jpeg'}).status_code == 204
            payload = {'assetKey': asset}
            assert client.post('/v1/uploads/complete', json=payload).status_code == 503
            with psycopg.connect(URL) as c:
                assert c.execute('SELECT verification_state FROM app.assets WHERE asset_key=%s', (asset,)).fetchone() == ('pending',)
            assert client.post('/v1/uploads/complete', json=payload).status_code == 200
            assert store.uploads == 2  # Original upload recovered; only verified copy was new.
            assert client.post('/v1/uploads/complete', json=payload).status_code == 200
            assert store.uploads == 2
            response = client.get(f'/v1/assets/{asset}', follow_redirects=False)
            assert response.status_code == 302 and response.headers['cache-control'] == 'private, no-store'
            assert response.headers['location'].startswith('https://cloud.test/')
            app.dependency_overrides[authenticated_subject] = lambda: Subject(str(uuid.uuid4()), 'other@example.test')
            assert client.get(f'/v1/assets/{asset}', follow_redirects=False).status_code == 404
            assert store.signed == 1
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
        with psycopg.connect(URL) as c:
            c.execute('DELETE FROM app.cloud_objects WHERE account_id=%s', (owner.id,))
            c.execute('DELETE FROM app.assets WHERE owner_id=%s', (owner.id,))
            c.execute('DELETE FROM app.accounts WHERE id=%s', (owner.id,))
