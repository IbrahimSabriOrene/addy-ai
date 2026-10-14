from datetime import datetime, timedelta, timezone
import uuid

import psycopg

from admaker.ops_status import operational_snapshot
from test_worker_leases import URL, queued_job


def test_utc_day_boundary_and_media_review_totals(queued_job):
    queue = queued_job[3]
    # Non-UTC database session must still aggregate at UTC midnight.
    url = URL + "?options=-c%20timezone%3DPacific%2FHonolulu"
    before = operational_snapshot(url, queue)
    midnight = datetime.fromisoformat(before["observedAt"]).astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    media_ids, review_ids = [], []
    try:
        with psycopg.connect(URL) as c:
            for kind, amount in [("photo", 110), ("video", 230)]:
                for stamp, value in [(midnight, amount), (midnight - timedelta(microseconds=1), 9999)]:
                    key = uuid.uuid4()
                    media_ids.append(key)
                    c.execute("INSERT INTO app.provider_budget_holds(attempt_id,amount_microusd,media_kind,created_at) VALUES (%s,%s,%s,%s)", (key, value, kind, stamp))
            for stamp, value in [(midnight, 370), (midnight - timedelta(microseconds=1), 9999)]:
                key = uuid.uuid4()
                review_ids.append(key)
                c.execute("INSERT INTO app.media_review_budget(id,amount_microusd,created_at) VALUES (%s,%s,%s)", (key, value, stamp))
        after = operational_snapshot(url, queue)
        assert datetime.fromisoformat(after["observedAt"]).astimezone(timezone.utc).date() == midnight.date()
        for name, delta in [("photo", 110), ("video", 230), ("provider", 340), ("reviewAndPlanning", 370), ("total", 710)]:
            field = name + "CommittedEstimateMicrousdToday"
            assert after[field] - before[field] == delta
    finally:
        with psycopg.connect(URL) as c:
            c.execute("DELETE FROM app.provider_budget_holds WHERE attempt_id=ANY(%s)", (media_ids,))
            c.execute("DELETE FROM app.media_review_budget WHERE id=ANY(%s)", (review_ids,))
