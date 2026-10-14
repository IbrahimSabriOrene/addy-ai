"""Direct Veo adapter. Real provider work is explicitly opt-in."""

from __future__ import annotations

import os
import io
import re
import tempfile
import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
import psycopg

FAST_MODEL = "veo-3.1-fast-generate-preview"


def validate_operation_name(name: str) -> str:
    if not isinstance(name, str) or not re.fullmatch(r"(?:models/[a-zA-Z0-9._-]+/)?operations/[a-zA-Z0-9_-]{1,200}", name):
        raise ValueError("Invalid provider operation name")
    return name


@dataclass(frozen=True)
class VeoRequest:
    prompt: str
    image_path: str | None = None
    model: str | None = None
    image_bytes: bytes | None = None


def image_mime_type(data: bytes) -> str:
    from PIL import Image

    if not isinstance(data, bytes) or len(data) > 10 * 1024 * 1024:
        raise ValueError("Product image is too large or invalid")
    with Image.open(io.BytesIO(data)) as decoded:
        if decoded.format not in {"JPEG", "PNG", "WEBP"} or decoded.width * decoded.height > 25_000_000:
            raise ValueError("Unsupported product image")
        mime_type = Image.MIME[decoded.format]
        decoded.verify()
    return mime_type


def read_video_image(path: str | Path) -> bytes:
    with Path(path).open("rb") as source:
        data = source.read(10 * 1024 * 1024 + 1)
    image_mime_type(data)
    return data


class SubmissionUnknown(Exception):
    """Keep the reservation held; no automatic resubmission is permitted."""


class SubmissionInProgress(Exception):
    """The same lease has already started the provider request."""


def submit_video_attempt(database_url: str, attempt_id: uuid.UUID, owner: str, fence: int,
                         request: VeoRequest, estimated_cost_microusd: int, service) -> str:
    from admaker.consent import require_ai_consent
    from admaker.db import lock_run_lease

    if type(estimated_cost_microusd) is not int or not 0 <= estimated_cost_microusd <= 1_000_000_000:
        raise ValueError("A bounded integer provider cost estimate is required")
    if (request.model or FAST_MODEL) != FAST_MODEL or not isinstance(request.prompt, str) or not request.prompt.strip() or len(request.prompt) > 4000:
        raise ValueError("Invalid video request")
    if request.image_bytes is not None:
        raise ValueError("Reserved attempts use the job's verified asset, not caller-supplied bytes")
    snapshot = {"prompt": request.prompt, "model": request.model or FAST_MODEL, "estimatedCostMicrousd": estimated_cost_microusd,
                "durationSeconds": 8, "resolution": "1080p", "aspectRatio": "9:16"}
    unknown = False
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        identity = cursor.execute("SELECT a.run_id,j.owner_id,s.asset_key,s.storage_key,s.owner_id,s.verification_state FROM app.job_attempts a JOIN app.job_runs r ON r.id=a.run_id JOIN app.jobs j ON j.id=r.job_id JOIN app.assets s ON s.asset_key=j.source_asset_id WHERE a.id=%s", (attempt_id,)).fetchone()
        if not identity:
            raise ValueError("Unknown video attempt")
        run_id, account_id, asset_id, storage_key, asset_owner, verification = identity
        lock_run_lease(cursor, run_id, owner, fence)
        if asset_owner != account_id or verification != "verified":
            raise ValueError("Job source is not an owned verified image")
        root = Path(os.environ.get("LOCAL_ASSET_ROOT", ".local-assets")).resolve()
        source = (root / storage_key).resolve()
        if not source.is_relative_to(root) or (request.image_path is not None and Path(request.image_path).resolve() != source):
            raise ValueError("Video image does not match the job's private asset")
        snapshot["sourceAssetId"] = str(asset_id)
        prior, prior_fence, saved_snapshot, operation, state, reservation_state, reservation_owner = cursor.execute(
            "SELECT a.provider_state,a.provider_fence,a.provider_request,a.operation_name,a.state,c.state,c.account_id "
            "FROM app.job_attempts a JOIN app.credit_reservations c ON c.id=a.reservation_id WHERE a.id=%s FOR UPDATE OF a,c", (attempt_id,),
        ).fetchone()
        if state != "running" or reservation_state != "held" or reservation_owner != account_id:
            raise ValueError("Attempt has no active owned reservation")
        if saved_snapshot is not None and any(saved_snapshot.get(key) != value for key, value in snapshot.items()):
            raise ValueError("Provider request does not match its immutable snapshot")
        if operation:
            return operation
        if prior == "submitting" and prior_fence == fence:
            raise SubmissionInProgress()
        if prior in {"submitting", "submission_unknown"}:
            cursor.execute("UPDATE app.job_attempts SET provider_state='submission_unknown',provider_error='submission_unknown' WHERE id=%s", (attempt_id,))
            unknown = True
        elif prior is not None:
            raise ValueError("Attempt is not eligible for submission")
        else:
            require_ai_consent(str(account_id))
            data = read_video_image(source)
            snapshot.update(imageSha256=hashlib.sha256(data).hexdigest(), imageMimeType=image_mime_type(data), imageSizeBytes=len(data))
            request_hash = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            request = VeoRequest(request.prompt, model=snapshot["model"], image_bytes=data)
            lock_run_lease(cursor, run_id, owner, fence)
            from admaker.provider_budget import reserve_provider_budget
            reserve_provider_budget(cursor, attempt_id, estimated_cost_microusd)
            cursor.execute(
                "UPDATE app.job_attempts SET provider_state='submitting',provider_fence=%s,provider_request=%s,provider_request_hash=%s,estimated_cost_microusd=%s WHERE id=%s",
                (fence, psycopg.types.json.Jsonb(snapshot), request_hash, estimated_cost_microusd, attempt_id),
            )
    if unknown:
        raise SubmissionUnknown()
    try:
        operation = validate_operation_name(service.submit(request, account_id=str(account_id)))
    except Exception:
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            lock_run_lease(cursor, run_id, owner, fence)
            cursor.execute("UPDATE app.job_attempts SET provider_state='submission_unknown',provider_error='submission_unknown' WHERE id=%s", (attempt_id,))
        raise SubmissionUnknown() from None
    # A crash here leaves 'submitting'. A replacement lease must not issue another POST.
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        lock_run_lease(cursor, run_id, owner, fence)
        cursor.execute("UPDATE app.job_attempts SET provider_state='submitted',operation_name=%s,next_poll_at=clock_timestamp(),provider_error=NULL WHERE id=%s", (operation, attempt_id))
    return operation


def poll_video_attempt(database_url: str, attempt_id: uuid.UUID, owner: str, fence: int, service):
    """One scheduled GET. Timeouts retain the saved operation and held credit."""
    from admaker.db import lock_run_lease

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        row = cursor.execute("SELECT run_id FROM app.job_attempts WHERE id=%s", (attempt_id,)).fetchone()
        if not row:
            raise ValueError("Unknown video attempt")
        run_id = row[0]
        lock_run_lease(cursor, run_id, owner, fence)
        state, operation, due, expired = cursor.execute("SELECT provider_state,operation_name,next_poll_at<=clock_timestamp(),created_at + interval '24 hours' <= clock_timestamp() FROM app.job_attempts WHERE id=%s FOR UPDATE", (attempt_id,)).fetchone()
        if state not in {"submitted", "ready"} or not operation:
            raise ValueError("Attempt has no pollable operation")
        if expired:
            cursor.execute("UPDATE app.job_attempts SET provider_error='wait_deadline_exceeded',next_poll_at=NULL WHERE id=%s", (attempt_id,))
        elif not due:
            return None
        else:
            cursor.execute("UPDATE app.job_attempts SET next_poll_at=clock_timestamp()+interval '10 seconds' WHERE id=%s", (attempt_id,))
    if expired:
        # Outcome remains uncertain even when the operation name is known.
        raise SubmissionUnknown("Provider output wait exceeded the 24-hour deadline")
    result = service.poll(operation)
    response = result.response
    error = None
    if result.done:
        if result.error:
            error = "provider_failed"
        elif response and (response.rai_media_filtered_count or response.rai_media_filtered_reasons):
            error = "provider_blocked"
        elif not response or not response.generated_videos or len(response.generated_videos) != 1 or not response.generated_videos[0].video:
            error = "provider_empty_output"
    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        lock_run_lease(cursor, run_id, owner, fence)
        cursor.execute("UPDATE app.job_attempts SET provider_state=%s,provider_error=%s WHERE id=%s",
                       ("failed" if error else "ready" if result.done else "submitted", error, attempt_id))
    return result if result.done else None


class VeoService:
    def __init__(self) -> None:
        if os.environ.get("ENABLE_REAL_VEO") != "true":
            raise RuntimeError("real Veo is disabled; set ENABLE_REAL_VEO=true after approving a test budget")
        from google import genai
        from google.genai import types

        self.model = os.environ.get("VEO_MODEL", FAST_MODEL)
        if self.model != FAST_MODEL:
            raise ValueError("Only the configured Veo Fast model is supported")
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], vertexai=False,
                                   http_options=types.HttpOptions(timeout=60_000, retry_options=types.HttpRetryOptions(attempts=1)))

    def submit(self, request: VeoRequest, *, account_id: str) -> str:
        from admaker.consent import require_ai_consent

        require_ai_consent(account_id)
        from google.genai import types

        model = request.model or self.model
        if model != FAST_MODEL or model != self.model:
            raise ValueError("Requested model does not match the configured Fast model")
        if not isinstance(request.prompt, str) or not request.prompt.strip() or len(request.prompt) > 4000:
            raise ValueError("Video prompt must contain 1 to 4000 characters")
        image = None
        if request.image_path and request.image_bytes is not None:
            raise ValueError("Choose one image source")
        data = read_video_image(request.image_path) if request.image_path else request.image_bytes
        if data is not None:
            image = types.Image(image_bytes=data, mime_type=image_mime_type(data))
        operation = self.client.models.generate_videos(
            model=model,
            source=types.GenerateVideosSource(prompt=request.prompt, image=image),
            config=types.GenerateVideosConfig(aspect_ratio="9:16", resolution="1080p", duration_seconds=8),
        )
        # Invalid/missing names after submission are uncertain outcomes, not retry permission.
        return validate_operation_name(operation.name)

    def poll(self, operation_name: str):
        from google.genai import types

        return self.client.operations.get(types.GenerateVideosOperation(name=validate_operation_name(operation_name)))

    def download(self, operation, destination: str) -> None:
        response = operation.response
        if not operation.done or operation.error or not response:
            raise ValueError("Provider operation has no completed output")
        if response.rai_media_filtered_count or response.rai_media_filtered_reasons:
            raise ValueError("Provider blocked the output")
        if not response.generated_videos or len(response.generated_videos) != 1 or not response.generated_videos[0].video:
            raise ValueError("Provider returned no usable video")
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Keep a failed/partial download from replacing an existing complete artifact.
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as output:
            partial = Path(output.name)
        try:
            self.client.files.download(file=response.generated_videos[0].video, destination=partial)
            if partial.stat().st_size == 0:
                raise ValueError("Provider download was empty")
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
