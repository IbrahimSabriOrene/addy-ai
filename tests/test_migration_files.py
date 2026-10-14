import pytest

from admaker import db


def test_missing_migrations_fail_before_database_connection(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "MIGRATIONS", tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="Migration files are missing"):
        db.migrate()
