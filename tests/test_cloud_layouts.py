import io
import uuid

import psycopg
from PIL import Image
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.cloud_objects import publish_private_object
from admaker.campaign_layouts import render_campaign_layouts
from test_worker_leases import URL, queued_job


def test_cloud_layout_retry_reuses_render_and_offer_edit_never_creates_video(queued_job, monkeypatch, tmp_path):
    account, job, reservation, queue = queued_job
    class Store:
        origin, bucket = 'https://layout.test', 'private'
        objects = {}
        lose = False
        def upload(self, key, content, content_type):
            self.objects[key] = content
            if self.lose:
                self.lose = False
                raise OSError('Lost response')
        def download(self, key, max_bytes=None):
            return self.objects.get(key)
        def signed_download(self, key, expires_in):
            return f'https://layout.test/storage/v1/object/sign/private/{key}?token=fixture'
    store = Store()
    monkeypatch.setenv('DATABASE_URL', URL)
    monkeypatch.setenv('LOCAL_ASSET_ROOT', str(tmp_path))
    monkeypatch.setenv('PUBLISH_PRIVATE_OUTPUTS', 'true')
    monkeypatch.setattr('admaker.cloud_objects.configured_cloud_storage', lambda: store)
    renders = []
    def render(*args):
        renders.append(args[2]['offer'])
        return render_campaign_layouts(*args)
    monkeypatch.setattr('admaker.campaign_routes.render_campaign_layouts', render)
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), 'layout-cloud@example.test')
    try:
        image = io.BytesIO()
        Image.new('RGB', (32, 32), 'red').save(image, 'PNG')
        publish_private_object(URL, account, 'test.png', image.getvalue(), 'image/png', store=store)
        with psycopg.connect(URL) as c:
            asset = str(c.execute('SELECT source_asset_id FROM app.jobs WHERE id=%s', (job,)).fetchone()[0])
        with TestClient(app) as client:
            product = client.post('/v1/products', json={'name': 'Fixture', 'assetKey': asset}).json()['id']
            assert client.post(f'/v1/products/{product}/approved-image', json={'assetKey': asset, 'expectedVersion': 0}).status_code == 200
            campaign = client.post('/v1/campaigns', json={'productId': product, 'imageVersion': 1, 'offer': '20% off'}, headers={'Idempotency-Key': 'cloud-layout'}).json()['id']
            path = f'/v1/campaigns/{campaign}/layouts'
            store.lose = True
            assert client.post(path, json={'expectedVersion': 1}).status_code == 503
            first = client.post(path, json={'expectedVersion': 1})
            assert first.status_code == 200 and renders == ['20% off']
            assert client.get(first.json()['outputs']['story']['url'], follow_redirects=False).status_code == 302
            assert client.patch(f'/v1/campaigns/{campaign}', json={'expectedVersion': 1, 'offer': '15% off', 'caption': '', 'cta': '', 'color': '#FFFFFF'}).status_code == 200
            second = client.post(path, json={'expectedVersion': 2})
            assert second.status_code == 200 and renders == ['20% off', '15% off']
            assert second.json()['outputs']['story']['offer'] == '15% off'
            assert first.json()['outputs']['story']['url'] != second.json()['outputs']['story']['url']
            with psycopg.connect(URL) as c:
                assert c.execute('SELECT count(*) FROM app.jobs WHERE owner_id=%s', (account,)).fetchone() == (1,)
                assert c.execute('SELECT count(*) FROM app.credit_ledger WHERE account_id=%s', (account,)).fetchone() == (0,)
                assert c.execute('SELECT count(*) FROM app.cloud_objects WHERE account_id=%s', (account,)).fetchone() == (5,)
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
        with psycopg.connect(URL) as c:
            c.execute('DELETE FROM app.cloud_objects WHERE account_id=%s', (account,))
            c.execute('DELETE FROM app.command_keys WHERE account_id=%s', (account,))
            c.execute('DELETE FROM app.campaigns WHERE owner_id=%s', (account,))
            c.execute('DELETE FROM app.product_images WHERE owner_id=%s', (account,))
            c.execute('DELETE FROM app.products WHERE owner_id=%s', (account,))
