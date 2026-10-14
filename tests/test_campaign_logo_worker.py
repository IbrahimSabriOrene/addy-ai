import hashlib
import uuid

import psycopg
import pytest
from PIL import Image

from admaker import campaign_pack
from admaker.campaign_worker import finish_campaign_pack
from admaker.provider_graph import ReviewedCandidate
from test_worker_leases import URL, queued_job


def test_worker_resolves_owned_logo_and_reuses_fenced_pack(queued_job, monkeypatch, tmp_path):
    account, job, _, _ = queued_job
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("LOCAL_ASSET_ROOT", str(tmp_path))
    monkeypatch.setenv("PUBLISH_PRIVATE_OUTPUTS", "false")
    logo = tmp_path / "test.png"
    Image.new("RGB", (360, 110), "blue").save(logo)
    Image.new("RGB", (100, 200), "red").save(tmp_path / "product.png")
    (tmp_path / "source.mp4").write_bytes(b"fixture video")
    run = uuid.uuid4()
    with psycopg.connect(URL) as c:
        asset = c.execute("SELECT source_asset_id FROM app.jobs WHERE id=%s", (job,)).fetchone()[0]
        c.execute("UPDATE app.assets SET checksum=%s WHERE asset_key=%s", (hashlib.sha256(logo.read_bytes()).hexdigest(), asset))
        c.execute("INSERT INTO app.job_runs(id,job_id,sequence,thread_id,state,lease_owner,lease_until,fence) VALUES (%s,%s,1,%s,'running','logo-test',clock_timestamp()+interval '1 minute',1)", (run, job, str(run)))
        c.execute("UPDATE app.jobs SET active_run_id=%s,state='running' WHERE id=%s", (run, job))
    renders, reviews = [], []
    monkeypatch.setattr(campaign_pack, "validate_video", lambda *args: {})
    def render(source, destination, brief, logo=None):
        assert logo == tmp_path / "test.png"
        renders.append(logo)
        output = destination / "video.mp4"
        output.write_bytes(b"composed")
        return {"path": str(output), "mimeType": "video/mp4"}
    monkeypatch.setattr(campaign_pack, "render_campaign_video", render)
    def review(root, manifest):
        reviews.append(manifest)
        with Image.open(root / manifest["story"]["key"]) as image:
            assert image.getpixel((540, 70)) == (0, 0, 255)
        return {"policyAllowed": True, "qualityPassed": True}
    settings = {"campaignBrief": {"logoAssetKey": str(asset), "offer": "20%", "cta": "Shop"}}
    candidate = ReviewedCandidate({"tiktok": {"key": "source.mp4"}}, {"policyAllowed": True, "qualityPassed": True})
    first = finish_campaign_pack(URL, run, "logo-test", 1, "product.png", settings, candidate, review)
    from admaker.cloud_objects import CloudPublicationPending
    output = tmp_path / first.exports["story"]["key"]
    original = output.read_bytes()
    output.write_bytes(b"changed after review")
    with pytest.raises(CloudPublicationPending):
        finish_campaign_pack(URL, run, "logo-test", 1, "product.png", settings, candidate, review)
    output.write_bytes(original)
    second = finish_campaign_pack(URL, run, "logo-test", 1, "product.png", settings, candidate, review)
    assert first == second and len(renders) == len(reviews) == 1
    with pytest.raises(RuntimeError, match="inputs changed"):
        finish_campaign_pack(URL, run, "logo-test", 1, "product.png", {"campaignBrief": {**settings["campaignBrief"], "logoAssetKey": None}}, candidate, review)
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone()[0] == 0
