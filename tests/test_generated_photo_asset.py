import uuid

import psycopg
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.photo_provider import PHOTO_MODEL
from admaker.worker import process_one
from test_provider_graph import provider_job
from test_worker_leases import URL, queued_job


def test_generated_photo_can_be_approved_and_reused_without_generation(provider_job, monkeypatch, tmp_path):
    account, job, _, queue = provider_job
    monkeypatch.setenv("PHOTO_DAILY_BUDGET_MICROUSD", "100000000000")
    with psycopg.connect(URL) as connection:
        source = connection.execute("UPDATE app.jobs SET settings=%s WHERE id=%s RETURNING source_asset_id",
            (Jsonb({"outputKind": "photo", "photoProvider": True, "preparedPhotoPrompt": "Soft light",
                "photoModel": PHOTO_MODEL, "renderPlatforms": ["feed_square"]}), job)).fetchone()[0]
    calls = []
    def generate(*args, **kwargs):
        calls.append(True)
        return (tmp_path / "test.png").read_bytes()
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "photo@example.test")
    try:
        assert process_one(URL, "photo", queue, photo_generate=generate, estimated_cost_microusd=7,
            video_review=lambda *args: {"policyAllowed": True, "qualityPassed": True, "offerFree": True})
        with TestClient(app) as client:
            result = client.get(f"/v1/jobs/{job}").json()
            route = f"/v1/jobs/{job}/photo-asset"
            payload = {"expectedResultVersion": result["resultVersion"], "platform": "feed"}
            assert client.post(route, json={**payload, "expectedResultVersion": "0" * 64}).status_code == 409
            response = client.post(route, json=payload)
            assert response.status_code == 200, response.text
            asset = response.json()["assetKey"]
            assert client.post(route, json=payload).json() == response.json()
            assert client.get(f"/v1/assets/{asset}").content == client.get(result["exports"][0]["url"]).content
            product = client.post("/v1/products", json={"name": "Saved product", "assetKey": str(source)}).json()
            approval = f"/v1/products/{product['id']}/approved-image"
            assert client.post(approval, json={"assetKey": asset, "expectedVersion": 0}).json()["version"] == 1
            for number in range(2):
                campaign = client.post("/v1/campaigns", json={"productId": product["id"], "imageVersion": 1},
                    headers={"Idempotency-Key": f"reuse-{number}"})
                assert campaign.status_code == 201, campaign.text
                assert campaign.json()["assetKey"] == asset
            assert client.post(approval, json={"assetKey": str(source), "expectedVersion": 1}).json()["version"] == 2
            assert client.get(approval, params={"version": 1}).json()["image"]["assetKey"] == asset
            app.dependency_overrides[authenticated_subject] = lambda: Subject(str(uuid.uuid4()), "other@example.test")
            assert client.post(route, json=payload).status_code == 404
            assert client.get(f"/v1/assets/{asset}").status_code == 404
            app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "photo@example.test")
            with psycopg.connect(URL) as connection:
                key = connection.execute("SELECT storage_key FROM app.assets WHERE asset_key=%s", (asset,)).fetchone()[0]
                assert connection.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (1,)
                assert connection.execute("SELECT count(*) FROM app.jobs WHERE owner_id=%s", (account,)).fetchone() == (1,)
            path = (tmp_path / key).resolve()
            assert path.is_relative_to(tmp_path.resolve())
            path.write_bytes((tmp_path / "test.png").read_bytes())
            assert client.post(route, json=payload).status_code == 409
        assert calls == [True]
    finally:
        app.dependency_overrides.clear()
        with psycopg.connect(URL) as connection:
            connection.execute("DELETE FROM app.command_keys WHERE account_id=%s", (account,))
            connection.execute("DELETE FROM app.campaigns WHERE owner_id=%s", (account,))
            connection.execute("DELETE FROM app.product_images WHERE owner_id=%s", (account,))
            connection.execute("DELETE FROM app.products WHERE owner_id=%s", (account,))
            connection.execute("DELETE FROM app.assets WHERE owner_id=%s AND asset_key<>%s", (account, source))
            connection.execute("DELETE FROM app.provider_budget_holds WHERE attempt_id IN (SELECT a.id FROM app.job_attempts a JOIN app.job_runs r ON r.id=a.run_id WHERE r.job_id=%s)", (job,))
