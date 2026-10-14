from pathlib import Path
import subprocess
import uuid

import psycopg

from admaker.db import migrate
from admaker.worker import _render_fake, process_one, recover_expired_runs


def test_fake_render_uses_argument_list(monkeypatch, tmp_path) -> None:
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == "ffmpeg" and command[-1] != "-":
            Path(command[-1]).write_bytes(b"fixture")
        height = 1080 if "feed" in command[-1] else 1920
        return subprocess.CompletedProcess(command, 0, stdout=f'{{"streams":[{{"codec_type":"video","codec_name":"h264","width":1080,"height":{height},"pix_fmt":"yuv420p","duration":"8.0"}},{{"codec_type":"audio","codec_name":"aac","duration":"8.0"}}],"format":{{"duration":"8.0","format_name":"mov,mp4"}}}}')

    monkeypatch.setattr("admaker.worker.subprocess.run", run)
    exports = _render_fake(Path("source.jpg"), tmp_path, "job-1", ["tiktok", "feed"])
    assert calls[0][0][0] == "ffmpeg"
    assert calls[0][1]["check"] is True
    assert calls[1][0][0] == "ffprobe"
    assert set(exports) == {"tiktok", "feed"}


def test_worker_settles_only_its_attempt_reservation(monkeypatch) -> None:
    database_url = "postgresql://postgres:postgres@localhost:54322/postgres"
    queue = f"worker_test_{uuid.uuid4().hex}"
    migrate(database_url)
    owner_id, asset_key, job_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    reservation_ids = sorted((uuid.uuid4(), uuid.uuid4()), key=str)
    with psycopg.connect(database_url) as connection:
        connection.execute("SELECT pgmq.create(%s)", (queue,))
        connection.execute("INSERT INTO app.accounts (id, email) VALUES (%s, %s)", (owner_id, f"worker-{owner_id}@example.com"))
        connection.execute("INSERT INTO app.assets (asset_key, owner_id, storage_key, mime_type, verification_state) VALUES (%s,%s,%s,'image/jpeg','verified')", (asset_key, owner_id, f"test/{asset_key}.jpg"))
        connection.execute("INSERT INTO app.jobs (id, owner_id, source_asset_id, state, settings) VALUES (%s,%s,%s,'submitted',%s)", (job_id, owner_id, asset_key, psycopg.types.json.Jsonb({"platforms": ["tiktok"]})))
        for reservation_id in reservation_ids:
            connection.execute("INSERT INTO app.credit_reservations (id, account_id, job_id, amount, state) VALUES (%s,%s,%s,3,'held')", (reservation_id, owner_id, job_id))
        connection.execute("SELECT pgmq.send(%s, %s)", (queue, psycopg.types.json.Jsonb({"jobId": str(job_id)})))
    monkeypatch.setattr("admaker.worker._render_fake", lambda *_: {"tiktok": {"key": "runs/test.mp4", "caption": ""}})
    assert process_one(database_url, "test-worker", queue)
    with psycopg.connect(database_url) as connection:
        states = connection.execute("SELECT id, state FROM app.credit_reservations WHERE job_id=%s ORDER BY id", (job_id,)).fetchall()
        attempt = connection.execute("SELECT a.reservation_id, a.state FROM app.job_attempts a JOIN app.job_runs r ON r.id=a.run_id WHERE r.job_id=%s", (job_id,)).fetchone()
    assert states == [(reservation_ids[0], "consumed"), (reservation_ids[1], "held")]
    assert attempt == (reservation_ids[0], "delivered")
    with psycopg.connect(database_url) as connection:
        assert connection.execute("SELECT sum(delta) FROM app.credit_ledger WHERE account_id=%s", (owner_id,)).fetchone()[0] == -3


def test_expired_run_is_reclaimed_with_a_new_fence(monkeypatch) -> None:
    database_url = "postgresql://postgres:postgres@localhost:54322/postgres"
    queue = f"recovery_test_{uuid.uuid4().hex}"
    migrate(database_url)
    owner_id, asset_key, job_id, run_id, reservation_id, attempt_id = (uuid.uuid4() for _ in range(6))
    with psycopg.connect(database_url) as connection:
        connection.execute("SELECT pgmq.create(%s)", (queue,))
        connection.execute("INSERT INTO app.accounts (id, email) VALUES (%s,%s)", (owner_id, f"recovery-{owner_id}@example.com"))
        connection.execute("INSERT INTO app.assets (asset_key, owner_id, storage_key, mime_type, verification_state) VALUES (%s,%s,%s,'image/jpeg','verified')", (asset_key, owner_id, f"test/{asset_key}.jpg"))
        connection.execute("INSERT INTO app.jobs (id, owner_id, source_asset_id, state, settings) VALUES (%s,%s,%s,'running',%s)", (job_id, owner_id, asset_key, psycopg.types.json.Jsonb({"platforms": ["tiktok"]})))
        connection.execute("INSERT INTO app.credit_reservations (id, account_id, job_id, amount, state) VALUES (%s,%s,%s,1,'held')", (reservation_id, owner_id, job_id))
        connection.execute("INSERT INTO app.job_runs (id, job_id, sequence, thread_id, state, lease_owner, lease_until, fence) VALUES (%s,%s,1,%s,'running','dead-worker',now() - interval '1 second',1)", (run_id, job_id, f"{job_id}:1"))
        connection.execute("INSERT INTO app.job_attempts (id, run_id, reservation_id, sequence, state, request_hash) VALUES (%s,%s,%s,1,'running','test')", (attempt_id, run_id, reservation_id))
        connection.execute("UPDATE app.jobs SET active_run_id=%s WHERE id=%s", (run_id, job_id))
    assert recover_expired_runs(database_url, queue, str(job_id)) == 1
    monkeypatch.setattr("admaker.worker._render_fake", lambda *_: {"tiktok": {"key": "runs/test.mp4", "caption": ""}})
    assert process_one(database_url, "new-worker", queue)
    with psycopg.connect(database_url) as connection:
        run = connection.execute("SELECT state, fence FROM app.job_runs WHERE id=%s", (run_id,)).fetchone()
        attempt = connection.execute("SELECT state FROM app.job_attempts WHERE id=%s", (attempt_id,)).fetchone()
    assert run == ("delivered", 2)
    assert attempt == ("delivered",)
