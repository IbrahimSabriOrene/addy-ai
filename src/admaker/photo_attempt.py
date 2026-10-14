"""One reserved synchronous photo call, with fenced output and no blind retry."""
import hashlib
import json
import os
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from admaker.consent import require_ai_consent
from admaker.db import lock_run_lease
from admaker.input_review import require_reviewed_input
from admaker.media_drain import job_media_writer
from admaker.photo_provider import PHOTO_INSTRUCTIONS, PHOTO_MODEL, PhotoOutputRejected, PhotoRequest, generate_product_photo
from admaker.provider_budget import reserve_provider_budget
from admaker.veo import SubmissionInProgress, SubmissionUnknown, image_mime_type, read_video_image


def generate_photo_attempt(database_url, attempt_id, owner, fence, prompt, aspect_ratio, estimate, reviewer, *, generate=generate_product_photo):
    if (not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 4000 or len(prompt) > 4000
            or aspect_ratio not in {"1:1", "9:16"} or type(estimate) is not int or not 0 < estimate <= 1_000_000_000
            or not callable(reviewer)):
        raise ValueError("Explicit photo direction, format, estimate and reviewer are required")
    with psycopg.connect(database_url) as connection:
        row = connection.execute("""SELECT r.id,j.id,j.owner_id,s.owner_id,s.storage_key,s.verification_state,j.settings
            FROM app.job_attempts a JOIN app.job_runs r ON r.id=a.run_id JOIN app.jobs j ON j.id=r.job_id
            JOIN app.assets s ON s.asset_key=j.source_asset_id WHERE a.id=%s""", (attempt_id,)).fetchone()
    if not row or row[2] != row[3] or row[5] != "verified" or row[6].get("outputKind") != "photo":
        raise ValueError("An owned verified photo job is required")
    run, job, account, _, key, _, _ = row
    with job_media_writer(database_url, job):
        root = Path(os.environ.get("LOCAL_ASSET_ROOT", ".local-assets")).resolve()
        source = (root / key).resolve()
        if not source.is_relative_to(root):
            raise ValueError("Photo source escapes private storage")
        data = read_video_image(source)
        snapshot = {"model": PHOTO_MODEL, "instructions": PHOTO_INSTRUCTIONS, "prompt": prompt,
            "aspectRatio": aspect_ratio, "imageSize": "1K", "estimatedCostMicrousd": estimate,
            "sourceKey": key, "sourceSha256": hashlib.sha256(data).hexdigest()}
        digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        require_reviewed_input(database_url, run, owner, fence, root, key, prompt, reviewer)
        unknown = False
        with psycopg.connect(database_url) as connection:
            lock_run_lease(connection, run, owner, fence)
            state, prior_fence, prior_hash, attempt_state, held, reservation_owner = connection.execute("""
                SELECT a.provider_state,a.provider_fence,a.provider_request_hash,a.state,c.state,c.account_id
                FROM app.job_attempts a JOIN app.credit_reservations c ON c.id=a.reservation_id
                WHERE a.id=%s FOR UPDATE OF a,c""", (attempt_id,)).fetchone()
            if attempt_state != "running" or held != "held" or reservation_owner != account:
                raise ValueError("An active owned photo reservation is required")
            if prior_hash is not None and prior_hash != digest:
                raise ValueError("Photo request changed from its immutable snapshot")
            saved = connection.execute("SELECT data,mime_type,checksum FROM app.photo_attempt_outputs WHERE attempt_id=%s", (attempt_id,)).fetchone()
            if saved:
                if state != "ready" or hashlib.sha256(saved[0]).hexdigest() != saved[2] or image_mime_type(saved[0]) != saved[1]:
                    raise ValueError("Saved photo output failed verification")
                return saved[0]
            if state == "submitting" and prior_fence == fence:
                raise SubmissionInProgress()
            if state in {"submitting", "submission_unknown"}:
                connection.execute("UPDATE app.job_attempts SET provider_state='submission_unknown',provider_error='photo_submission_unknown' WHERE id=%s", (attempt_id,))
                unknown = True
            elif state is not None:
                raise PhotoOutputRejected("Photo attempt cannot be submitted again")
            else:
                require_ai_consent(str(account))
                reserve_provider_budget(connection, attempt_id, estimate, media_kind="photo")
                connection.execute("""UPDATE app.job_attempts SET provider_state='submitting',provider_fence=%s,
                    provider_request=%s,provider_request_hash=%s,estimated_cost_microusd=%s WHERE id=%s""",
                    (fence, Jsonb(snapshot), digest, estimate, attempt_id))
        if unknown:
            raise SubmissionUnknown("Photo generation outcome is unconfirmed")
        try:
            require_ai_consent(str(account))
            output = generate(PhotoRequest(prompt, data, aspect_ratio), account_id=str(account))
            try:
                mime = image_mime_type(output)
            except (ValueError, OSError):
                raise PhotoOutputRejected("Generated photo failed validation") from None
        except PhotoOutputRejected:
            with psycopg.connect(database_url) as connection:
                lock_run_lease(connection, run, owner, fence)
                connection.execute("UPDATE app.job_attempts SET provider_state='failed',provider_error='photo_output_rejected' WHERE id=%s", (attempt_id,))
            raise
        except Exception:
            with psycopg.connect(database_url) as connection:
                lock_run_lease(connection, run, owner, fence)
                connection.execute("UPDATE app.job_attempts SET provider_state='submission_unknown',provider_error='photo_submission_unknown' WHERE id=%s", (attempt_id,))
            raise SubmissionUnknown("Photo generation outcome is unconfirmed") from None
        with psycopg.connect(database_url) as connection:
            lock_run_lease(connection, run, owner, fence)
            # ponytail: at most 10 MiB per photo in PostgreSQL gives one atomic output
            # receipt; replace with verified object receipts if storage throughput requires it.
            connection.execute("INSERT INTO app.photo_attempt_outputs(attempt_id,data,mime_type,checksum) VALUES (%s,%s,%s,%s)",
                (attempt_id, output, mime, hashlib.sha256(output).hexdigest()))
            connection.execute("UPDATE app.job_attempts SET provider_state='ready',provider_error=NULL WHERE id=%s", (attempt_id,))
        return output
