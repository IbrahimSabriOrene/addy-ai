import sys

import pytest

from admaker import provider_worker


def test_provider_entry_validates_before_touching_queue_and_binds_reviewer(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["provider-worker", "--once"])
    monkeypatch.setenv("ENABLE_REAL_VEO", "false")
    calls = []
    monkeypatch.setattr(provider_worker, "database_ready", lambda url: calls.append("database") or True)
    with pytest.raises(SystemExit):
        provider_worker.main()
    assert not calls
    configuration = {"ENABLE_REAL_VEO": "true", "ENABLE_REAL_MEDIA_REVIEW": "true", "DATABASE_URL": "fixture",
        "CAMPAIGN_PACK_QUEUE": "campaign_fixture", "MEDIA_REVIEW_MODEL": "gemini-fixture", "GEMINI_API_KEY": "fixture-key",
        "MEDIA_REVIEW_ESTIMATE_MICROUSD": "1", "MEDIA_REVIEW_DAILY_BUDGET_MICROUSD": "10",
        "MEDIA_REVIEW_MAX_CALLS_PER_RUN": "4", "MEDIA_REVIEW_MAX_CONCURRENT_CALLS": "2",
        "VEO_ESTIMATED_COST_MICROUSD": "10", "VEO_DAILY_BUDGET_MICROUSD": "100", "VEO_MAX_CONCURRENT_OPERATIONS": "2"}
    for key, value in configuration.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("VEO_MODEL", raising=False)
    monkeypatch.setenv("MEDIA_REVIEW_MAX_CONCURRENT_CALLS", "0")
    with pytest.raises(SystemExit):
        provider_worker.main()
    assert not calls
    monkeypatch.setenv("MEDIA_REVIEW_MAX_CONCURRENT_CALLS", "2")
    service = object()
    monkeypatch.setattr(provider_worker, "verify_provider_runtime", lambda url: calls.append("runtime"))
    monkeypatch.setattr(provider_worker, "VeoService", lambda: service)
    monkeypatch.setattr(provider_worker, "recover_campaign_provider_runs", lambda url, queue: calls.append(("recover", queue)))
    monkeypatch.setattr(provider_worker, "build_media_reviewer", lambda db, job, run, model: (db, job, run, model))
    def process(url, owner, queue, **kwargs):
        calls.append(("process", queue))
        assert kwargs["video_service"] is service and kwargs["estimated_cost_microusd"] == 10
        assert kwargs["video_review_factory"](url, "job", "run") == ("fixture", "job", "run", "gemini-fixture")
        return False
    monkeypatch.setattr(provider_worker, "process_one", process)
    provider_worker.main()
    assert calls == ["database", "runtime", ("recover", "campaign_fixture"), ("process", "campaign_fixture")]


def test_runtime_refuses_missing_codecs_or_migrations(monkeypatch):
    monkeypatch.setattr(provider_worker.shutil, "which", lambda name: None)
    with pytest.raises(ValueError, match="FFmpeg"):
        provider_worker.verify_provider_runtime("fixture")
    monkeypatch.setattr(provider_worker.shutil, "which", lambda name: name)
    applied = []
    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, query):
            return applied
    monkeypatch.setattr(provider_worker.psycopg, "connect", lambda url: Connection())
    with pytest.raises(ValueError, match="migrations"):
        provider_worker.verify_provider_runtime("fixture")
    applied = [(path.name,) for path in provider_worker.MIGRATIONS.glob("*.sql")]
    provider_worker.verify_provider_runtime("fixture")
