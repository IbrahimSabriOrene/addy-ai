"""Worker process entry point; durable job consumption begins in milestone M2."""

from __future__ import annotations

import logging
import hashlib
import json
import os
import socket
import subprocess
import time
import uuid
from pathlib import Path
from contextlib import contextmanager
from threading import Event, Thread

import psycopg

from admaker.db import database_ready
from admaker.provider_budget import ProviderCapacityBusy
from admaker.cloud_objects import CloudPublicationPending
from admaker.media_review import MediaReviewPending
from admaker.review_files import ReviewFileProcessing


def run_worker_graph(database_url: str, run_id: uuid.UUID, owner: str, fence: int,
                     source: str, settings: dict, output_id: str, platforms: list[str]) -> dict:
    from admaker.db import FencedPostgresSaver, lock_run_lease, postgres_checkpointer
    from admaker.graph import WORKER_GRAPH_VERSION, build_worker_graph

    with psycopg.connect(database_url) as connection:
        thread_id, version = connection.execute("SELECT thread_id,graph_version FROM app.job_runs WHERE id=%s", (run_id,)).fetchone()
    if version != WORKER_GRAPH_VERSION:
        raise RuntimeError("Run requires an unavailable graph version; reservation remains held")
    request_hash = hashlib.sha256(json.dumps({"source": source, "settings": settings, "platforms": platforms}, sort_keys=True).encode()).hexdigest()

    def render_stage(state):
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            lock_run_lease(cursor, run_id, owner, fence)
            saved = cursor.execute("SELECT request_hash,result FROM app.job_stages WHERE run_id=%s AND stage_key='render'", (run_id,)).fetchone()
        if saved:
            if saved[0] != request_hash:
                raise RuntimeError("Stage input changed; refusing to replay")
            return {"exports": saved[1]}
        renderer = _render_photo_fake if settings.get("outputKind") == "photo" else _render_fake
        root = Path(os.environ.get("LOCAL_ASSET_ROOT", ".local-assets"))
        exports = renderer(root / source, root, output_id, platforms)
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            lock_run_lease(cursor, run_id, owner, fence)
            cursor.execute("INSERT INTO app.job_stages(run_id,stage_key,request_hash,result,fence) VALUES (%s,'render',%s,%s,%s)",
                           (run_id, request_hash, psycopg.types.json.Jsonb(exports), fence))
        return {"exports": exports}

    with postgres_checkpointer(database_url) as saver:
        fenced = FencedPostgresSaver(saver.conn, run_id, owner, fence)
        graph = build_worker_graph(render_stage, fenced)
        config = {"configurable": {"thread_id": thread_id}}
        state = graph.get_state(config)
        if state.values and (state.values.get("graph_version") != version or state.values.get("run_id") != str(run_id) or state.values.get("request_hash") != request_hash):
            raise RuntimeError("Checkpoint identity/version mismatch")
        result = graph.invoke(None if state.created_at else {"run_id": str(run_id), "graph_version": version, "request_hash": request_hash}, config=config, durability="sync")
    return result["exports"]


def _render_fake(source: Path, root: Path, job_id: str, platforms: list[str]) -> dict[str, dict[str, str]]:
    """Create deterministic local MP4s; paid providers remain opt-in."""
    from admaker.media import validate_video

    exports: dict[str, dict[str, str]] = {}
    for platform in platforms:
        key = f"runs/{job_id}/final_{platform}.mp4"
        destination = root / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        dimensions = "1080:1080" if platform in {"feed", "feed_square"} else "1080:1920"
        subprocess.run(
            ["ffmpeg", "-y", "-loop", "1", "-i", str(source), "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100", "-t", "8", "-vf", f"scale={dimensions}:force_original_aspect_ratio=decrease,pad={dimensions}:(ow-iw)/2:(oh-ih)/2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(destination)],
            check=True, capture_output=True, timeout=60,
        )
        metadata = validate_video(destination, tuple(int(value) for value in dimensions.split(":")))
        exports[platform] = {"key": key, "caption": "", "mimeType": "video/mp4", **metadata}
    return exports


def _render_photo_fake(source: Path, root: Path, output_id: str, platforms: list[str]) -> dict:
    """Local photo fixture: preserve the product and pad to the requested layout."""
    from PIL import Image, ImageOps

    exports = {}
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        for platform in platforms:
            size = (1080, 1080) if platform in {"feed", "feed_square"} else (1080, 1920)
            result = ImageOps.pad(image, size, color="white")
            key = f"runs/{output_id}/final_{platform}.png"
            destination = root / key
            destination.parent.mkdir(parents=True, exist_ok=True)
            result.save(destination, format="PNG")
            exports[platform] = {"key": key, "caption": "", "mimeType": "image/png"}
    return exports


def recover_expired_runs(database_url: str, queue: str = "commands", job_id: str | None = None) -> int:
    """Requeue expired leases; the worker reuses the recorded attempt."""
    from admaker.graph import WORKER_GRAPH_VERSION
    with psycopg.connect(database_url) as connection:
        rows = connection.execute("SELECT r.id, r.job_id FROM app.job_runs r JOIN app.jobs j ON j.active_run_id=r.id WHERE r.state='running' AND r.lease_until < clock_timestamp() AND (r.next_work_at IS NULL OR r.next_work_at<=clock_timestamp()) AND j.state='running' AND (%s::uuid IS NULL OR r.job_id=%s::uuid) AND (%s<>'commands' OR r.graph_version=%s) FOR UPDATE OF j SKIP LOCKED", (job_id, job_id, queue, WORKER_GRAPH_VERSION)).fetchall()
        for run_id, job_id in rows:
            connection.execute("UPDATE app.jobs SET state='submitted' WHERE active_run_id=%s AND state='running'", (run_id,))
            connection.execute("SELECT pgmq.send(%s, %s)", (queue, psycopg.types.json.Jsonb({"jobId": str(job_id)})))
    return len(rows)


def renew_run_lease(database_url: str, run_id: uuid.UUID, owner: str, fence: int) -> bool:
    with psycopg.connect(database_url, connect_timeout=2, options="-c statement_timeout=5000 -c lock_timeout=3000") as connection:
        if not connection.execute("SELECT id FROM app.jobs WHERE active_run_id=%s AND state='running' FOR UPDATE", (run_id,)).fetchone():
            return False
        return bool(connection.execute(
            "UPDATE app.job_runs SET lease_until=clock_timestamp() + interval '60 seconds' WHERE id=%s AND state='running' AND lease_owner=%s AND fence=%s AND lease_until > clock_timestamp() RETURNING id",
            (run_id, owner, fence),
        ).fetchone())


@contextmanager
def run_heartbeat(database_url: str, run_id: uuid.UUID, owner: str, fence: int, interval: float = 10):
    stop, lost = Event(), Event()

    def beat():
        while not stop.wait(interval):
            try:
                if renew_run_lease(database_url, run_id, owner, fence):
                    continue
            except psycopg.Error:
                logging.warning("lease renewal failed for run %s", run_id)
            lost.set()
            return

    thread = Thread(target=beat, name="run-heartbeat", daemon=True)
    thread.start()
    try:
        yield lost
    finally:
        stop.set()
        thread.join()


def process_one(database_url: str, owner: str, queue: str = "commands", *,
                video_service=None, video_request=None, estimated_cost_microusd=None, video_review=None,
                video_review_factory=None, photo_generate=None) -> bool:
    from admaker.db import RunLeaseLost, lock_run_lease
    from admaker.graph import WORKER_GRAPH_VERSION
    from admaker.provider_graph import PROVIDER_GRAPH_VERSION, ReviewedCandidate, run_provider_graph
    from admaker.photo_graph import PHOTO_GRAPH_VERSION, run_photo_graph
    from admaker.photo_provider import PhotoOutputRejected
    from admaker.veo import SubmissionUnknown, VeoRequest
    from admaker.campaign_worker import CampaignPackNeedsReview
    from admaker.media_drain import job_media_writer

    if photo_generate is not None and (not callable(photo_generate) or video_service is not None):
        raise ValueError("Choose one configured media provider")
    if (video_service is not None or photo_generate is not None) and (type(estimated_cost_microusd) is not int
            or (callable(video_review) + callable(video_review_factory)) != 1):
        raise ValueError("An explicit request, cost estimate and content reviewer are required")
    graph_version = PHOTO_GRAPH_VERSION if photo_generate is not None else PROVIDER_GRAPH_VERSION if video_service is not None else WORKER_GRAPH_VERSION

    with psycopg.connect(database_url) as connection:
        message = connection.execute("SELECT msg_id, message FROM pgmq.read(%s, vt => 60, qty => 1)", (queue,)).fetchone()
        if not message:
            return False
        job_id = message[1]["jobId"]
        run_id = uuid.uuid4()
        claimed = connection.execute("UPDATE app.jobs SET state='running' WHERE id=%s AND state='submitted' RETURNING id, source_asset_id, settings", (job_id,)).fetchone()
        if claimed:
            if claimed[2].get("videoProvider") is True and video_service is None:
                raise ValueError("Provider videos require the configured video worker")
            if claimed[2].get("photoProvider") is True and photo_generate is None:
                raise ValueError("Provider photos require the configured photo worker")
            if claimed[2].get("generationKind") == "campaign_pack" and video_service is None:
                raise ValueError("Campaign packs require the configured provider worker and reviewer")
            if video_service is not None and video_request is None:
                prepared = claimed[2].get("preparedVideoPrompt")
                if not prepared:
                    raise ValueError("This job has no prepared video request")
                video_request = VeoRequest(prepared)
            if video_service is not None and claimed[2].get("outputKind") == "photo":
                raise ValueError("Photo jobs cannot use the video provider")
            if photo_generate is not None and (claimed[2].get("outputKind") != "photo" or not claimed[2].get("preparedPhotoPrompt")):
                raise ValueError("Photo provider requires a prepared photo job")
            resumed = connection.execute("SELECT r.id, r.sequence, r.fence, a.id, a.reservation_id FROM app.job_runs r JOIN app.job_attempts a ON a.run_id=r.id JOIN app.jobs j ON j.active_run_id=r.id WHERE r.job_id=%s AND r.state='running' AND r.lease_until < clock_timestamp()", (job_id,)).fetchone()
            if resumed:
                run_id, sequence, old_fence, attempt_id, reservation_id = resumed
                fence = old_fence + 1
                connection.execute("UPDATE app.job_runs SET lease_owner=%s, lease_until=now() + interval '60 seconds', fence=%s,next_work_at=NULL WHERE id=%s AND fence=%s", (owner, fence, run_id, old_fence))
            else:
                sequence = connection.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM app.job_runs WHERE job_id=%s", (job_id,)).fetchone()[0]
                reservation = connection.execute("SELECT id FROM app.credit_reservations WHERE job_id=%s AND state='held' ORDER BY id LIMIT 1 FOR UPDATE", (job_id,)).fetchone()
                if not reservation:
                    raise RuntimeError(f"submitted job {job_id} has no held credit")
                fence = 1
                connection.execute("INSERT INTO app.job_runs (id, job_id, sequence, thread_id, state, lease_owner, lease_until, fence, graph_version) VALUES (%s,%s,%s,%s,'running',%s,now() + interval '60 seconds',%s,%s)", (run_id, job_id, sequence, f"{job_id}:{sequence}", owner, fence, graph_version))
                request_hash = hashlib.sha256(json.dumps({"asset": str(claimed[1]), "settings": claimed[2]}, sort_keys=True).encode()).hexdigest()
                attempt_id = uuid.uuid4()
                reservation_id = reservation[0]
                connection.execute("INSERT INTO app.job_attempts (id, run_id, reservation_id, sequence, state, request_hash) VALUES (%s,%s,%s,%s,'running',%s)", (attempt_id, run_id, reservation_id, sequence, request_hash))
            connection.execute("UPDATE app.jobs SET active_run_id=%s WHERE id=%s", (run_id, job_id))
        if not claimed:
            connection.execute("SELECT pgmq.archive(%s, %s)", (queue, message[0]))
            return True
        source = connection.execute("SELECT storage_key FROM app.assets WHERE asset_key=%s", (claimed[1],)).fetchone()[0]
        platforms = claimed[2].get("renderPlatforms", claimed[2].get("platforms", ["tiktok"]))
    lost = Event()
    try:
        from admaker.run_compatibility import pause_incompatible_run
        if pause_incompatible_run(database_url, run_id, owner, fence,
                                  graph_version, queue, message[0]):
            return True
        with job_media_writer(database_url, job_id), run_heartbeat(database_url, run_id, owner, fence) as lost:
            if (video_service is not None or photo_generate is not None) and video_review_factory is not None:
                video_review = video_review_factory(database_url, job_id, run_id)
                if not callable(video_review):
                    raise MediaReviewPending("Configured reviewer is unavailable")
            from admaker.cloud_objects import stage_job_source, publish_job_outputs
            try:
                stage_job_source(database_url, job_id, os.environ.get("LOCAL_ASSET_ROOT", ".local-assets"))
            except (OSError, ValueError):
                raise CloudPublicationPending("Private source staging is unconfirmed") from None
            if claimed[2].get("structuredPlanning") is True and (video_service is not None or photo_generate is not None):
                from admaker.creative_planning import plan_product
                from dataclasses import replace
                plan = plan_product(database_url, run_id, owner, fence,
                    Path(os.environ.get("LOCAL_ASSET_ROOT", ".local-assets")), claimed[2])
                prompt_key = "preparedPhotoPrompt" if photo_generate is not None else "preparedVideoPrompt"
                planned_prompt = claimed[2][prompt_key] + " Product summary: " + plan["product_summary"] + " Creative adaptation: " + plan["creative_direction"]
                if len(planned_prompt) > 4000:
                    raise MediaReviewPending("Planned prompt exceeds the supported limit")
                claimed[2][prompt_key] = planned_prompt
                if video_service is not None:
                    video_request = replace(video_request, prompt=planned_prompt)
            if photo_generate is not None:
                exports = run_photo_graph(database_url, run_id, attempt_id, owner, fence, claimed[2], platforms,
                    estimated_cost_microusd, video_review, photo_generate)
            elif video_service is None:
                exports = run_worker_graph(database_url, run_id, owner, fence, source, claimed[2], f"{job_id}/{run_id}/{fence}", platforms)
            else:
                if video_review_factory is not None:
                    from admaker.input_review import require_reviewed_input
                    require_reviewed_input(database_url, run_id, owner, fence,
                        Path(os.environ.get("LOCAL_ASSET_ROOT", ".local-assets")), source, video_request.prompt, video_review)
                exports = run_provider_graph(database_url, run_id, attempt_id, owner, fence,
                    video_request, estimated_cost_microusd, video_service, claimed[2], f"{job_id}/{run_id}/{fence}", platforms, video_review)
                if exports is not None and claimed[2].get("generationKind") == "campaign_pack":
                    from admaker.campaign_worker import finish_campaign_pack
                    exports = finish_campaign_pack(database_url, run_id, owner, fence, source, claimed[2], exports, video_review)
            if exports is not None and os.environ.get("PUBLISH_PRIVATE_OUTPUTS") == "true":
                publish_job_outputs(database_url, job_id, os.environ.get("LOCAL_ASSET_ROOT", ".local-assets"),
                    exports.exports if isinstance(exports, ReviewedCandidate) else exports)
    except (ProviderCapacityBusy, CloudPublicationPending, ReviewFileProcessing):
        try:
            with psycopg.connect(database_url) as connection:
                lock_run_lease(connection, run_id, owner, fence)
                connection.execute("UPDATE app.job_runs SET lease_until=clock_timestamp()-interval '1 second',next_work_at=clock_timestamp()+interval '10 seconds' WHERE id=%s", (run_id,))
                connection.execute("SELECT pgmq.archive(%s,%s)", (queue, message[0]))
        except RunLeaseLost:
            pass
        return True
    except RunLeaseLost:
        return True
    except (CampaignPackNeedsReview, MediaReviewPending) as error:
        with psycopg.connect(database_url) as connection:
            lock_run_lease(connection, run_id, owner, fence)
            connection.execute("UPDATE app.job_runs SET state='review_required',lease_until=NULL,next_work_at=NULL WHERE id=%s", (run_id,))
            code = "media_review_pending" if isinstance(error, MediaReviewPending) else "campaign_pack_incomplete"
            failure = {"code": code}
            if code == "campaign_pack_incomplete":
                failure["message"] = "Some campaign outputs could not be prepared. Your reserved credits remain held; contact support."
            connection.execute("UPDATE app.jobs SET state='failed',result=result || %s WHERE id=%s", (psycopg.types.json.Jsonb({"failure": failure}), job_id))
            connection.execute("SELECT pgmq.archive(%s,%s)", (queue, message[0]))
        return True
    except SubmissionUnknown:
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            lock_run_lease(cursor, run_id, owner, fence)
            cursor.execute("INSERT INTO app.submission_reviews(attempt_id) VALUES (%s) ON CONFLICT (attempt_id) DO NOTHING", (attempt_id,))
            cursor.execute("UPDATE app.job_runs SET state='review_required',lease_until=NULL,next_work_at=NULL WHERE id=%s", (run_id,))
            cursor.execute("UPDATE app.jobs SET state='failed',result=result || %s WHERE id=%s", (psycopg.types.json.Jsonb({"failure": {"code": "submission_unknown", "message": "Generation needs review. Your reserved credits remain held; contact support."}}), job_id))
            cursor.execute("SELECT pgmq.archive(%s,%s)", (queue, message[0]))
        return True
    except (OSError, subprocess.SubprocessError, PhotoOutputRejected) as error:
        if lost.is_set():
            return True
        with psycopg.connect(database_url) as connection:
            connection.execute("SELECT id FROM app.accounts WHERE id=(SELECT account_id FROM app.credit_reservations WHERE id=%s) FOR UPDATE", (reservation_id,))
            if not connection.execute("SELECT id FROM app.jobs WHERE id=%s AND active_run_id=%s AND state='running' FOR UPDATE", (job_id, run_id)).fetchone():
                return True
            fenced = connection.execute("UPDATE app.job_runs SET state='failed', lease_until=NULL WHERE id=%s AND fence=%s AND lease_owner=%s AND state='running' AND lease_until > clock_timestamp() RETURNING id", (run_id, fence, owner)).fetchone()
            if not fenced:
                return True
            connection.execute("UPDATE app.job_attempts SET state='failed', completed_at=now() WHERE id=%s", (attempt_id,))
            connection.execute("UPDATE app.jobs SET state='failed' WHERE id=%s AND active_run_id=%s", (job_id, run_id))
            connection.execute("UPDATE app.credit_reservations SET state='released' WHERE id=%s AND state='held'", (reservation_id,))
            connection.execute("SELECT pgmq.archive(%s, %s)", (queue, message[0]))
        logging.error(json.dumps({"event": "generation_failed", "jobId": str(job_id),
            "runId": str(run_id), "errorType": type(error).__name__, "reservation": "released"}))
        return True
    if lost.is_set():
        return True
    validation = exports.validation if isinstance(exports, ReviewedCandidate) else None
    if validation is not None:
        exports = exports.exports
    if validation is not None and not validation["qualityPassed"]:
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            lock_run_lease(cursor, run_id, owner, fence)
            cursor.execute("UPDATE app.job_runs SET state='awaiting_user_decision',lease_until=NULL,next_work_at=NULL WHERE id=%s", (run_id,))
            result = cursor.execute("SELECT result FROM app.jobs WHERE id=%s", (job_id,)).fetchone()[0]
            result.setdefault("runs", {})[str(sequence)] = {"exports": exports}
            result.update(exports=exports, candidateValidation=validation)
            cursor.execute("UPDATE app.jobs SET state='awaiting_user_decision',result=%s WHERE id=%s", (psycopg.types.json.Jsonb(result), job_id))
            cursor.execute("SELECT pgmq.archive(%s,%s)", (queue, message[0]))
        return True
    if exports is None:
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            lock_run_lease(cursor, run_id, owner, fence)
            cursor.execute("UPDATE app.job_runs SET lease_until=clock_timestamp()-interval '1 second',next_work_at=clock_timestamp()+interval '10 seconds' WHERE id=%s", (run_id,))
            cursor.execute("SELECT pgmq.archive(%s,%s)", (queue, message[0]))
        return True
    with psycopg.connect(database_url) as connection:
        connection.execute("SELECT id FROM app.accounts WHERE id=(SELECT account_id FROM app.credit_reservations WHERE id=%s) FOR UPDATE", (reservation_id,))
        if not connection.execute("SELECT id FROM app.jobs WHERE id=%s AND active_run_id=%s AND state='running' FOR UPDATE", (job_id, run_id)).fetchone():
            return True
        fenced = connection.execute("UPDATE app.job_runs SET state='delivered', lease_until=NULL WHERE id=%s AND fence=%s AND lease_owner=%s AND state='running' AND lease_until > clock_timestamp() RETURNING id", (run_id, fence, owner)).fetchone()
        if not fenced:
            return True
        connection.execute("UPDATE app.job_attempts SET state='delivered', completed_at=now() WHERE id=%s", (attempt_id,))
        result = connection.execute("SELECT result FROM app.jobs WHERE id=%s", (job_id,)).fetchone()[0]
        result.setdefault("runs", {})[str(sequence)] = {"exports": exports}
        result["exports"] = exports
        if validation is not None:
            result["candidateValidation"] = validation
        else:
            result.pop("candidateValidation", None)
        connection.execute("UPDATE app.jobs SET state='delivered', result=%s WHERE id=%s AND active_run_id=%s", (psycopg.types.json.Jsonb(result), job_id, run_id))
        settlement = connection.execute("UPDATE app.credit_reservations SET state='consumed' WHERE id=%s AND state='held' RETURNING account_id,amount", (reservation_id,)).fetchone()
        if settlement:
            connection.execute("INSERT INTO app.credit_ledger (account_id, delta, event_key, reason, reservation_id) VALUES (%s,%s,%s,'delivery',%s) ON CONFLICT (event_key) DO NOTHING", (settlement[0], -settlement[1], f"consume:{job_id}:{sequence}", reservation_id))
        connection.execute("SELECT pgmq.archive(%s, %s)", (queue, message[0]))
    return True


def main() -> None:
    from admaker.billing import process_pending_billing

    database_url = os.environ.get("DATABASE_URL")
    if not database_ready(database_url):
        raise SystemExit("DATABASE_URL is unavailable")
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    owner = f"{socket.gethostname()}:{os.getpid()}"
    try:
        while True:
            try:
                process_pending_billing(database_url)
            except psycopg.Error:
                logging.warning("billing reconciliation will retry on the next worker pass")
            if os.environ.get("RECOVER_EXPIRED_RUNS", "true").lower() == "true":
                recover_expired_runs(database_url)
            if not process_one(database_url, owner):
                time.sleep(1)
    except KeyboardInterrupt:
        return
    except Exception:
        raise SystemExit("Worker stopped; check server configuration and restricted operational records.") from None
