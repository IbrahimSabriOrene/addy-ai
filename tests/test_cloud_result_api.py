import uuid

import psycopg
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.cloud_objects import publish_private_object
from test_worker_leases import URL, queued_job


def test_cloud_pack_is_available_without_local_files_and_remains_private(queued_job, monkeypatch, tmp_path):
    owner, job, reservation, queue = queued_job
    product, campaign = uuid.uuid4(), uuid.uuid4()
    class Store:
        origin, bucket = 'https://results.test', 'private'
        objects = {}
        signed = 0
        def upload(self, key, content, content_type):
            self.objects[key] = content
        def download(self, key, max_bytes=None):
            return self.objects.get(key)
        def signed_download(self, key, expires_in):
            self.signed += 1
            assert expires_in == 60
            return f'https://results.test/storage/v1/object/sign/private/{key}?token=fixture'
    store = Store()
    monkeypatch.setenv('DATABASE_URL', URL)
    monkeypatch.setenv('LOCAL_ASSET_ROOT', str(tmp_path))
    monkeypatch.setattr('admaker.cloud_objects.configured_cloud_storage', lambda: store)
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(owner), 'result@example.test')
    try:
        exports = {'copy': {'caption': 'Exact offer', 'cta': 'Shop'}}
        for kind in ['cleanImage', 'video', 'story', 'feed']:
            key = f'campaign-runs/fixture/{kind}.mp4' if kind == 'video' else f'campaign-runs/fixture/{kind}.png'
            mime = 'video/mp4' if kind == 'video' else 'image/png'
            publish_private_object(URL, owner, key, b'fixture', mime, store=store)
            exports[kind] = {'key': key, 'mimeType': mime}
        with psycopg.connect(URL) as c:
            asset = c.execute('SELECT source_asset_id FROM app.jobs WHERE id=%s', (job,)).fetchone()[0]
            c.execute("INSERT INTO app.products(id,owner_id,name,source_asset_id) VALUES (%s,%s,'Fixture',%s)", (product, owner, asset))
            c.execute('INSERT INTO app.product_images(product_id,owner_id,version,asset_key) VALUES (%s,%s,1,%s)', (product, owner, asset))
            c.execute("INSERT INTO app.campaigns(id,owner_id,product_id,image_version,brief) VALUES (%s,%s,%s,1,'{}')", (campaign, owner, product))
            c.execute('INSERT INTO app.campaign_generations(campaign_id,campaign_version,job_id,price_credits) VALUES (%s,1,%s,3)', (campaign, job))
            c.execute("UPDATE app.jobs SET state='delivered',result=%s WHERE id=%s", (Jsonb({'exports': exports}), job))
        with TestClient(app) as client:
            base = f'/v1/campaigns/{campaign}/generations/1'
            result = client.get(base).json()
            assert result['state'] == 'delivered'
            assert all(item['state'] == 'ready' for item in result['outputs'].values())
            for path in [base + '/video', f'/v1/jobs/{job}/exports/video']:
                response = client.get(path, follow_redirects=False)
                assert response.status_code == 302 and response.headers['cache-control'] == 'private, no-store'
            assert not list(tmp_path.iterdir())
            app.dependency_overrides[authenticated_subject] = lambda: Subject(str(uuid.uuid4()), 'other@example.test')
            assert client.get(base).status_code == 404
            assert client.get(base + '/video', follow_redirects=False).status_code == 404
            assert client.get(f'/v1/jobs/{job}/exports/video', follow_redirects=False).status_code == 404
            assert store.signed == 2
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
        with psycopg.connect(URL) as c:
            c.execute('DELETE FROM app.cloud_objects WHERE account_id=%s', (owner,))
            c.execute('DELETE FROM app.campaign_generations WHERE campaign_id=%s', (campaign,))
            c.execute('DELETE FROM app.campaigns WHERE id=%s', (campaign,))
            c.execute('DELETE FROM app.product_images WHERE product_id=%s', (product,))
            c.execute('DELETE FROM app.products WHERE id=%s', (product,))
