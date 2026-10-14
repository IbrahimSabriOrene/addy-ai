import hashlib
import uuid
from types import SimpleNamespace

import psycopg
from google.genai import types

from admaker.cloud_objects import publish_private_object
from admaker.veo import VeoRequest
from admaker import worker
from test_provider_graph import provider_job, allow_review
from test_worker_leases import URL, queued_job


def test_first_provider_call_uses_restored_owned_image_and_persists_only_digest(provider_job, monkeypatch, tmp_path):
    account, job, reservation, queue = provider_job
    image = (tmp_path / 'test.png').read_bytes()
    class Store:
        origin, bucket = 'https://provider-input.test', 'private'
        objects = {}
        def upload(self, key, content, content_type):
            self.objects[key] = content
        def download(self, key, max_bytes=None):
            return self.objects.get(key)
    store = Store()
    monkeypatch.setattr('admaker.cloud_objects.configured_cloud_storage', lambda: store)
    publish_private_object(URL, account, 'test.png', image, 'image/png', store=store)
    (tmp_path / 'test.png').unlink()
    submissions = []
    operation = f'operations/{uuid.uuid4()}'
    def submit(request, *, account_id):
        assert account_id == str(account)
        assert request.image_bytes == image and request.image_path is None
        submissions.append(request)
        return operation
    service = SimpleNamespace(submit=submit, poll=lambda _: types.GenerateVideosOperation(name=operation, done=False))
    options = dict(video_service=service, video_request=VeoRequest('Approved product fixture'), estimated_cost_microusd=1, video_review=allow_review)
    try:
        assert worker.process_one(URL, 'cloud-input', queue, **options)
        with psycopg.connect(URL) as c:
            saved = c.execute('SELECT a.provider_request FROM app.job_attempts a JOIN app.job_runs r ON r.id=a.run_id WHERE r.job_id=%s', (job,)).fetchone()[0]
            assert saved['imageSha256'] == hashlib.sha256(image).hexdigest()
            assert saved['imageMimeType'] == 'image/png' and saved['imageSizeBytes'] == len(image)
            assert 'image_bytes' not in saved and 'image_path' not in saved
            assert all('token=' not in str(value) for value in saved.values())
            c.execute("UPDATE app.job_runs SET next_work_at=clock_timestamp()-interval '1 second' WHERE job_id=%s", (job,))
        assert worker.recover_expired_runs(URL, queue, str(job)) == 1
        assert worker.process_one(URL, 'cloud-input-retry', queue, **options)
        assert len(submissions) == 1
        with psycopg.connect(URL) as c:
            assert c.execute('SELECT state FROM app.credit_reservations WHERE id=%s', (reservation,)).fetchone() == ('held',)
            assert c.execute('SELECT count(*) FROM app.credit_ledger WHERE account_id=%s', (account,)).fetchone() == (0,)
    finally:
        with psycopg.connect(URL) as c:
            c.execute('DELETE FROM app.cloud_objects WHERE account_id=%s', (account,))
