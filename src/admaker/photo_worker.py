"""Explicit photo worker; never consumes the default fixture/video queue."""
import argparse
import os
import re
import socket
import time
from functools import partial

import psycopg

from admaker.db import MIGRATIONS, database_ready
from admaker.media_review import build_media_reviewer
from admaker.photo_graph import PHOTO_GRAPH_VERSION
from admaker.photo_provider import generate_product_photo
from admaker.review_budget import review_budget_limits
from admaker.worker import process_one, recover_expired_runs


def photo_worker_configuration():
    if os.environ.get("ENABLE_REAL_PHOTO") != "true" or os.environ.get("ENABLE_REAL_MEDIA_REVIEW") != "true":
        raise ValueError("Explicit photo and review enablement are required")
    url, queue, model = (os.environ.get(key, "") for key in ("DATABASE_URL", "PHOTO_QUEUE", "MEDIA_REVIEW_MODEL"))
    if (not url or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,47}", queue)
            or queue in {"commands", os.environ.get("CAMPAIGN_PACK_QUEUE", "")}):
        raise ValueError("A database and dedicated photo queue are required")
    if not re.fullmatch(r"gemini-[a-zA-Z0-9._-]{1,100}", model):
        raise ValueError("A server review model is required")
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key.strip() or os.environ.get("GOOGLE_API_KEY", key) != key:
        raise ValueError("Consistent photo and review credentials are required")
    review_budget_limits()
    values = []
    for name, maximum in (("PHOTO_ESTIMATED_COST_MICROUSD", 1_000_000_000),
                          ("PHOTO_DAILY_BUDGET_MICROUSD", 1_000_000_000_000),
                          ("PHOTO_MAX_CONCURRENT_OPERATIONS", 10000)):
        value = os.environ.get(name, "")
        if not re.fullmatch(r"[0-9]+", value) or not 0 < int(value) <= maximum:
            raise ValueError("Positive bounded photo budgets are required")
        values.append(int(value))
    if values[0] > values[1]:
        raise ValueError("Photo estimate exceeds the daily budget")
    return url, queue, model, values[0]


def recover_photo_runs(database_url, queue):
    with psycopg.connect(database_url) as connection:
        jobs = connection.execute("""SELECT j.id FROM app.jobs j JOIN app.job_runs r ON r.id=j.active_run_id
            WHERE j.settings->>'outputKind'='photo' AND j.state='running' AND r.graph_version=%s
            AND r.state='running' AND r.lease_until<clock_timestamp()
            AND (r.next_work_at IS NULL OR r.next_work_at<=clock_timestamp())""", (PHOTO_GRAPH_VERSION,)).fetchall()
    return sum(recover_expired_runs(database_url, queue, str(job)) for (job,) in jobs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    try:
        url, queue, model, estimate = photo_worker_configuration()
        if not database_ready(url):
            raise ValueError("Photo database is unavailable")
        with psycopg.connect(url) as connection:
            applied = {row[0] for row in connection.execute("SELECT version FROM public.schema_migrations")}
        if {path.name for path in MIGRATIONS.glob("*.sql")} - applied:
            raise ValueError("Apply database migrations before starting the photo worker")
        reviewer = partial(build_media_reviewer, model=model)
        owner = f"{socket.gethostname()}:{os.getpid()}:photo"
        while True:
            recover_photo_runs(url, queue)
            worked = process_one(url, owner, queue, photo_generate=generate_product_photo,
                estimated_cost_microusd=estimate, video_review_factory=reviewer)
            if args.once:
                return
            if not worked:
                time.sleep(1)
    except KeyboardInterrupt:
        return
    except Exception:
        raise SystemExit("Photo worker stopped; check server configuration and restricted operational records.") from None


if __name__ == "__main__":
    main()
