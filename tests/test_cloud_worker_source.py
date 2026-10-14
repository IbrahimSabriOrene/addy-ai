import psycopg
import pytest

from admaker.cloud_objects import publish_private_object, stage_job_source
from admaker.worker import process_one
from test_worker_leases import URL, queued_job


def test_worker_restores_only_verified_source_and_rejects_corruption(queued_job, monkeypatch, tmp_path):
    owner, job, reservation, queue = queued_job
    class Store:
        origin, bucket = 'https://worker-cloud.test', 'private'
        objects = {}
        def upload(self, key, content, content_type):
            self.objects[key] = content
        def download(self, key, max_bytes=None):
            return self.objects.get(key)
    store = Store()
    monkeypatch.setenv('LOCAL_ASSET_ROOT', str(tmp_path))
    monkeypatch.setattr('admaker.cloud_objects.configured_cloud_storage', lambda: store)
    rendered = []
    def render(source, root, output_id, platforms):
        rendered.append(source.read_bytes())
        return {'tiktok': {'key': f'runs/{output_id}/final.mp4', 'caption': ''}}
    monkeypatch.setattr('admaker.worker._render_fake', render)
    try:
        remote_key = publish_private_object(URL, owner, 'test.png', b'verified-source', 'image/png', store=store)
        assert not (tmp_path / 'test.png').exists()
        assert process_one(URL, 'cloud-source-worker', queue)
        assert rendered == [b'verified-source']
        assert (tmp_path / 'test.png').read_bytes() == b'verified-source'
        (tmp_path / 'test.png').unlink()
        store.objects[remote_key] = b'wrong-source'
        with pytest.raises(OSError, match='verification'):
            stage_job_source(URL, job, tmp_path, store=store)
        assert not (tmp_path / 'test.png').exists()
    finally:
        with psycopg.connect(URL) as c:
            c.execute('DELETE FROM app.cloud_objects WHERE account_id=%s', (owner,))


def test_source_outage_defers_without_rendering_or_releasing_credit(queued_job, monkeypatch):
    owner, job, reservation, queue = queued_job
    def unavailable(*args):
        raise OSError('Private storage unavailable')
    def render(*args):
        raise AssertionError('No renderer may run before verified source staging')
    monkeypatch.setattr('admaker.cloud_objects.stage_job_source', unavailable)
    monkeypatch.setattr('admaker.worker._render_fake', render)
    assert process_one(URL, 'source-outage-worker', queue)
    with psycopg.connect(URL) as c:
        assert c.execute('SELECT state FROM app.credit_reservations WHERE id=%s', (reservation,)).fetchone() == ('held',)
        assert c.execute('SELECT state FROM app.jobs WHERE id=%s', (job,)).fetchone() == ('running',)
        assert c.execute('SELECT next_work_at>clock_timestamp() FROM app.job_runs WHERE job_id=%s', (job,)).fetchone() == (True,)
        assert c.execute('SELECT count(*) FROM app.credit_ledger WHERE account_id=%s', (owner,)).fetchone() == (0,)
