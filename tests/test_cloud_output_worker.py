import psycopg

from admaker.worker import process_one, recover_expired_runs
from test_worker_leases import URL, queued_job


def test_output_publication_failure_keeps_credit_and_replays_render(queued_job, monkeypatch, tmp_path):
    owner, job, reservation, queue = queued_job
    class Store:
        origin, bucket = 'https://output-cloud.test', 'private'
        objects = {}
        uploads = 0
        def upload(self, key, content, content_type):
            self.uploads += 1
            self.objects[key] = content
            raise OSError('Upload acknowledgement lost')
        def download(self, key, max_bytes=None):
            return self.objects.get(key)
    store = Store()
    renders = []
    def render(source, root, output_id, platforms):
        renders.append(output_id)
        key = f'runs/{output_id}/final.mp4'
        path = root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'output-fixture')
        return {'tiktok': {'key': key, 'mimeType': 'video/mp4'}}
    monkeypatch.setenv('LOCAL_ASSET_ROOT', str(tmp_path))
    monkeypatch.setenv('PUBLISH_PRIVATE_OUTPUTS', 'true')
    monkeypatch.setattr('admaker.cloud_objects.configured_cloud_storage', lambda: store)
    monkeypatch.setattr('admaker.worker._render_fake', render)
    try:
        assert process_one(URL, 'publisher', queue)
        with psycopg.connect(URL) as c:
            assert c.execute('SELECT state FROM app.credit_reservations WHERE id=%s', (reservation,)).fetchone() == ('held',)
            assert c.execute('SELECT count(*) FROM app.credit_ledger WHERE account_id=%s', (owner,)).fetchone() == (0,)
            assert c.execute('SELECT state FROM app.cloud_objects WHERE account_id=%s', (owner,)).fetchone() == ('pending',)
            c.execute("UPDATE app.job_runs SET next_work_at=clock_timestamp()-interval '1 second' WHERE job_id=%s", (job,))
        assert recover_expired_runs(URL, queue, str(job)) == 1
        assert process_one(URL, 'publisher-recovery', queue)
        assert len(renders) == 1 and store.uploads == 1
        with psycopg.connect(URL) as c:
            assert c.execute('SELECT state FROM app.jobs WHERE id=%s', (job,)).fetchone() == ('delivered',)
            assert c.execute('SELECT state FROM app.cloud_objects WHERE account_id=%s', (owner,)).fetchone() == ('ready',)
            assert c.execute('SELECT delta FROM app.credit_ledger WHERE account_id=%s', (owner,)).fetchall() == [(-2,)]
    finally:
        with psycopg.connect(URL) as c:
            c.execute('DELETE FROM app.cloud_objects WHERE account_id=%s', (owner,))


def test_ready_output_can_be_republished_after_local_cache_loss(queued_job, tmp_path):
    from admaker.cloud_objects import publish_job_outputs
    owner, job, reservation, queue = queued_job
    class Store:
        origin, bucket = 'https://output-cache.test', 'private'
        objects = {}
        uploads = 0
        def upload(self, key, content, content_type):
            self.uploads += 1
            self.objects[key] = content
        def download(self, key, max_bytes=None):
            return self.objects.get(key)
    store = Store()
    path = tmp_path / 'final.mp4'
    path.write_bytes(b'verified-output')
    exports = {'tiktok': {'key': 'final.mp4', 'mimeType': 'video/mp4'}}
    try:
        publish_job_outputs(URL, job, tmp_path, exports, store=store)
        path.unlink()
        publish_job_outputs(URL, job, tmp_path, exports, store=store)
        assert path.read_bytes() == b'verified-output' and store.uploads == 1
    finally:
        with psycopg.connect(URL) as c:
            c.execute('DELETE FROM app.cloud_objects WHERE account_id=%s', (owner,))
