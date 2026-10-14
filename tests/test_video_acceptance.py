import pytest
import psycopg

from test_decision_settlement import decision_job
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("missing", [True, False])
def test_video_accept_does_not_charge_for_missing_or_changed_bytes(decision_job, tmp_path, missing):
    client, account, job, reservation, *_ = decision_job
    path = tmp_path / "private/candidate.mp4"
    original = path.read_bytes()
    if missing:
        path.unlink()
    else:
        path.write_bytes(b"different candidate")
    version = client.get(f"/v1/jobs/{job}").json()["version"]
    body, headers = {"action": "accept", "expectedVersion": version}, {"Idempotency-Key": "video-accept"}
    assert client.post(f"/v1/jobs/{job}/decision", json=body, headers=headers).status_code == 409
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("held",)
        assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
    path.write_bytes(original)
    for _ in range(2):
        assert client.post(f"/v1/jobs/{job}/decision", json=body, headers=headers).status_code == 202
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT count(*),sum(delta) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (1, -2)
