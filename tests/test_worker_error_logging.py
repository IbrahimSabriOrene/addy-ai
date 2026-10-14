import json
import logging

import psycopg

from admaker.worker import process_one
from test_worker_leases import URL, queued_job


def test_render_failure_log_excludes_exception_content(queued_job, monkeypatch, caplog):
    _, job, reservation, queue = queued_job
    secret = "private-product-description-and-provider-token"
    def fail(*args):
        raise OSError(secret)
    monkeypatch.setattr("admaker.worker._render_fake", fail)
    with caplog.at_level(logging.ERROR):
        assert process_one(URL, "safe-log-check", queue)
    assert secret not in caplog.text
    events = [json.loads(record.message) for record in caplog.records if record.message.startswith('{"event": "generation_failed"')]
    assert len(events) == 1
    assert events[0]["jobId"] == str(job) and events[0]["errorType"] == "OSError"
    assert all(record.exc_info is None for record in caplog.records)
    with psycopg.connect(URL) as c:
        assert c.execute("SELECT state FROM app.credit_reservations WHERE id=%s", (reservation,)).fetchone() == ("released",)
