import hashlib
import json

import psycopg
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.cloud_objects import publish_private_object
from test_worker_leases import URL, queued_job


def test_accept_restores_cloud_pack_and_refuses_corrupt_output(queued_job, monkeypatch, tmp_path):
    account, job, reservation, queue = queued_job
    class Store:
        origin, bucket = 'https://accept.test', 'private'
        objects = {}
        def upload(self, key, content, content_type):
            self.objects[key] = content
        def download(self, key, max_bytes=None):
            return self.objects.get(key)
    store = Store()
    monkeypatch.setenv('DATABASE_URL', URL)
    monkeypatch.setenv('LOCAL_ASSET_ROOT', str(tmp_path))
    monkeypatch.setattr('admaker.cloud_objects.configured_cloud_storage', lambda: store)
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), 'accept@example.test')
    try:
        exports = {'copy': {'caption': 'Offer', 'cta': 'Shop'}}
        for kind in ['cleanImage', 'video', 'story', 'feed']:
            key = f'campaign-runs/fixture/{kind}.png'
            remote = publish_private_object(URL, account, key, b'verified', 'image/png', store=store)
            exports[kind] = {'key': key, 'mimeType': 'image/png'}
        with psycopg.connect(URL) as c:
            validation = {'technicalPassed': True, 'policyAllowed': True,
                'exportsHash': hashlib.sha256(json.dumps(exports, sort_keys=True).encode()).hexdigest(), 'reservationId': str(reservation)}
            c.execute("UPDATE app.jobs SET state='awaiting_user_decision',settings=%s,result=%s WHERE id=%s",
                (Jsonb({'generationKind': 'campaign_pack'}), Jsonb({'exports': exports, 'candidateValidation': validation}), job))
        store.objects[remote] = b'corrupt'
        with TestClient(app) as client:
            path = f'/v1/jobs/{job}/decision'
            version = client.get(f'/v1/jobs/{job}').json()['version']
            kwargs = {'json': {'action': 'accept', 'expectedVersion': version}, 'headers': {'Idempotency-Key': 'cloud-accept'}}
            rejected = client.post(path, **kwargs)
            assert rejected.status_code == 409
            assert 'complete campaign pack is unavailable' in rejected.json()['message']
            with psycopg.connect(URL) as c:
                assert c.execute('SELECT state FROM app.credit_reservations WHERE id=%s', (reservation,)).fetchone() == ('held',)
                assert c.execute('SELECT count(*) FROM app.credit_ledger WHERE account_id=%s', (account,)).fetchone() == (0,)
            store.objects[remote] = b'verified'
            assert client.post(path, **kwargs).status_code == 202
            assert client.post(path, **kwargs).status_code == 202
            for kind in ['cleanImage', 'video', 'story', 'feed']:
                assert (tmp_path / exports[kind]['key']).read_bytes() == b'verified'
            with psycopg.connect(URL) as c:
                assert c.execute('SELECT delta FROM app.credit_ledger WHERE account_id=%s', (account,)).fetchall() == [(-2,)]
    finally:
        app.dependency_overrides.pop(authenticated_subject, None)
        with psycopg.connect(URL) as c:
            c.execute('DELETE FROM app.cloud_objects WHERE account_id=%s', (account,))
            c.execute('DELETE FROM app.command_keys WHERE account_id=%s', (account,))
