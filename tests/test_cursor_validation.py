import base64
from datetime import datetime, timezone
import uuid

import pytest
from fastapi import HTTPException

from admaker.api import _job_cursor, _parse_job_cursor


def test_cursor_requires_valid_bounded_timestamp_uuid_and_encoding():
    identifier = uuid.uuid4()
    timestamp = datetime.now(timezone.utc)
    assert _parse_job_cursor(_job_cursor(timestamp, identifier)) == (timestamp.isoformat(), identifier)
    malformed = ["!invalid", "a" * 257]
    for date, job_id in [("not-a-date", identifier), ("2026-09-08", identifier), ("2026-99-99T00:00:00Z", identifier), (timestamp.isoformat(), "not-a-uuid")]:
        malformed.append(base64.urlsafe_b64encode(f"{date}|{job_id}".encode()).decode())
    for cursor in malformed:
        with pytest.raises(HTTPException) as error:
            _parse_job_cursor(cursor)
        assert error.value.status_code == 422
