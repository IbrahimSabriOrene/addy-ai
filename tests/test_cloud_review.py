import uuid

import psycopg
import pytest

from admaker.cloud_objects import publish_private_object, delete_requested_cloud_objects
from admaker.cloud_review import reconcile_cloud_object
from test_worker_leases import URL, queued_job


def test_verified_absence_allows_one_retry_and_old_review_cannot_reset_it(queued_job):
    account, job, reservation, queue = queued_job
    class Store:
        origin, bucket = 'https://review.test', 'private'
        objects = {}
        fail = True
        uploads = 0
        def download(self, key, max_bytes=None):
            return self.objects.get(key)
        def upload(self, key, content, content_type):
            self.uploads += 1
            if self.fail:
                raise OSError('Unconfirmed transfer')
            self.objects[key] = content
        def remove(self, key):
            self.objects.pop(key, None)
    store = Store()
    resolution = uuid.uuid4()
    args = (URL, account, 'file.png', resolution, 'operator', 'verified_absent', 'terminal-upload-ticket')
    try:
        for _ in range(2):
            with pytest.raises(OSError):
                publish_private_object(URL, account, 'file.png', b'content', 'image/png', store=store)
        assert store.uploads == 1
        assert reconcile_cloud_object(*args, store=store)
        with pytest.raises(ValueError):
            reconcile_cloud_object(*args[:-1], 'different-ticket', store=store)
        store.fail = False
        publish_private_object(URL, account, 'file.png', b'content', 'image/png', store=store)
        assert store.uploads == 2
        assert reconcile_cloud_object(*args, store=store)  # Audit replay, never changes the new ready state.
        with psycopg.connect(URL) as c:
            assert c.execute('SELECT state FROM app.cloud_objects WHERE account_id=%s', (account,)).fetchone() == ('ready',)
            assert c.execute('SELECT count(*) FROM app.cloud_object_reviews WHERE account_id=%s', (account,)).fetchone() == (1,)
            assert c.execute('SELECT count(*) FROM app.credit_ledger WHERE account_id=%s', (account,)).fetchone() == (0,)
        store.fail = True
        with pytest.raises(OSError):
            publish_private_object(URL, account, 'pending.png', b'pending', 'image/png', store=store)
        with psycopg.connect(URL) as c:
            c.execute('INSERT INTO app.account_deletions(account_id) VALUES (%s)', (account,))
        assert reconcile_cloud_object(URL, account, 'pending.png', uuid.uuid4(), 'operator', 'verified_absent', 'terminal-ticket-2', store=store)
        assert delete_requested_cloud_objects(URL, account, store=store) == {'state': 'cloud_removed'}
        assert not store.objects
    finally:
        with psycopg.connect(URL) as c:
            c.execute('DELETE FROM app.cloud_object_reviews WHERE account_id=%s', (account,))
            c.execute('DELETE FROM app.cloud_objects WHERE account_id=%s', (account,))
            c.execute('DELETE FROM app.account_deletions WHERE account_id=%s', (account,))


def test_present_reconciliation_checks_remote_checksum(queued_job):
    account, job, reservation, queue = queued_job
    class Store:
        origin, bucket = 'https://present.test', 'private'
        objects = {}
        def download(self, key, max_bytes=None):
            return self.objects.get(key)
        def upload(self, key, content, content_type):
            self.objects[key] = b'corrupt'
            raise OSError('Unknown result')
    store = Store()
    args = (URL, account, 'file.png', uuid.uuid4(), 'operator', 'verified_present', 'terminal-evidence')
    try:
        with pytest.raises(OSError):
            publish_private_object(URL, account, 'file.png', b'expected', 'image/png', store=store)
        with pytest.raises(ValueError, match='does not match'):
            reconcile_cloud_object(*args, store=store)
        key = next(iter(store.objects))
        store.objects[key] = b'expected'
        assert reconcile_cloud_object(*args, store=store)
        with psycopg.connect(URL) as c:
            assert c.execute('SELECT state FROM app.cloud_objects WHERE account_id=%s', (account,)).fetchone() == ('ready',)
    finally:
        with psycopg.connect(URL) as c:
            c.execute('DELETE FROM app.cloud_object_reviews WHERE account_id=%s', (account,))
            c.execute('DELETE FROM app.cloud_objects WHERE account_id=%s', (account,))
