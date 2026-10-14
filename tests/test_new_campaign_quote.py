from fastapi.testclient import TestClient
import psycopg

from admaker.api import app
from admaker.auth import Subject, authenticated_subject
from test_worker_leases import URL, queued_job


def test_pack_quote_precedes_campaign_creation_and_never_reserves_credits(queued_job, monkeypatch):
    account, job, reservation, queue = queued_job
    monkeypatch.setenv("DATABASE_URL", URL)
    with TestClient(app) as client:
        assert client.get("/v1/campaign-pack/quote").status_code == 401
        app.dependency_overrides[authenticated_subject] = lambda: Subject(account, "fixture@example.test")
        try:
            monkeypatch.setenv("ENABLE_CAMPAIGN_PACKS", "true")
            monkeypatch.setenv("CAMPAIGN_PACK_CREDITS", "3")
            monkeypatch.setenv("CAMPAIGN_PACK_QUEUE", queue)
            quote = client.get("/v1/campaign-pack/quote").json()
            assert quote["available"] and quote["priceCredits"] == 3
            assert quote["scope"] == "campaign_pack" and len(quote["outputs"]) == 5
            assert "campaignId" not in quote
            monkeypatch.setenv("CAMPAIGN_PACK_CREDITS", "7")
            assert client.get("/v1/campaign-pack/quote").json()["priceCredits"] == 7
            monkeypatch.setenv("ENABLE_CAMPAIGN_PACKS", "false")
            disabled = client.get("/v1/campaign-pack/quote").json()
            assert disabled["available"] is False and disabled["priceCredits"] is None
            with psycopg.connect(URL) as c:
                assert c.execute("SELECT count(*) FROM app.campaigns WHERE owner_id=%s", (account,)).fetchone() == (0,)
                assert c.execute("SELECT count(*) FROM app.jobs WHERE owner_id=%s", (account,)).fetchone() == (1,)
                assert c.execute("SELECT count(*) FROM app.credit_reservations WHERE account_id=%s", (account,)).fetchone() == (1,)
                assert c.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
        finally:
            app.dependency_overrides.pop(authenticated_subject, None)
