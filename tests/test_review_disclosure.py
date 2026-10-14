import psycopg
import pytest

from admaker.consent import DISCLOSURE, DISCLOSURE_VERSION, require_ai_consent
from admaker.eligibility import POLICY_VERSION
from test_worker_leases import URL, queued_job


def test_generated_media_disclosure_requires_new_permission(queued_job, monkeypatch):
    account, _, _, _ = queued_job
    monkeypatch.setenv("DATABASE_URL", URL)
    assert "generated images and videos (including sound)" in DISCLOSURE
    assert "content/quality checks" in DISCLOSURE
    try:
        with psycopg.connect(URL) as c:
            c.execute("INSERT INTO app.account_eligibility(account_id,policy_version) VALUES (%s,%s)", (account, POLICY_VERSION))
            c.execute("INSERT INTO app.ai_consent(account_id,disclosure_version,granted) VALUES (%s,'google-media-2026-09-08-v2',true)", (account,))
        with pytest.raises(PermissionError):
            require_ai_consent(str(account))
        with psycopg.connect(URL) as c:
            c.execute("UPDATE app.ai_consent SET disclosure_version=%s WHERE account_id=%s", (DISCLOSURE_VERSION, account))
        require_ai_consent(str(account))
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.ai_consent WHERE account_id=%s", (account,))
