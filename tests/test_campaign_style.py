import json
import uuid

import psycopg
from fastapi.testclient import TestClient

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from admaker.catalogue import TEMPLATES
from test_worker_leases import queued_job


def test_campaign_freezes_private_style_and_replays_after_catalogue_change(queued_job, monkeypatch):
    account, job, reservation, queue = queued_job
    url = "postgresql://postgres:postgres@localhost:54322/postgres"
    monkeypatch.setenv("DATABASE_URL", url)
    with psycopg.connect(url) as connection:
        asset = connection.execute("SELECT asset_key FROM app.assets WHERE owner_id=%s", (account,)).fetchone()[0]
    app.dependency_overrides[authenticated_subject] = lambda: Subject(str(account), "style@example.com")
    try:
        with TestClient(app) as client:
            product = client.post("/v1/products", json={"name": "Product", "assetKey": str(asset)}).json()["id"]
            assert client.post(f"/v1/products/{product}/approved-image", json={"assetKey": str(asset), "expectedVersion": 0}).status_code == 200
            payload = {"productId": product, "imageVersion": 1, "templateId": "pedestal_spin", "templateVersion": 1}
            headers = {"Idempotency-Key": str(uuid.uuid4())}
            first = client.post("/v1/campaigns", json=payload, headers=headers)
            assert first.status_code == 201
            campaign = first.json()
            original = TEMPLATES["pedestal_spin"]
            assert campaign["brief"]["style"] == {k: original[k] for k in ("id", "version", "name")}
            with psycopg.connect(url) as connection:
                assert connection.execute("SELECT style_snapshot FROM app.campaigns WHERE id=%s", (campaign["id"],)).fetchone()[0] == original
            monkeypatch.setitem(TEMPLATES, "pedestal_spin", {**original, "version": 2, "prompt": "changed private instruction"})
            assert client.post("/v1/campaigns", json=payload, headers=headers).json() == campaign
            for changes in ({}, {"templateVersion": None}, {"templateId": "unknown"}):
                rejected = client.post("/v1/campaigns", json={**payload, **changes}, headers={"Idempotency-Key": str(uuid.uuid4())})
                assert rejected.status_code == 422
            public = [client.get(f"/v1/campaigns/{campaign['id']}").json(), client.get(f"/v1/products/{product}/campaigns").json()]
            assert original["prompt"] not in json.dumps(public)
            assert "style_snapshot" not in json.dumps(public)
            assert public[0]["brief"]["style"]["version"] == 1
    finally:
        app.dependency_overrides.clear()
        with psycopg.connect(url) as connection:
            connection.execute("DELETE FROM app.command_keys WHERE account_id=%s", (account,))
            connection.execute("DELETE FROM app.campaigns WHERE owner_id=%s", (account,))
            connection.execute("DELETE FROM app.product_images WHERE owner_id=%s", (account,))
            connection.execute("DELETE FROM app.products WHERE owner_id=%s", (account,))
