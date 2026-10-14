import hashlib
import json

import psycopg
import pytest
from psycopg.types.json import Jsonb

from test_decision_settlement import decision_job
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("damage", ["missing_file", "missing_output", "outside_root", "empty_file", "missing_copy", "changed_file", "missing_checksum", None])
def test_pack_acceptance_requires_all_outputs_before_debit(decision_job, monkeypatch, tmp_path, damage):
    client, account, job, reservation, queue, run, attempt = decision_job
    monkeypatch.setenv("LOCAL_ASSET_ROOT", str(tmp_path))
    manifest = {kind: {"key": f"{kind}.bin"} for kind in ("cleanImage", "video", "story", "feed")}
    for item in manifest.values():
        (tmp_path / item["key"]).write_bytes(b"Previously validated fixture output")
        item["sha256"] = hashlib.sha256(b"Previously validated fixture output").hexdigest()
    manifest["copy"] = {"caption": "Caption", "cta": "Shop"}
    if damage == "missing_file":
        (tmp_path / "story.bin").unlink()
    elif damage == "missing_output":
        del manifest["feed"]
    elif damage == "outside_root":
        manifest["video"]["key"] = "../outside.mp4"
    elif damage == "empty_file":
        (tmp_path / "video.bin").write_bytes(b"")
    elif damage == "missing_copy":
        manifest["copy"] = {}
    elif damage == "changed_file":
        (tmp_path / "feed.bin").write_bytes(b"Different bytes")
    elif damage == "missing_checksum":
        del manifest["video"]["sha256"]
    validation = {"technicalPassed": True, "policyAllowed": True, "reservationId": str(reservation),
                  "exportsHash": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()}
    with psycopg.connect(URL) as c:
        version = c.execute("UPDATE app.jobs SET settings=%s,result=%s WHERE id=%s RETURNING version", (Jsonb({"generationKind": "campaign_pack"}), Jsonb({"exports": manifest, "candidateValidation": validation}), job)).fetchone()[0]
    body, headers = {"action": "accept", "expectedVersion": version}, {"Idempotency-Key": "accept-pack"}
    response = client.post(f"/v1/jobs/{job}/decision", json=body, headers=headers)
    assert response.status_code == (409 if damage else 202)
    if not damage:
        # A receipt stays replayable even if a file later disappears.
        (tmp_path / "video.bin").unlink()
        assert client.post(f"/v1/jobs/{job}/decision", json=body, headers=headers).json() == response.json()
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("held" if damage else "consumed",)
        assert c.execute("SELECT count(*),COALESCE(sum(delta),0) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == ((0, 0) if damage else (1, -2))
