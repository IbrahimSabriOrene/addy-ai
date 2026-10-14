import uuid

import psycopg
import pytest

from admaker import campaign_worker
from admaker.provider_graph import ReviewedCandidate
from test_provider_graph import Crash
from test_worker_leases import URL, queued_job


def test_pack_stage_survives_review_crash_and_local_file_loss(queued_job, monkeypatch, tmp_path):
    account, job, reservation, queue = queued_job
    run = uuid.uuid4()
    with psycopg.connect(URL) as c:
        c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state,lease_owner,lease_until,fence) VALUES (%s,%s,1,%s,'running','fixture',clock_timestamp()+interval '5 minutes',1)", (run, job, str(run)))
        c.execute("UPDATE app.jobs SET active_run_id=%s,state='running' WHERE id=%s", (run, job))
    class Store:
        origin, bucket = 'https://pack-stage.test', 'private'
        objects = {}
        uploads = 0
        def upload(self, key, content, content_type):
            self.uploads += 1
            self.objects[key] = content
        def download(self, key, max_bytes=None):
            return self.objects.get(key)
    store = Store()
    monkeypatch.setenv('LOCAL_ASSET_ROOT', str(tmp_path))
    monkeypatch.setenv('PUBLISH_PRIVATE_OUTPUTS', 'true')
    monkeypatch.setattr('admaker.cloud_objects.configured_cloud_storage', lambda: store)
    composed = []
    def compose(*args):
        composed.append(1)
        manifest = {'copy': {'caption': 'Offer', 'cta': 'Shop'}}
        for kind in ['cleanImage', 'video', 'story', 'feed']:
            path = tmp_path / f'{kind}.png'
            path.write_bytes(kind.encode())
            manifest[kind] = {'key': path.name, 'mimeType': 'image/png'}
        return manifest
    monkeypatch.setattr(campaign_worker, 'compose_campaign_pack', compose)
    def crash(*args):
        raise Crash()
    candidate = ReviewedCandidate({'tiktok': {'key': 'video.mp4'}}, {'policyAllowed': True, 'qualityPassed': True})
    args = (URL, run, 'fixture', 1, 'test.png', {'campaignBrief': {}}, candidate)
    try:
        with pytest.raises(Crash):
            campaign_worker.finish_campaign_pack(*args, crash)
        for kind in ['cleanImage', 'video', 'story', 'feed']:
            (tmp_path / f'{kind}.png').unlink()
        result = campaign_worker.finish_campaign_pack(*args, lambda *args: {'policyAllowed': True, 'qualityPassed': True})
        assert composed == [1] and store.uploads == 4
        assert result.validation['qualityPassed']
        for kind in ['cleanImage', 'video', 'story', 'feed']:
            assert (tmp_path / result.exports[kind]['key']).read_bytes() == kind.encode()
    finally:
        with psycopg.connect(URL) as c:
            c.execute('DELETE FROM app.cloud_objects WHERE account_id=%s', (account,))
