import uuid

import psycopg
from PIL import Image

from admaker import campaign_pack
from admaker.deletion_media import account_media_inventory
from test_worker_leases import URL, queued_job


def test_unpublished_pack_and_owner_scoped_orphans_are_discoverable(queued_job, tmp_path, monkeypatch):
    account, job, reservation, queue = queued_job
    run = uuid.uuid4()
    with psycopg.connect(URL) as c:
        c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state) VALUES (%s,%s,1,%s,'running')", (run, job, str(run)))
    Image.new("RGB", (8, 8), "blue").save(tmp_path / "test.png")
    (tmp_path / "video.mp4").write_bytes(b"fixture video")
    monkeypatch.setattr(campaign_pack, "validate_video", lambda *args: {"hasAudio": True})
    def overlay(source, destination, brief):
        path = destination / "video.mp4"
        path.write_bytes(b"fixture composed video")
        return {"path": str(path), "mimeType": "video/mp4", "hasAudio": True}
    monkeypatch.setattr(campaign_pack, "render_campaign_video", overlay)
    result = campaign_pack.compose_campaign_pack(tmp_path, "test.png", "video.mp4", {"offer": "20%", "cta": "Shop"}, run)
    assert result["story"]["key"].startswith(f"campaign-runs/{run}/")
    assert result["feed"]["key"].startswith(f"campaign-runs/{run}/")
    # Simulate a crash before persisting the returned manifest.
    keys = [f"incoming/{account}/partial.upload", f"verified/{account}/uncommitted.png", f"runs/{job}/partial.mp4"]
    for key in keys:
        path = tmp_path / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"unpublished")
    unrelated = tmp_path / "campaign-packs" / str(uuid.uuid4()) / "unknown.png"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_bytes(b"unknown owner: preserve")
    with psycopg.connect(URL) as c:
        inventory = account_media_inventory(c, account, tmp_path)
    found = {item["key"]: item["status"] for item in inventory["files"]}
    for key in [*keys, result["story"]["key"], result["feed"]["key"], result["video"]["key"]]:
        assert found[key] == "owned_file"
    assert unrelated.relative_to(tmp_path).as_posix() not in found
    assert unrelated.read_bytes() == b"unknown owner: preserve"
