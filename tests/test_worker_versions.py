import uuid

import psycopg

from admaker.db import migrate
from admaker.worker import process_one


def test_regeneration_keeps_previous_export_paths(monkeypatch):
    url = "postgresql://postgres:postgres@localhost:54322/postgres"
    migrate(url)
    owner, asset, job = (uuid.uuid4() for _ in range(3))
    queue = f"versions_{uuid.uuid4().hex}"
    with psycopg.connect(url) as c:
        c.execute("SELECT pgmq.create(%s)", (queue,))
        c.execute("INSERT INTO app.accounts(id,email) VALUES (%s,'versions@example.com')", (owner,))
        c.execute("INSERT INTO app.assets(asset_key,owner_id,storage_key,mime_type,verification_state) VALUES (%s,%s,%s,'image/png','verified')", (asset, owner, str(asset)))
        c.execute("INSERT INTO app.jobs(id,owner_id,source_asset_id,state) VALUES (%s,%s,%s,'submitted')", (job, owner, asset))
    paths = []

    def render(source, root, output_id, platforms):
        paths.append(output_id)
        return {"tiktok": {"key": f"runs/{output_id}/final.mp4", "caption": ""}}

    monkeypatch.setattr("admaker.worker._render_fake", render)
    try:
        for _ in range(2):
            with psycopg.connect(url) as c:
                c.execute("UPDATE app.jobs SET state='submitted' WHERE id=%s", (job,))
                c.execute("INSERT INTO app.credit_reservations(id,account_id,job_id,amount,state) VALUES (%s,%s,%s,1,'held')", (uuid.uuid4(), owner, job))
                c.execute("SELECT pgmq.send(%s,%s)", (queue, psycopg.types.json.Jsonb({"jobId": str(job)})))
            assert process_one(url, "test", queue)
        assert paths[0] != paths[1]
        assert all(path.startswith(f"{job}/") and path.endswith("/1") for path in paths)
        with psycopg.connect(url) as c:
            result = c.execute("SELECT result FROM app.jobs WHERE id=%s", (job,)).fetchone()[0]
            assert result["runs"]["1"]["exports"]["tiktok"]["key"] != result["runs"]["2"]["exports"]["tiktok"]["key"]
    finally:
        with psycopg.connect(url) as c:
            c.execute("SELECT pgmq.drop_queue(%s)", (queue,))
            c.execute("UPDATE app.jobs SET active_run_id=NULL WHERE id=%s", (job,))
            c.execute("DELETE FROM app.job_attempts WHERE run_id IN (SELECT id FROM app.job_runs WHERE job_id=%s)", (job,))
            c.execute("DELETE FROM app.job_runs WHERE job_id=%s", (job,))
            c.execute("DELETE FROM app.credit_reservations WHERE job_id=%s", (job,))
            c.execute("DELETE FROM app.jobs WHERE id=%s", (job,))
            c.execute("DELETE FROM app.credit_ledger WHERE account_id=%s", (owner,))
            c.execute("DELETE FROM app.assets WHERE asset_key=%s", (asset,))
            c.execute("DELETE FROM app.accounts WHERE id=%s", (owner,))
