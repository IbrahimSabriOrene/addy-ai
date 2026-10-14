"""Small PostgreSQL helpers shared by API and worker processes."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row


MIGRATIONS = Path(os.environ.get("ADMAKER_MIGRATIONS_DIR", str(Path(__file__).parents[2] / "migrations")))


class RunLeaseLost(Exception):
    """An expired/replaced worker must stop without settling the reservation."""


def lock_run_lease(cursor, run_id: uuid.UUID, owner: str, fence: int) -> None:
    if not cursor.execute("SELECT id FROM app.jobs WHERE active_run_id=%s AND state='running' FOR UPDATE", (run_id,)).fetchone():
        raise RunLeaseLost()
    if not cursor.execute(
        "SELECT id FROM app.job_runs WHERE id=%s AND state='running' AND lease_owner=%s AND fence=%s AND lease_until>clock_timestamp() FOR UPDATE",
        (run_id, owner, fence),
    ).fetchone():
        raise RunLeaseLost()


class FencedPostgresSaver(PostgresSaver):
    """Checkpoint SQL and lease validation share one short transaction."""

    def __init__(self, connection, run_id: uuid.UUID, owner: str, fence: int):
        super().__init__(connection)
        self.run_id, self.owner, self.fence = run_id, owner, fence

    def put_writes(self, config, writes, task_id, task_path=""):
        # Pinned LangGraph error channel; payloads may contain private URLs or input.
        safe_writes = [(channel, RuntimeError("Generation step failed") if channel == "__error__" else value)
                       for channel, value in writes]
        return super().put_writes(config, safe_writes, task_id, task_path)

    @contextmanager
    def _cursor(self, *, pipeline: bool = False):
        # Pinned PostgresSaver uses this hook for every read/write. Avoid pipeline
        # mode so fence validation precedes SQL and commits atomically with it.
        with self.lock, self.conn.transaction(), self.conn.cursor(binary=True, row_factory=dict_row) as cursor:
            lock_run_lease(cursor, self.run_id, self.owner, self.fence)
            yield cursor


@contextmanager
def postgres_checkpointer(database_url: str | None = None) -> Iterator[PostgresSaver]:
    """Open the durable LangGraph saver for a worker-owned graph invocation."""
    with PostgresSaver.from_conn_string(database_url or os.environ["DATABASE_URL"]) as saver:
        saver.setup()
        yield saver


def database_ready(database_url: str | None, timeout: int = 2) -> bool:
    if not database_url:
        return False
    try:
        with psycopg.connect(database_url, connect_timeout=timeout) as connection:
            connection.execute("SELECT 1")
        return True
    except psycopg.Error:
        return False


def migrate(database_url: str | None = None) -> None:
    paths = sorted(MIGRATIONS.glob("*.sql"))
    if not paths:
        raise RuntimeError("Migration files are missing; configure ADMAKER_MIGRATIONS_DIR")
    database_url = database_url or os.environ["DATABASE_URL"]
    with psycopg.connect(database_url) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS public.schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        for path in paths:
            if connection.execute("SELECT 1 FROM public.schema_migrations WHERE version = %s", (path.name,)).fetchone():
                continue
            connection.execute(path.read_text(encoding="utf-8"))
            connection.execute("INSERT INTO public.schema_migrations (version) VALUES (%s)", (path.name,))


def main() -> None:
    migrate()
