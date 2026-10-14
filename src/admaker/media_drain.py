"""Account-scoped PostgreSQL locks shared by media writers and deletion cleanup."""
from contextlib import contextmanager
import uuid

import psycopg
from admaker.db import RunLeaseLost


class AccountDeletionRequested(RunLeaseLost):
    pass


def lock_media_writer(connection, account_id):
    account_id = uuid.UUID(str(account_id))
    connection.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended(%s,0))", (f"account-media:{account_id}",))
    if connection.execute("SELECT 1 FROM app.account_deletions WHERE account_id=%s", (account_id,)).fetchone():
        raise AccountDeletionRequested("Account deletion has been requested")


@contextmanager
def job_media_writer(database_url, job_id):
    with psycopg.connect(database_url) as connection:
        row = connection.execute("SELECT owner_id FROM app.jobs WHERE id=%s", (job_id,)).fetchone()
        if not row:
            raise RunLeaseLost()
        lock_media_writer(connection, row[0])
        yield


def try_lock_media_cleanup(connection, account_id):
    """Call before any account/job row locks; hold transaction through cleanup."""
    account_id = uuid.UUID(str(account_id))
    if not connection.execute("SELECT 1 FROM app.account_deletions WHERE account_id=%s", (account_id,)).fetchone():
        raise ValueError("An admitted deletion request is required")
    return connection.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0))", (f"account-media:{account_id}",)).fetchone()[0]
