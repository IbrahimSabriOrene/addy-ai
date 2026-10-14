import uuid

import psycopg
import pytest

from admaker.cloud_objects import publish_private_object, delete_requested_cloud_objects
from admaker.db import migrate
from admaker.media_drain import AccountDeletionRequested
from test_worker_leases import URL


def test_uncertain_upload_replays_without_reupload_and_deletion_tracks_pending():
    migrate(URL)
    owner = uuid.uuid4()
    class Store:
        origin, bucket = 'https://fixture.test', 'private'
        objects = {}
        uploads = 0
        def download(self, key, max_bytes=None):
            return self.objects.get(key)
        def upload(self, key, content, content_type):
            self.uploads += 1
            self.objects[key] = content
            raise OSError('Lost upload response')
        def remove(self, key):
            self.objects.pop(key, None)
    store = Store()
    with psycopg.connect(URL) as c:
        c.execute("INSERT INTO app.accounts(id,email) VALUES (%s,'cloud-fixture@example.test')", (owner,))
    try:
        with pytest.raises(OSError):
            publish_private_object(URL, owner, 'verified/source.png', b'original', 'image/png', store=store)
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT state FROM app.cloud_objects WHERE account_id=%s", (owner,)).fetchone() == ('pending',)
        key = publish_private_object(URL, owner, 'verified/source.png', b'original', 'image/png', store=store)
        assert store.uploads == 1 and key.startswith(f'objects/{owner}/')
        with pytest.raises(ValueError, match='changed'):
            publish_private_object(URL, owner, 'verified/source.png', b'changed', 'image/png', store=store)
        assert store.objects[key] == b'original'
        with pytest.raises(OSError):
            publish_private_object(URL, owner, 'runs/result.mp4', b'pending', 'video/mp4', store=store)
        with psycopg.connect(URL) as c:
            c.execute("INSERT INTO app.account_deletions(account_id) VALUES (%s)", (owner,))
        with pytest.raises(AccountDeletionRequested):
            publish_private_object(URL, owner, 'verified/new.png', b'new', 'image/png', store=store)
        assert delete_requested_cloud_objects(URL, owner, store=store) == {'state': 'cloud_removed'}
        assert not store.objects
        assert delete_requested_cloud_objects(URL, owner, store=store) == {'state': 'cloud_removed'}
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT count(*) FROM app.cloud_objects WHERE account_id=%s", (owner,)).fetchone() == (0,)
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.cloud_objects WHERE account_id=%s", (owner,))
            c.execute("DELETE FROM app.account_deletions WHERE account_id=%s", (owner,))
            c.execute("DELETE FROM app.accounts WHERE id=%s", (owner,))


def test_missing_uncertain_upload_is_neither_resubmitted_nor_forgotten():
    migrate(URL)
    owner = uuid.uuid4()
    class Store:
        origin, bucket = 'https://fixture.test', 'private'
        uploads = 0
        def download(self, key, max_bytes=None):
            return None
        def upload(self, key, content, content_type):
            self.uploads += 1
            raise OSError('May still be processing')
        def remove(self, key):
            raise AssertionError('Unconfirmed upload must retain ownership')
    store = Store()
    with psycopg.connect(URL) as c:
        c.execute("INSERT INTO app.accounts(id,email) VALUES (%s,'pending@example.test')", (owner,))
    try:
        for _ in range(2):
            with pytest.raises(OSError):
                publish_private_object(URL, owner, 'file.png', b'fixture', 'image/png', store=store)
        assert store.uploads == 1
        with psycopg.connect(URL) as c:
            c.execute("INSERT INTO app.account_deletions(account_id) VALUES (%s)", (owner,))
        with pytest.raises(OSError):
            delete_requested_cloud_objects(URL, owner, store=store)
        with psycopg.connect(URL) as c:
            assert c.execute("SELECT state FROM app.cloud_objects WHERE account_id=%s", (owner,)).fetchone() == ('pending',)
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.cloud_objects WHERE account_id=%s", (owner,))
            c.execute("DELETE FROM app.account_deletions WHERE account_id=%s", (owner,))
            c.execute("DELETE FROM app.accounts WHERE id=%s", (owner,))
