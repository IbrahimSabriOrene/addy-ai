import uuid
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import psycopg
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.db import migrate
from admaker.reports import update_report


def test_private_durable_report_and_support_resolution(monkeypatch):
    url = "postgresql://postgres:postgres@localhost:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", url)
    migrate()
    owner, other, asset, job, pending = (uuid.uuid4() for _ in range(5))
    snapshot = {"exports": {"feed": {"key": "private/original-result.png"}}}
    with psycopg.connect(url) as connection:
        connection.execute("INSERT INTO app.accounts(id,email) VALUES (%s,'report@example.com'),(%s,'other@example.com')", (owner, other))
        connection.execute("INSERT INTO app.assets(asset_key,owner_id,storage_key,mime_type,verification_state) VALUES (%s,%s,'test.png','image/png','verified')", (asset, owner))
        connection.execute("INSERT INTO app.jobs(id,owner_id,source_asset_id,state,result) VALUES (%s,%s,%s,'delivered',%s),(%s,%s,%s,'submitted','{}')", (job, owner, asset, Jsonb(snapshot), pending, owner, asset))
    current = owner
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(current), "report@example.com")
    headers = {"Idempotency-Key": str(uuid.uuid4())}
    path = f"/v1/jobs/{job}/reports"
    payload = {"reason": "product_accuracy", "details": "The handle is missing.",
               "expectedResultVersion": hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()}
    try:
        with TestClient(app) as client:
            assert client.post(path, json=payload).status_code == 422
            assert client.post(path, json={**payload, "details": "x" * 1001}, headers=headers).status_code == 422
            assert client.get(f"/v1/jobs/{job}").json()["resultVersion"] == payload["expectedResultVersion"]
            assert client.post(path, json={**payload, "expectedResultVersion": "0" * 64}, headers=headers).status_code == 409
            assert client.post(f"/v1/jobs/{pending}/reports", json=payload, headers=headers).status_code == 409
            current = other
            assert client.get(path).status_code == 404
            assert client.post(path, json=payload, headers=headers).status_code == 404
            current = owner
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(lambda _: client.post(path, json=payload, headers=headers), range(2)))
            assert [response.status_code for response in responses] == [201, 201]
            assert responses[0].json() == responses[1].json()
            report_id = uuid.UUID(responses[0].json()["id"])
            assert client.post(path, json={**payload, "reason": "rights"}, headers=headers).status_code == 409
            with psycopg.connect(url) as connection:
                assert connection.execute("SELECT count(*) FROM app.result_reports WHERE job_id=%s", (job,)).fetchone()[0] == 1
                connection.execute("UPDATE app.jobs SET result=%s WHERE id=%s", (Jsonb({"exports": {"feed": {"key": "new.png"}}}), job))
                assert connection.execute("SELECT result_snapshot FROM app.result_reports WHERE id=%s", (report_id,)).fetchone()[0] == snapshot
                assert connection.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (owner,)).fetchone()[0] == 0
            assert client.post(path, json=payload, headers={"Idempotency-Key": "another-action"}).status_code == 409
            assert client.post(path, json=payload, headers=headers).json()["id"] == str(report_id)
            assert update_report(url, report_id, "operator-a")
            assert not update_report(url, report_id, "operator-b")
            assert not update_report(url, report_id, "operator-b", "Reviewed.")
            assert update_report(url, report_id, "operator-a", "Reviewed the product mismatch. Please use your original photo while we investigate.")
            report = client.get(path).json()["items"][0]
            assert report["status"] == "resolved"
            assert report["resolution"].startswith("Reviewed the product")
            assert "assignee" not in report and "result_snapshot" not in report
            current = other
            assert client.get(path).status_code == 404
    finally:
        app.dependency_overrides.clear()
        with psycopg.connect(url) as connection:
            connection.execute("DELETE FROM app.result_reports WHERE owner_id=%s", (owner,))
            connection.execute("DELETE FROM app.command_keys WHERE account_id IN (%s,%s)", (owner, other))
            connection.execute("DELETE FROM app.jobs WHERE owner_id=%s", (owner,))
            connection.execute("DELETE FROM app.assets WHERE owner_id=%s", (owner,))
            connection.execute("DELETE FROM app.accounts WHERE id IN (%s,%s)", (owner, other))
