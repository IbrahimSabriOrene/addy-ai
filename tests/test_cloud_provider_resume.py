import uuid
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from google.genai import types

from admaker import provider_graph, worker
from admaker.veo import VeoRequest
from test_provider_graph import provider_job, allow_review, Crash
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize('boundary', ['raw', 'composed'])
def test_provider_resumes_after_local_media_loss_without_new_paid_call(provider_job, monkeypatch, tmp_path, boundary):
    account, job, reservation, queue = provider_job
    calls = {'submit': 0, 'download': 0, 'compose': 0, 'upload': 0}
    class Store:
        origin, bucket = 'https://provider-cache.test', 'private'
        objects = {}
        def upload(self, key, content, content_type):
            calls['upload'] += 1
            self.objects[key] = content
        def download(self, key, max_bytes=None):
            return self.objects.get(key)
    store = Store()
    monkeypatch.setenv('PUBLISH_PRIVATE_OUTPUTS', 'true')
    monkeypatch.setattr('admaker.cloud_objects.configured_cloud_storage', lambda: store)
    operation = f'operations/{uuid.uuid4()}'
    def submit(*args, **kwargs):
        calls['submit'] += 1
        return operation
    def download(operation, path):
        calls['download'] += 1
        Path(path).write_bytes(b'raw-fixture')
    def compose(source, root, output_id, platforms):
        assert source.read_bytes() == b'raw-fixture'
        calls['compose'] += 1
        if boundary == 'raw' and calls['compose'] == 1:
            raise Crash()
        key = f'runs/{output_id}/final.mp4'
        path = root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'composed-fixture')
        return {'tiktok': {'key': key, 'mimeType': 'video/mp4'}}
    monkeypatch.setattr(provider_graph, 'compose_video', compose)
    service = SimpleNamespace(submit=submit, download=download, poll=lambda _: types.GenerateVideosOperation(name=operation, done=True,
        response=types.GenerateVideosResponse(generated_videos=[types.GeneratedVideo(video=types.Video(uri='fake://video'))])))
    options = dict(video_service=service, video_request=VeoRequest('Fixture'), estimated_cost_microusd=400000, video_review=allow_review)
    original = provider_graph.run_provider_graph
    def crash_after_graph(*args):
        original(*args)
        raise Crash()
    if boundary == 'composed':
        monkeypatch.setattr(provider_graph, 'run_provider_graph', crash_after_graph)
    try:
        with pytest.raises(Crash):
            worker.process_one(URL, 'cloud-first', queue, **options)
        for path in tmp_path.rglob('*.mp4'):
            path.unlink()
        monkeypatch.setattr(provider_graph, 'run_provider_graph', original)
        with psycopg.connect(URL) as c:
            c.execute("UPDATE app.job_runs SET lease_until=clock_timestamp()-interval '1 second',next_work_at=NULL WHERE job_id=%s", (job,))
        assert worker.recover_expired_runs(URL, queue, str(job)) == 1
        assert worker.process_one(URL, 'cloud-restart', queue, **options)
        assert calls == {'submit': 1, 'download': 1, 'compose': 2 if boundary == 'raw' else 1, 'upload': 2}
        with psycopg.connect(URL) as c:
            assert c.execute('SELECT delta FROM app.credit_ledger WHERE account_id=%s', (account,)).fetchall() == [(-2,)]
            assert c.execute('SELECT state FROM app.jobs WHERE id=%s', (job,)).fetchone() == ('delivered',)
    finally:
        with psycopg.connect(URL) as c:
            c.execute('DELETE FROM app.cloud_objects WHERE account_id=%s', (account,))
