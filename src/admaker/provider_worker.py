"""Explicit campaign-provider worker; validates configuration before reading its queue."""
import argparse
import os
import re
import socket
import shutil
import time
from functools import partial

import psycopg

from admaker.db import database_ready, MIGRATIONS
from admaker.media_review import build_media_reviewer
from admaker.provider_graph import PROVIDER_GRAPH_VERSION
from admaker.review_budget import review_budget_limits
from admaker.veo import FAST_MODEL, VeoService
from admaker.worker import process_one, recover_expired_runs


def provider_worker_configuration():
    if os.environ.get("ENABLE_REAL_VEO") != "true" or os.environ.get("ENABLE_REAL_MEDIA_REVIEW") != "true":
        raise ValueError("Explicit video and review enablement are required")
    url, queue, model = (os.environ.get(key, "") for key in ("DATABASE_URL", "CAMPAIGN_PACK_QUEUE", "MEDIA_REVIEW_MODEL"))
    if (not url or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,47}", queue)
            or queue in {"commands", os.environ.get("PHOTO_QUEUE", "")}):
        raise ValueError("A database and dedicated campaign queue are required")
    if not re.fullmatch(r"gemini-[a-zA-Z0-9._-]{1,100}", model) or os.environ.get("VEO_MODEL", FAST_MODEL) != FAST_MODEL:
        raise ValueError("Supported server-configured models are required")
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key.strip() or os.environ.get("GOOGLE_API_KEY", key) != key:
        raise ValueError("Use one consistent Gemini API key for generation and review")
    review_budget_limits()
    values = []
    for name, maximum in (("VEO_ESTIMATED_COST_MICROUSD", 1_000_000_000),
                          ("VEO_DAILY_BUDGET_MICROUSD", 1_000_000_000_000),
                          ("VEO_MAX_CONCURRENT_OPERATIONS", 10000)):
        value = os.environ.get(name, "")
        if not value.isdecimal() or not 0 < int(value) <= maximum:
            raise ValueError("Positive bounded video budgets are required")
        values.append(int(value))
    if values[0] > values[1]:
        raise ValueError("Video estimate exceeds the daily budget")
    return url, queue, model, values[0]


def recover_campaign_provider_runs(database_url, queue):
    with psycopg.connect(database_url) as connection:
        jobs = connection.execute("SELECT j.id FROM app.jobs j JOIN app.job_runs r ON r.id=j.active_run_id "
            "WHERE (j.settings->>'generationKind'='campaign_pack' OR j.settings->>'videoProvider'='true') AND j.state='running' "
            "AND r.graph_version=%s AND r.state='running' AND r.lease_until<clock_timestamp() "
            "AND (r.next_work_at IS NULL OR r.next_work_at<=clock_timestamp())", (PROVIDER_GRAPH_VERSION,)).fetchall()
    return sum(recover_expired_runs(database_url, queue, str(job)) for (job,) in jobs)


def verify_provider_runtime(database_url):
    if not all(shutil.which(name) for name in ("ffmpeg", "ffprobe")):
        raise ValueError("FFmpeg and ffprobe are required")
    with psycopg.connect(database_url) as connection:
        applied = {row[0] for row in connection.execute("SELECT version FROM public.schema_migrations")}
    if {path.name for path in MIGRATIONS.glob("*.sql")} - applied:
        raise ValueError("Apply all database migrations before starting the provider worker")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Process at most one queued job, then exit")
    args = parser.parse_args()
    try:
        database_url, queue, model, estimate = provider_worker_configuration()
        if not database_ready(database_url):
            raise ValueError("Database is unavailable")
        verify_provider_runtime(database_url)
        service = VeoService()
        reviewer = partial(build_media_reviewer, model=model)
        owner = f"{socket.gethostname()}:{os.getpid()}:provider"
        while True:
            recover_campaign_provider_runs(database_url, queue)
            worked = process_one(database_url, owner, queue, video_service=service,
                                 estimated_cost_microusd=estimate, video_review_factory=reviewer)
            if args.once:
                return
            if not worked:
                time.sleep(1)
    except KeyboardInterrupt:
        return
    except Exception:
        raise SystemExit("Provider worker stopped; check server configuration and private operational records.") from None


if __name__ == "__main__":
    main()
