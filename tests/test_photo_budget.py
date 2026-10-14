import uuid

import psycopg
import pytest

from admaker.db import migrate
from admaker.provider_budget import reserve_provider_budget
from test_worker_leases import URL


def test_photo_and_video_estimates_have_separate_caps_and_immutable_kind(monkeypatch):
    migrate(URL)
    ids = [uuid.uuid4() for _ in range(4)]
    with psycopg.connect(URL) as connection:
        totals = dict(connection.execute("SELECT media_kind,sum(amount_microusd) FROM app.provider_budget_holds WHERE created_at >= date_trunc('day',clock_timestamp() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' GROUP BY media_kind"))
    monkeypatch.setenv("VEO_DAILY_BUDGET_MICROUSD", str(totals.get("video", 0) + 10))
    monkeypatch.setenv("PHOTO_DAILY_BUDGET_MICROUSD", str(totals.get("photo", 0) + 7))
    try:
        with psycopg.connect(URL) as connection:
            reserve_provider_budget(connection, ids[0], 10)
            reserve_provider_budget(connection, ids[1], 7, media_kind="photo")
        with psycopg.connect(URL) as connection:
            reserve_provider_budget(connection, ids[1], 7, media_kind="photo")
        with pytest.raises(OSError, match="changed"):
            with psycopg.connect(URL) as connection:
                reserve_provider_budget(connection, ids[1], 7, media_kind="video")
        for kind, identifier in zip(("video", "photo"), ids[2:]):
            with pytest.raises(OSError, match="exhausted"):
                with psycopg.connect(URL) as connection:
                    reserve_provider_budget(connection, identifier, 1, media_kind=kind)
        monkeypatch.delenv("PHOTO_DAILY_BUDGET_MICROUSD")
        with pytest.raises(OSError, match="photo budget is required"):
            with psycopg.connect(URL) as connection:
                reserve_provider_budget(connection, ids[3], 1, media_kind="photo")
    finally:
        with psycopg.connect(URL) as connection:
            connection.execute("DELETE FROM app.provider_budget_holds WHERE attempt_id=ANY(%s)", (ids,))
