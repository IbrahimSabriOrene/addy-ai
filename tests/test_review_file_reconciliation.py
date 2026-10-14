import uuid

import psycopg
import pytest

from admaker.review_file_reconciliation import resolve_absent_review_file
from admaker.review_files import delete_requested_review_files, stage_review_file
from test_review_files import file_store
from test_provider_graph import provider_job
from test_worker_leases import URL, queued_job


@pytest.mark.parametrize("delete", [False, True])
def test_terminal_evidence_unlocks_retry_or_deletion_without_charging(provider_job, file_store, delete):
    account, job, _, _ = provider_job
    file_store.files.lose_upload = True
    with pytest.raises(OSError):
        stage_review_file(URL, job, b"uncertain", "video/mp4", store=file_store)
    name = next(iter(file_store.files.objects))
    resolution = uuid.uuid4()
    args = (URL, account, name, resolution, "fixture-operator", "restricted-terminal-proof")
    try:
        with pytest.raises(ValueError, match="terminal"):
            resolve_absent_review_file(*args, verified_terminal=False, store=file_store)
        with pytest.raises(ValueError, match="exists"):
            resolve_absent_review_file(*args, verified_terminal=True, store=file_store)
        file_store.files.objects.clear()
        assert resolve_absent_review_file(*args, verified_terminal=True, store=file_store)
        assert resolve_absent_review_file(*args, verified_terminal=True, store=file_store)
        with pytest.raises(ValueError, match="different"):
            resolve_absent_review_file(URL, account, name, resolution, "other", "other", verified_terminal=True, store=file_store)
        assert file_store.files.uploads == 1
        if delete:
            with psycopg.connect(URL) as connection:
                connection.execute("INSERT INTO app.account_deletions(account_id) VALUES (%s)", (account,))
            assert delete_requested_review_files(URL, account, store=file_store) == {"state": "review_files_removed"}
        else:
            file_store.files.lose_upload = False
            uri = stage_review_file(URL, job, b"uncertain", "video/mp4", store=file_store)
            assert not uri.endswith(name) and file_store.files.uploads == 2
        with psycopg.connect(URL) as connection:
            assert connection.execute("SELECT count(*) FROM app.review_file_resolutions WHERE id=%s", (resolution,)).fetchone() == (1,)
            assert connection.execute("SELECT count(*) FROM app.credit_ledger WHERE account_id=%s", (account,)).fetchone() == (0,)
    finally:
        with psycopg.connect(URL) as connection:
            connection.execute("DELETE FROM app.review_file_resolutions WHERE account_id=%s", (account,))
