import uuid

import psycopg
import pytest
from psycopg.types.json import Jsonb

from admaker.deletion_media import account_media_inventory
from test_worker_leases import URL, queued_job


def test_inventory_preserves_shared_files_and_includes_unfinished_outputs(queued_job, tmp_path):
    owner, job, reservation, queue = queued_job
    other, other_asset, run = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for key in ("test.png", "shared.png", "history.mp4", "raw.mp4"):
        (tmp_path / key).write_bytes(b"keep me")
    with psycopg.connect(URL) as c:
        c.execute("INSERT INTO app.accounts(id,email) VALUES (%s,'other@example.com')", (other,))
        c.execute("INSERT INTO app.assets(asset_key,owner_id,storage_key,mime_type) VALUES (%s,%s,'./shared.png','image/png')", (other_asset, other))
        c.execute("UPDATE app.jobs SET result=%s WHERE id=%s", (Jsonb({"exports": {"image": {"key": "shared.png"}}, "runs": {"1": {"exports": {"video": {"key": "history.mp4"}}}}}), job))
        c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state) VALUES (%s,%s,1,%s,'running')", (run, job, str(run)))
        c.execute("INSERT INTO app.job_stages(run_id,stage_key,request_hash,result,fence) VALUES (%s,'provider_download','fixture',%s,1)", (run, Jsonb({"key": "raw.mp4", "nested": [{"key": "../outside.png"}, {"key": "missing.png"}]})))
    try:
        with psycopg.connect(URL) as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            inventory = account_media_inventory(c, owner, tmp_path)
            assert {item["key"]: item["status"] for item in inventory["files"]} == {
                "test.png": "owned_file", "shared.png": "shared_reference", "history.mp4": "owned_file",
                "raw.mp4": "owned_file", "../outside.png": "outside_storage_root", "missing.png": "missing"}
            assert inventory["pendingJobs"] == [{"id": str(job), "state": "submitted"}]
            assert account_media_inventory(c, other, tmp_path)["files"] == [{"key": "./shared.png", "status": "shared_reference"}]
            with pytest.raises(LookupError):
                account_media_inventory(c, uuid.uuid4(), tmp_path)
        assert all(path.read_bytes() == b"keep me" for path in tmp_path.iterdir())
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.assets WHERE asset_key=%s", (other_asset,))
            c.execute("DELETE FROM app.accounts WHERE id=%s", (other,))
