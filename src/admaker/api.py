"""HTTP process entry point. Product routes begin in milestone M1."""

from __future__ import annotations

import hashlib
import base64
import io
import json
import os
import re
import uuid
import logging
import hmac
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from PIL import Image, ImageOps, ImageCms
import psycopg
from pydantic import BaseModel, Field
from typing import Literal

from admaker.auth import Subject, authenticated_subject
from admaker.db import database_ready
from admaker.storage import LocalPrivateStorage
from admaker.campaign_failure import campaign_failure
from admaker.retry_pricing import retry_terms
from admaker.media_drain import lock_media_writer, AccountDeletionRequested

app = FastAPI(title="Addy AI API", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)
from admaker.campaign_routes import router as campaign_layout_router
app.include_router(campaign_layout_router)
from admaker.account_deletion import router as account_deletion_router
app.include_router(account_deletion_router)
from admaker.eligibility import router as eligibility_router
app.include_router(eligibility_router)
from admaker.brand import router as brand_router
app.include_router(brand_router)
from admaker.growth import router as growth_router
app.include_router(growth_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.environ.get("WEB_ORIGINS", "").split(",") if origin.strip()],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
ALLOWED_IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
STYLE_CANDIDATES = [
    {"id": "pedestal_spin", "name": "Pedestal spin", "oneLiner": "A clean product turntable.", "captionPreview": "Made for the moment."},
    {"id": "lifestyle_zoom", "name": "Lifestyle zoom", "oneLiner": "A close-up in a natural setting.", "captionPreview": "Small detail, big impact."},
]
PUBLIC_PLATFORMS = {"tiktok", "reels", "feed", "stories"}


@app.exception_handler(Exception)
async def unexpected_error(_: Request, error: Exception) -> JSONResponse:
    trace_id = str(uuid.uuid4())
    logging.error(json.dumps({"event": "api_request_failed", "traceId": trace_id,
                              "errorType": type(error).__name__}))
    return JSONResponse(status_code=500, headers={"Cache-Control": "no-store"}, content={
        "code": "request_failed", "message": "The request could not be completed.", "traceId": trace_id,
    })


@app.exception_handler(HTTPException)
async def api_error(_: Request, error: HTTPException) -> JSONResponse:
    message = str(error.detail)
    code = re.sub(r"[^a-z0-9]+", "_", message.lower()).strip("_") or "request_failed"
    return JSONResponse(status_code=error.status_code, headers=error.headers, content={"code": code, "message": message, "traceId": str(uuid.uuid4())})


@app.middleware("http")
async def safe_request_errors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as error:
        return await unexpected_error(request, error)


@app.exception_handler(psycopg.errors.CheckViolation)
async def database_constraint_error(_: Request, error: psycopg.errors.CheckViolation) -> JSONResponse:
    deleted = error.diag.constraint_name == "account_deletion_requested"
    return JSONResponse(status_code=410 if deleted else 500, content={
        "code": "account_deletion_requested" if deleted else "request_failed",
        "message": "Account deletion has been requested" if deleted else "The request could not be completed.",
        "traceId": str(uuid.uuid4()),
    })


@app.exception_handler(AccountDeletionRequested)
async def media_deletion_error(_: Request, error: AccountDeletionRequested) -> JSONResponse:
    return JSONResponse(status_code=410, content={"code": "account_deletion_requested", "message": "Account deletion has been requested", "traceId": str(uuid.uuid4())})


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
    fields = sorted({str(item["loc"][-1]) for item in error.errors() if item.get("loc")})
    return JSONResponse(status_code=422, content={
        "code": "invalid_request",
        "message": "Please check the request fields.",
        "fields": fields,
        "traceId": str(uuid.uuid4()),
    })


class PresignRequest(BaseModel):
    mime_type: str = Field(alias="mimeType")
    size_bytes: int = Field(alias="sizeBytes", gt=0, le=MAX_IMAGE_BYTES)


class CompleteRequest(BaseModel):
    asset_key: uuid.UUID = Field(alias="assetKey")


class JobRequest(BaseModel):
    asset_key: uuid.UUID = Field(alias="assetKey")
    platforms: list[str] = Field(min_length=1)
    fast_mode: bool = Field(alias="fastMode")
    quality: str = "fast"
    template_id: str | None = Field(default=None, alias="templateId", max_length=100)
    template_version: int | None = Field(default=None, alias="templateVersion", ge=1)
    output_kind: str = Field(default="video", alias="outputKind")
    direction: str = Field(default="", max_length=500)


class StyleChoiceRequest(BaseModel):
    expected_version: int = Field(alias="expectedVersion", ge=1, strict=True)
    preset_id: str | None = Field(default=None, alias="presetId")
    direction: str | None = Field(default=None, max_length=500)


class DecisionRequest(BaseModel):
    expected_version: int = Field(alias="expectedVersion", ge=1, strict=True)
    action: str = Field(pattern="^(accept|spend_more|abort)$")
    confirmed_credits: int | None = Field(default=None, alias="confirmedCredits", ge=1, le=10000, strict=True)


class RegenRequest(BaseModel):
    expected_version: int = Field(alias="expectedVersion", ge=1, strict=True)
    confirmed_credits: int | None = Field(default=None, alias="confirmedCredits", ge=1, le=10000, strict=True)


def _job_for_command(connection, job_id, account_id, version, state):
    row = connection.execute("SELECT settings,result,version,state FROM app.jobs WHERE id=%s AND owner_id=%s FOR UPDATE", (job_id, account_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    if row[2] != version or row[3] != state:
        raise HTTPException(status_code=409, detail="generation changed; reload before deciding")
    return row


def _connection():
    try:
        return psycopg.connect(os.environ["DATABASE_URL"])
    except (KeyError, psycopg.Error):
        raise HTTPException(status_code=503, detail="database unavailable") from None


def _storage() -> LocalPrivateStorage:
    return LocalPrivateStorage(os.environ.get("LOCAL_ASSET_ROOT", ".local-assets"))


def _job_cursor(created_at, job_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{created_at.isoformat()}|{job_id}".encode()).decode().rstrip("=")


def _parse_job_cursor(cursor: str) -> tuple[str, uuid.UUID]:
    try:
        if len(cursor) > 256:
            raise ValueError("cursor too long")
        created_at, job_id = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True).decode().split("|", 1)
        timestamp = datetime.fromisoformat(created_at)
        if timestamp.tzinfo is None:
            raise ValueError("cursor must include a timezone")
        return timestamp.isoformat(), uuid.UUID(job_id)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=422, detail="invalid cursor") from None


def _account(subject: Subject) -> None:
    with _connection() as connection:
        connection.execute(
            "INSERT INTO app.accounts (id, email) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email",
            (subject.id, subject.email),
        )
        if os.environ.get("DEV_SEED_CREDITS"):
            connection.execute("INSERT INTO app.credit_ledger (account_id, delta, event_key, reason) VALUES (%s, %s, %s, 'development_seed') ON CONFLICT (event_key) DO NOTHING", (subject.id, int(os.environ["DEV_SEED_CREDITS"]), f"seed:{subject.id}"))


def _verify_image(data: bytes, mime_type: str) -> bytes:
    if len(data) > MAX_IMAGE_BYTES or mime_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=422, detail="unsupported image")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if Image.MIME.get(image.format) != mime_type:
                raise HTTPException(status_code=422, detail="image type does not match bytes")
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise HTTPException(status_code=422, detail="image is too large")
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            profile = image.info.get("icc_profile")
            if profile:
                alpha = image.convert("RGBA").getchannel("A") if "A" in image.getbands() or "transparency" in image.info else None
                image = ImageCms.profileToProfile(
                    image if image.mode in {"RGB", "CMYK", "LAB", "L"} else image.convert("RGB"),
                    ImageCms.ImageCmsProfile(io.BytesIO(profile)), ImageCms.createProfile("sRGB"), outputMode="RGB",
                )
                if alpha is not None:
                    image.putalpha(alpha)
            image.info.clear()
            output = io.BytesIO()
            image.save(output, format={"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}[mime_type])
            return output.getvalue()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=422, detail="invalid image bytes") from None


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def ready() -> dict[str, str]:
    if not database_ready(os.environ.get("DATABASE_URL")):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="database unavailable")
    return {"status": "ok"}


@app.get("/v1/account")
def account(subject: Subject = Depends(authenticated_subject)) -> dict[str, str]:
    _account(subject)
    name = subject.email.split("@", 1)[0]
    return {"name": name, "email": subject.email, "initial": name[:1].upper()}


@app.get("/v1/credits")
def credits(subject: Subject = Depends(authenticated_subject)) -> dict:
    _account(subject)
    with _connection() as connection:
        balance, held = connection.execute(
            "SELECT COALESCE(SUM(delta), 0), COALESCE((SELECT SUM(amount) FROM app.credit_reservations WHERE account_id=%s AND state='held'), 0) FROM app.credit_ledger WHERE account_id=%s",
            (subject.id, subject.id),
        ).fetchone()
    return {"balance": balance - held, "held": held, "pack": None}


@app.get("/v1/credits/packs")
def list_credit_packs(response: Response, subject: Subject = Depends(authenticated_subject)) -> dict:
    from admaker.billing import credit_packs

    response.headers["Cache-Control"] = "private, no-store"
    if not os.environ.get("REVENUECAT_APP_ID") or not os.environ.get("REVENUECAT_AUTHORIZATION") or os.environ.get("REVENUECAT_ENVIRONMENT", "SANDBOX") not in {"SANDBOX", "PRODUCTION"}:
        raise HTTPException(status_code=503, detail="credit packs unavailable")
    try:
        packs = credit_packs()
    except ValueError:
        raise HTTPException(status_code=503, detail="credit packs unavailable") from None
    return {"items": [{"productId": product, "credits": amount} for product, amount in sorted(packs.items())]}


@app.get("/v1/credits/purchases")
def recent_credit_purchases(response: Response, subject: Subject = Depends(authenticated_subject)) -> dict:
    response.headers["Cache-Control"] = "private, no-store"
    with _connection() as connection:
        rows = connection.execute(
            "SELECT t.transaction_key,t.product_id,p.delta,r.delta,t.created_at "
            "FROM app.purchase_transactions t "
            "JOIN app.credit_ledger p ON p.event_key='revenuecat:purchase:'||t.transaction_key AND p.account_id=t.account_id "
            "LEFT JOIN app.credit_ledger r ON r.event_key='revenuecat:refund:'||t.transaction_key AND r.account_id=t.account_id "
            "WHERE t.account_id=%s ORDER BY t.created_at DESC,t.transaction_key DESC LIMIT 50",
            (subject.id,),
        ).fetchall()
    return {"items": [{"id": key, "productId": product, "credits": amount,
                       "status": "reversed" if reversal is not None else "granted", "createdAt": created.isoformat()}
                      for key, product, amount, reversal, created in rows]}


@app.get("/v1/credits/purchases/status")
def credit_purchase_status(response: Response,
                           transactionId: str = Query(min_length=1, max_length=300),
                           productId: str = Query(min_length=1, max_length=300),
                           store: str = Query(pattern="^(APP_STORE|PLAY_STORE)$"),
                           subject: Subject = Depends(authenticated_subject)) -> dict:
    response.headers["Cache-Control"] = "private, no-store"
    with _connection() as connection:
        row = connection.execute(
            "SELECT p.delta,r.delta FROM app.purchase_transactions t "
            "JOIN app.credit_ledger p ON p.event_key='revenuecat:purchase:'||t.transaction_key AND p.account_id=t.account_id "
            "LEFT JOIN app.credit_ledger r ON r.event_key='revenuecat:refund:'||t.transaction_key AND r.account_id=t.account_id "
            "WHERE t.account_id=%s AND t.app_id=%s AND t.environment=%s AND t.store=%s AND t.transaction_id=%s AND t.product_id=%s",
            (subject.id, os.environ.get("REVENUECAT_APP_ID"), os.environ.get("REVENUECAT_ENVIRONMENT", "SANDBOX"), store, transactionId, productId),
        ).fetchone()
    if not row:
        return {"status": "pending"}
    return {"status": "reversed" if row[1] is not None else "granted", "credits": row[0]}


@app.post("/v1/uploads/presign", status_code=status.HTTP_201_CREATED)
def presign_upload(payload: PresignRequest, subject: Subject = Depends(authenticated_subject)) -> dict:
    if payload.mime_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=422, detail="unsupported image type")
    _account(subject)
    asset_key = uuid.uuid4()
    storage_key = f"incoming/{subject.id}/{asset_key}.{ALLOWED_IMAGE_TYPES[payload.mime_type]}"
    with _connection() as connection:
        expires_at = connection.execute(
            "INSERT INTO app.assets (asset_key, owner_id, storage_key, mime_type, size_bytes) VALUES (%s, %s, %s, %s, %s) RETURNING created_at + interval '15 minutes'",
            (asset_key, subject.id, storage_key, payload.mime_type, payload.size_bytes),
        ).fetchone()[0]
    return {"assetKey": str(asset_key), "uploadUrl": f"/v1/uploads/{asset_key}", "method": "PUT", "headers": {"Content-Type": payload.mime_type}, "expiresAt": expires_at.isoformat()}


@app.put("/v1/uploads/{asset_key}", status_code=status.HTTP_204_NO_CONTENT)
async def upload_bytes(asset_key: uuid.UUID, request: Request, subject: Subject = Depends(authenticated_subject)) -> Response:
    with _connection() as connection:
        lock_media_writer(connection, subject.id)
        asset = connection.execute(
            "SELECT storage_key, mime_type, verification_state, created_at + interval '15 minutes' > clock_timestamp() FROM app.assets WHERE asset_key = %s AND owner_id = %s",
            (asset_key, subject.id),
        ).fetchone()
    if not asset:
        raise HTTPException(status_code=404, detail="asset not found")
    if asset[2] != "pending" or request.headers.get("content-type") != asset[1]:
        raise HTTPException(status_code=409, detail="upload is not permitted")
    if not asset[3]:
        raise HTTPException(status_code=410, detail="upload expired; choose the photo again")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=422, detail="image is too large")
        data.extend(chunk)
    with _connection() as connection:
        lock_media_writer(connection, subject.id)
        # Recheck after streaming, then serialize the write with completion.
        current = connection.execute(
            "SELECT storage_key,verification_state,created_at + interval '15 minutes' > clock_timestamp() FROM app.assets WHERE asset_key=%s AND owner_id=%s FOR UPDATE",
            (asset_key, subject.id),
        ).fetchone()
        if not current or current[1] != "pending":
            raise HTTPException(status_code=409, detail="upload is not permitted")
        if not current[2]:
            raise HTTPException(status_code=410, detail="upload expired; choose the photo again")
        _storage().write(current[0], data)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/v1/uploads/complete")
def complete_upload(payload: CompleteRequest, subject: Subject = Depends(authenticated_subject)) -> dict[str, str]:
    with _connection() as connection:
        lock_media_writer(connection, subject.id)
        asset = connection.execute(
            "SELECT storage_key, mime_type, verification_state, created_at + interval '15 minutes' > clock_timestamp() FROM app.assets WHERE asset_key = %s AND owner_id = %s FOR UPDATE",
            (payload.asset_key, subject.id),
        ).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail="asset not found")
        if asset[2] == "verified":
            return {"assetKey": str(payload.asset_key), "state": "verified"}
        if not asset[3]:
            raise HTTPException(status_code=410, detail="upload expired; choose the photo again")
        try:
            original = _storage().read(asset[0])
            normalized = _verify_image(original, asset[1])
        except FileNotFoundError:
            raise HTTPException(status_code=422, detail="uploaded bytes are missing") from None
        verified_key = f"verified/{subject.id}/{payload.asset_key}.{ALLOWED_IMAGE_TYPES[asset[1]]}"
        _storage().write(verified_key, normalized)
        if os.environ.get("PUBLISH_PRIVATE_UPLOADS") == "true":
            from admaker.cloud_objects import publish_private_object
            try:
                publish_private_object(os.environ["DATABASE_URL"], subject.id, asset[0], original, asset[1])
                publish_private_object(os.environ["DATABASE_URL"], subject.id, verified_key, normalized, asset[1])
            except (OSError, ValueError):
                raise HTTPException(503, "Private upload storage is unconfirmed; retry this upload") from None
        connection.execute(
            "UPDATE app.assets SET storage_key = %s, size_bytes = %s, checksum = %s, verification_state = 'verified', verified_at = now() WHERE asset_key = %s",
            (verified_key, len(normalized), hashlib.sha256(normalized).hexdigest(), payload.asset_key),
        )
    return {"assetKey": str(payload.asset_key), "state": "verified"}


@app.post("/v1/jobs", status_code=status.HTTP_202_ACCEPTED)
def create_job(payload: JobRequest, request: Request, subject: Subject = Depends(authenticated_subject)) -> dict:
    from admaker.catalogue import require_template
    from admaker.job_prompts import snapshot_styles, prepare_video_prompt, prepare_photo_prompt

    if payload.output_kind not in {"video", "photo"}:
        raise HTTPException(status_code=422, detail="unsupported output kind")
    if payload.output_kind == "photo" and payload.template_id is None:
        raise HTTPException(status_code=422, detail="photo template is required")
    if (payload.template_id is None) != (payload.template_version is None):
        raise HTTPException(status_code=422, detail="template ID and version are required together")
    key = request.headers.get("Idempotency-Key")
    if not key:
        raise HTTPException(status_code=422, detail="Idempotency-Key is required")
    if payload.quality != "fast":
        raise HTTPException(status_code=422, detail="only fast quality is available")
    if any(platform not in PUBLIC_PLATFORMS for platform in payload.platforms):
        raise HTTPException(status_code=422, detail="unsupported platform")
    _account(subject)
    request_hash = hashlib.sha256(payload.model_dump_json(by_alias=True).encode()).hexdigest()
    with _connection() as connection:
        connection.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (subject.id,))
        existing = connection.execute("SELECT request_hash, response FROM app.command_keys WHERE account_id=%s AND route='jobs' AND key=%s", (subject.id, key)).fetchone()
        if existing:
            if existing[0] != request_hash:
                raise HTTPException(status_code=409, detail="idempotency key payload mismatch")
            return existing[1]
        if payload.template_id is not None:
            try:
                require_template(payload.template_id, payload.template_version, payload.output_kind)
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from None
        asset = connection.execute("SELECT asset_key FROM app.assets WHERE asset_key=%s AND owner_id=%s AND verification_state='verified'", (payload.asset_key, subject.id)).fetchone()
        if not asset:
            raise HTTPException(status_code=422, detail="verified source asset is required")
        from admaker.admission_limit import require_generation_capacity
        require_generation_capacity(connection, subject.id)
        available = connection.execute("SELECT COALESCE(SUM(delta), 0) - COALESCE((SELECT SUM(amount) FROM app.credit_reservations WHERE account_id=%s AND state='held'), 0) FROM app.credit_ledger WHERE account_id=%s", (subject.id, subject.id)).fetchone()[0]
        if available < 1:
            raise HTTPException(status_code=409, detail="insufficient credits")
        job_id, reservation_id = uuid.uuid4(), uuid.uuid4()
        job_state = "submitted" if payload.fast_mode or payload.template_id else "awaiting_style_choice"
        settings = {"platforms": payload.platforms, "renderPlatforms": ["feed_square" if platform == "feed" else platform for platform in payload.platforms], "fastMode": payload.fast_mode, "quality": payload.quality}
        settings.update({"templateId": payload.template_id, "templateVersion": payload.template_version,
                         "outputKind": payload.output_kind, "direction": payload.direction})
        settings["structuredPlanning"] = os.environ.get("ENABLE_STRUCTURED_PLANNING") == "true"
        if payload.output_kind == "video":
            settings["videoProvider"] = os.environ.get("ENABLE_REAL_VEO") == "true"
        if job_state == "awaiting_style_choice":
            settings["styleOptions"] = snapshot_styles(STYLE_CANDIDATES)
        elif payload.output_kind == "video":
            template = require_template(payload.template_id or "pedestal_spin", payload.template_version or 1, "video")
            settings["preparedVideoPrompt"] = prepare_video_prompt(template["prompt"], payload.direction)
        else:
            from admaker.photo_provider import PHOTO_MODEL
            template = require_template(payload.template_id, payload.template_version, "photo")
            try:
                settings["preparedPhotoPrompt"] = prepare_photo_prompt(template["prompt"], payload.direction)
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from None
            settings["photoModel"] = PHOTO_MODEL
            settings["photoProvider"] = os.environ.get("ENABLE_REAL_PHOTO") == "true"
        from admaker.photo_routing import photo_queue
        destination_queue = photo_queue(settings, subject.id)
        created_at, version = connection.execute("INSERT INTO app.jobs (id, owner_id, source_asset_id, state, settings) VALUES (%s,%s,%s,%s,%s) RETURNING created_at,version", (job_id, subject.id, payload.asset_key, job_state, psycopg.types.json.Jsonb(settings))).fetchone()
        connection.execute("INSERT INTO app.credit_reservations (id, account_id, job_id, amount, state) VALUES (%s,%s,%s,1,'held')", (reservation_id, subject.id, job_id))
        response = {"id": str(job_id), "state": job_state, "assetKey": str(payload.asset_key), "platforms": payload.platforms, "fastMode": payload.fast_mode, "quality": "fast", "candidates": STYLE_CANDIDATES if job_state == "awaiting_style_choice" else []}
        response.update({"title": "Product photo" if payload.output_kind == "photo" else "Product ad",
                         "createdAt": created_at.isoformat(), "version": version, "outputKind": payload.output_kind})
        if job_state == "submitted":
            connection.execute("SELECT pgmq.send(%s, %s::jsonb)", (destination_queue, psycopg.types.json.Jsonb({"jobId": str(job_id)})))
        connection.execute("INSERT INTO app.command_keys (account_id, route, key, request_hash, response) VALUES (%s,'jobs',%s,%s,%s)", (subject.id, key, request_hash, psycopg.types.json.Jsonb(response)))
    return response


@app.post("/v1/jobs/{job_id}/style-choice", status_code=status.HTTP_202_ACCEPTED)
def choose_style(job_id: uuid.UUID, payload: StyleChoiceRequest, request: Request, subject: Subject = Depends(authenticated_subject)) -> dict:
    key = request.headers.get("Idempotency-Key")
    if not key:
        raise HTTPException(status_code=422, detail="Idempotency-Key is required")
    from admaker.job_prompts import prepare_video_prompt

    if bool(payload.preset_id) == bool(payload.direction and payload.direction.strip()):
        raise HTTPException(status_code=422, detail="choose exactly one preset or nonempty direction")
    request_hash = hashlib.sha256((str(job_id) + ":" + payload.model_dump_json(by_alias=True)).encode()).hexdigest()
    with _connection() as connection:
        connection.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (subject.id,))
        existing = connection.execute("SELECT request_hash, response FROM app.command_keys WHERE account_id=%s AND route='style-choice' AND key=%s", (subject.id, key)).fetchone()
        if existing:
            if existing[0] != request_hash:
                raise HTTPException(status_code=409, detail="idempotency key payload mismatch")
            return existing[1]
        job = _job_for_command(connection, job_id, subject.id, payload.expected_version, "awaiting_style_choice")
        options = job[0].get("styleOptions", [])
        chosen = next((item for item in options if item["id"] == payload.preset_id), None) if payload.preset_id else next(iter(options), None)
        if not chosen:
            raise HTTPException(status_code=422, detail="choose a style offered for this generation")
        direction = payload.direction.strip() if payload.direction else job[0].get("direction", "")
        prepared = prepare_video_prompt(chosen["prompt"], direction)

        row = connection.execute(
            "UPDATE app.jobs SET state='submitted', settings=settings || %s WHERE id=%s AND owner_id=%s AND state='awaiting_style_choice' AND version=%s RETURNING id, source_asset_id, settings, created_at, version",
            (psycopg.types.json.Jsonb({"presetId": chosen["id"], "direction": direction, "preparedVideoPrompt": prepared}), job_id, subject.id, payload.expected_version),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=409, detail="style choice is not available")
        from admaker.photo_routing import photo_queue
        destination_queue = photo_queue(row[2], subject.id)
        connection.execute("SELECT pgmq.send(%s, %s::jsonb)", (destination_queue, psycopg.types.json.Jsonb({"jobId": str(job_id)})))
        response = {"id": str(row[0]), "title": "Product ad", "state": "submitted", "platforms": row[2].get("platforms", [])}
        response.update({"createdAt": row[3].isoformat(), "version": row[4], "outputKind": row[2].get("outputKind", "video")})
        connection.execute("INSERT INTO app.command_keys (account_id, route, key, request_hash, response) VALUES (%s,'style-choice',%s,%s,%s)", (subject.id, key, request_hash, psycopg.types.json.Jsonb(response)))
    return response


@app.post("/v1/jobs/{job_id}/decision", status_code=status.HTTP_202_ACCEPTED)
def decide_job(job_id: uuid.UUID, payload: DecisionRequest, request: Request, subject: Subject = Depends(authenticated_subject)) -> dict:
    key = request.headers.get("Idempotency-Key")
    if not key:
        raise HTTPException(status_code=422, detail="Idempotency-Key is required")
    request_hash = hashlib.sha256((str(job_id) + ":" + payload.model_dump_json(exclude_none=True)).encode()).hexdigest()
    with _connection() as connection:
        lock_media_writer(connection, subject.id)
        connection.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (subject.id,))
        existing = connection.execute("SELECT request_hash, response FROM app.command_keys WHERE account_id=%s AND route='decision' AND key=%s", (subject.id, key)).fetchone()
        if existing:
            if existing[0] != request_hash:
                raise HTTPException(status_code=409, detail="idempotency key payload mismatch")
            if existing[1].get("state") == "cancelled":
                raise HTTPException(409, "This decision request was closed; review the generation and use a new request")
            return existing[1]
        job = _job_for_command(connection, job_id, subject.id, payload.expected_version, "awaiting_user_decision")
        held = connection.execute("SELECT id,amount FROM app.credit_reservations WHERE job_id=%s AND account_id=%s AND state='held' FOR UPDATE", (job_id, subject.id)).fetchall()
        if len(held) != 1:
            raise HTTPException(status_code=409, detail="generation reservation needs review")
        reservation_id, amount = held[0]
        prior_attempt = connection.execute("SELECT a.id,a.run_id,a.provider_state FROM app.job_attempts a JOIN app.jobs j ON j.active_run_id=a.run_id WHERE j.id=%s AND a.reservation_id=%s FOR UPDATE OF a", (job_id, reservation_id)).fetchone()
        active_run = connection.execute("SELECT active_run_id FROM app.jobs WHERE id=%s", (job_id,)).fetchone()[0]
        if active_run is not None and prior_attempt is None:
            raise HTTPException(status_code=409, detail="generation reservation does not match its active attempt")
        if prior_attempt and prior_attempt[2] in {"submitting", "submission_unknown", "submitted"}:
            raise HTTPException(status_code=409, detail="generation is still being reconciled")
        if payload.action == "accept":
            validation = job[1].get("candidateValidation", {})
            exports_hash = hashlib.sha256(json.dumps(job[1].get("exports", {}), sort_keys=True).encode()).hexdigest()
            if (not job[1].get("exports") or validation.get("technicalPassed") is not True
                    or validation.get("policyAllowed") is not True or validation.get("exportsHash") != exports_hash
                    or validation.get("reservationId") != str(reservation_id)):
                raise HTTPException(status_code=409, detail="no validated result is available")
            if job[0].get("generationKind") == "campaign_pack":
                from admaker.campaign_pack import require_available_pack
                from admaker.cloud_objects import stage_private_object
                try:
                    for item in job[1]["exports"].values():
                        if isinstance(item, dict) and isinstance(item.get("key"), str):
                            stage_private_object(os.environ["DATABASE_URL"], subject.id, item["key"], _storage().root)
                    require_available_pack(_storage().root, job[1]["exports"])
                except (OSError, ValueError):
                    raise HTTPException(status_code=409, detail="The complete campaign pack is unavailable; your credits remain reserved") from None
            else:
                from admaker.cloud_objects import stage_private_object
                try:
                    maximum = MAX_IMAGE_BYTES if job[0].get("outputKind") == "photo" else 100 * 1024 * 1024
                    for item in job[1]["exports"].values():
                        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
                            raise ValueError("Invalid media manifest")
                        stage_private_object(os.environ["DATABASE_URL"], subject.id, item["key"], _storage().root)
                        path = _storage().path(item["key"])
                        if (not path.is_file() or not 0 < path.stat().st_size <= maximum
                                or hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256")):
                            raise ValueError("Reviewed media is unavailable or changed")
                except (OSError, ValueError):
                    raise HTTPException(409, "The reviewed media is unavailable or cannot be verified; your credits remain reserved") from None
            connection.execute("UPDATE app.credit_reservations SET state='consumed' WHERE id=%s", (reservation_id,))
            connection.execute("INSERT INTO app.credit_ledger (account_id, delta, event_key, reason, reservation_id) VALUES (%s,%s,%s,'manual_acceptance',%s)", (subject.id, -amount, f"accept:{job_id}:{reservation_id}", reservation_id))
            state = "delivered"
        elif payload.action == "spend_more":
            from admaker.admission_limit import require_generation_capacity
            require_generation_capacity(connection, subject.id, job_id)
            retry_price, retry_queue = retry_terms(job[0], payload.confirmed_credits, subject.id)
            connection.execute("UPDATE app.credit_reservations SET state='released' WHERE id=%s", (reservation_id,))
            available = connection.execute("SELECT COALESCE(SUM(delta), 0) - COALESCE((SELECT SUM(amount) FROM app.credit_reservations WHERE account_id=%s AND state='held'), 0) FROM app.credit_ledger WHERE account_id=%s", (subject.id, subject.id)).fetchone()[0]
            if available < retry_price:
                raise HTTPException(status_code=409, detail="insufficient credits")
            connection.execute("INSERT INTO app.credit_reservations (id, account_id, job_id, amount, state) VALUES (%s,%s,%s,%s,'held')", (uuid.uuid4(), subject.id, job_id, retry_price))
            connection.execute("SELECT pgmq.send(%s, %s::jsonb)", (retry_queue, psycopg.types.json.Jsonb({"jobId": str(job_id)})))
            state = "submitted"
        else:
            connection.execute("UPDATE app.credit_reservations SET state='released' WHERE id=%s", (reservation_id,))
            state = "aborted"
        if prior_attempt:
            terminal = "delivered" if payload.action == "accept" else "failed"
            connection.execute("UPDATE app.job_attempts SET state=%s,completed_at=clock_timestamp() WHERE id=%s", (terminal, prior_attempt[0]))
            connection.execute("UPDATE app.job_runs SET state=%s,lease_until=NULL,next_work_at=NULL WHERE id=%s", (terminal, prior_attempt[1]))
        created_at, version = connection.execute("UPDATE app.jobs SET state=%s WHERE id=%s RETURNING created_at,version", (state, job_id)).fetchone()
        response = {"id": str(job_id), "title": "Product ad", "state": state, "platforms": job[0].get("platforms", [])}
        response.update({"createdAt": created_at.isoformat(), "version": version, "outputKind": job[0].get("outputKind", "video")})
        connection.execute("INSERT INTO app.command_keys (account_id, route, key, request_hash, response) VALUES (%s,'decision',%s,%s,%s)", (subject.id, key, request_hash, psycopg.types.json.Jsonb(response)))
    return response


@app.post("/v1/jobs/{job_id}/decision/close")
def close_decision(job_id: uuid.UUID, payload: DecisionRequest, request: Request,
                   subject: Subject = Depends(authenticated_subject)) -> dict:
    key = request.headers.get("Idempotency-Key", "")
    if not 1 <= len(key) <= 200:
        raise HTTPException(422, "A bounded Idempotency-Key is required")
    digest = hashlib.sha256((str(job_id) + ":" + payload.model_dump_json(exclude_none=True)).encode()).hexdigest()
    with _connection() as connection:
        connection.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (subject.id,))
        existing = connection.execute("SELECT request_hash,response FROM app.command_keys WHERE account_id=%s AND route='decision' AND key=%s", (subject.id, key)).fetchone()
        if existing:
            if existing[0] != digest:
                raise HTTPException(409, "idempotency key payload mismatch")
            return existing[1]
        if not connection.execute("SELECT id FROM app.jobs WHERE id=%s AND owner_id=%s", (job_id, subject.id)).fetchone():
            raise HTTPException(404, "job not found")
        response = {"state": "cancelled"}
        connection.execute("INSERT INTO app.command_keys(account_id,route,key,request_hash,response) VALUES (%s,'decision',%s,%s,%s)", (subject.id, key, digest, psycopg.types.json.Jsonb(response)))
    return response


@app.post("/v1/jobs/{job_id}/regen", status_code=status.HTTP_202_ACCEPTED)
def regen_job(job_id: uuid.UUID, payload: RegenRequest, request: Request, subject: Subject = Depends(authenticated_subject)) -> dict:
    key = request.headers.get("Idempotency-Key")
    if not key:
        raise HTTPException(status_code=422, detail="Idempotency-Key is required")
    request_hash = hashlib.sha256((str(job_id) + ":" + payload.model_dump_json(exclude_none=True)).encode()).hexdigest()
    with _connection() as connection:
        connection.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (subject.id,))
        existing = connection.execute("SELECT request_hash, response FROM app.command_keys WHERE account_id=%s AND route='regen' AND key=%s", (subject.id, key)).fetchone()
        if existing:
            if existing[0] != request_hash:
                raise HTTPException(status_code=409, detail="idempotency key payload mismatch")
            return existing[1]
        job = _job_for_command(connection, job_id, subject.id, payload.expected_version, "delivered")
        from admaker.admission_limit import require_generation_capacity
        require_generation_capacity(connection, subject.id, job_id)
        retry_price, retry_queue = retry_terms(job[0], payload.confirmed_credits, subject.id)
        available = connection.execute("SELECT COALESCE(SUM(delta), 0) - COALESCE((SELECT SUM(amount) FROM app.credit_reservations WHERE account_id=%s AND state='held'), 0) FROM app.credit_ledger WHERE account_id=%s", (subject.id, subject.id)).fetchone()[0]
        if available < retry_price:
            raise HTTPException(status_code=409, detail="insufficient credits")
        connection.execute("INSERT INTO app.credit_reservations (id, account_id, job_id, amount, state) VALUES (%s,%s,%s,%s,'held')", (uuid.uuid4(), subject.id, job_id, retry_price))
        created_at, version = connection.execute("UPDATE app.jobs SET state='submitted' WHERE id=%s RETURNING created_at,version", (job_id,)).fetchone()
        response = {"id": str(job_id), "title": "Product ad", "state": "submitted", "platforms": job[0].get("platforms", [])}
        response.update({"createdAt": created_at.isoformat(), "version": version, "outputKind": job[0].get("outputKind", "video")})
        connection.execute("SELECT pgmq.send(%s, %s::jsonb)", (retry_queue, psycopg.types.json.Jsonb({"jobId": str(job_id)})))
        connection.execute("INSERT INTO app.command_keys (account_id, route, key, request_hash, response) VALUES (%s,'regen',%s,%s,%s)", (subject.id, key, request_hash, psycopg.types.json.Jsonb(response)))
    return response


@app.get("/v1/jobs")
def list_jobs(limit: int = Query(default=20, ge=1, le=100), cursor: str | None = None, subject: Subject = Depends(authenticated_subject)) -> dict:
    after = _parse_job_cursor(cursor) if cursor else None
    with _connection() as connection:
        rows = connection.execute("SELECT id, state, created_at, settings FROM app.jobs WHERE owner_id=%s AND (%s::timestamptz IS NULL OR (created_at, id) < (%s::timestamptz, %s::uuid)) ORDER BY created_at DESC, id DESC LIMIT %s", (subject.id, after[0] if after else None, after[0] if after else None, after[1] if after else None, limit + 1)).fetchall()
    page = rows[:limit]
    return {"items": [{"id": str(row[0]), "title": "Product photo" if row[3].get("outputKind") == "photo" else "Product ad", "state": row[1], "createdAt": row[2].isoformat(), "platforms": row[3].get("platforms", []), "outputKind": row[3].get("outputKind", "video"), "campaignId": row[3].get("campaignId"), "campaignVersion": row[3].get("campaignVersion")} for row in page], "nextCursor": _job_cursor(page[-1][2], page[-1][0]) if len(rows) > limit else None}


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: uuid.UUID, subject: Subject = Depends(authenticated_subject)) -> dict:
    from admaker.job_progress import generation_stage

    with _connection() as connection:
        row = connection.execute(
            "SELECT id, state, created_at, source_asset_id, settings, result, version FROM app.jobs WHERE id=%s AND owner_id=%s",
            (job_id, subject.id),
        ).fetchone()
        stage = generation_stage(connection, job_id, subject.id) if row and row[1] == "running" else None
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    settings = row[4]
    exports = [{"platform": "feed" if platform == "feed_square" and "feed" in settings.get("platforms", []) else platform, "url": f"/v1/jobs/{row[0]}/exports/{'feed' if platform == 'feed_square' and 'feed' in settings.get('platforms', []) else platform}", "caption": value.get("caption", "")} for platform, value in row[5].get("exports", {}).items()]
    return {
        "id": str(row[0]), "title": "Product ad", "state": row[1], "createdAt": row[2].isoformat(),
        "version": row[6],
        "stage": stage,
        "gate": row[1] if row[1] in {"awaiting_style_choice", "awaiting_user_decision"} else None,
        "sourceImage": str(row[3]), "platforms": settings.get("platforms", []), "exports": exports,
        "outputKind": settings.get("outputKind", "video"),
        "campaignId": settings.get("campaignId"), "campaignVersion": settings.get("campaignVersion"),
        "templateId": settings.get("templateId"), "templateVersion": settings.get("templateVersion"),
        "direction": settings.get("direction", ""),
        "resultVersion": hashlib.sha256(json.dumps(row[5], sort_keys=True).encode()).hexdigest(),
        "failure": campaign_failure(row[1], row[5]) or ({"code": "submission_unknown", "message": "Generation needs review. Your reserved credits remain held; contact support."}
            if row[5].get("failure", {}).get("code") == "submission_unknown" else
            {"code": "generation_closed", "message": "This generation was closed after review. Your reserved credits have been released."}
            if row[5].get("failure", {}).get("code") == "generation_closed" else
            {"code": "incompatible_run", "message": "This generation needs a service update before it can continue. Your reserved credits remain held; contact support."}
            if row[5].get("failure", {}).get("code") == "incompatible_run" else None) if row[1] == "failed" else None,
        "candidates": [{key: value for key, value in option.items() if key != "prompt"} for option in settings.get("styleOptions", [])] if row[1] == "awaiting_style_choice" else [],
    }


@app.get("/v1/jobs/{job_id}/exports/{platform}")
def download_export(job_id: uuid.UUID, platform: str, subject: Subject = Depends(authenticated_subject)) -> Response:
    with _connection() as connection:
        row = connection.execute("SELECT result FROM app.jobs WHERE id=%s AND owner_id=%s", (job_id, subject.id)).fetchone()
    item = (row[0].get("exports", {}).get(platform) or row[0].get("exports", {}).get("feed_square" if platform == "feed" else platform) or {}) if row else {}
    key = item.get("key")
    if not key:
        raise HTTPException(status_code=404, detail="export not found")
    from admaker.cloud_objects import private_object_download_url
    try:
        cloud_url = private_object_download_url(os.environ["DATABASE_URL"], subject.id, key)
    except (OSError, ValueError):
        raise HTTPException(503, "Private export download is unavailable") from None
    if cloud_url:
        return RedirectResponse(cloud_url, status_code=302, headers={"Cache-Control": "private, no-store"})
    if not _storage().path(key).is_file():
        raise HTTPException(status_code=404, detail="export not found")
    if "sha256" in item:
        with _storage().path(key).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                raise HTTPException(503, "Private export integrity could not be verified")
    is_photo = key.endswith(".png")
    return FileResponse(_storage().path(key), media_type="image/png" if is_photo else "video/mp4", filename=f"{platform}.{'png' if is_photo else 'mp4'}", headers={"Cache-Control": "private, no-store"})


@app.post("/v1/webhooks/revenuecat", status_code=status.HTTP_202_ACCEPTED)
async def revenuecat_webhook(request: Request) -> dict[str, bool]:
    from admaker.billing import process_revenuecat_event
    from admaker.billing_payload import retained_revenuecat_payload

    expected = os.environ.get("REVENUECAT_AUTHORIZATION")
    if not expected or not hmac.compare_digest(request.headers.get("authorization", "").encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="invalid webhook authorization")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > 65536:
            raise HTTPException(status_code=413, detail="webhook is too large")
        data.extend(chunk)
    try:
        payload = json.loads(data)
        event = payload["event"]
        event_id = event["id"]
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 200 or not isinstance(event.get("type"), str):
            raise ValueError("invalid event")
        encoded = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
        raise HTTPException(status_code=422, detail="invalid webhook event") from None
    with _connection() as connection:
        retained = psycopg.types.json.Jsonb(retained_revenuecat_payload(payload))
        connection.execute("INSERT INTO app.webhook_events (provider, event_id, payload_hash, payload) VALUES ('revenuecat', %s, %s, %s) ON CONFLICT (provider, event_id) DO NOTHING", (event_id, encoded, retained))
        saved = connection.execute("SELECT payload_hash FROM app.webhook_events WHERE provider='revenuecat' AND event_id=%s FOR UPDATE", (event_id,)).fetchone()[0]
        if saved != encoded:
            raise HTTPException(status_code=409, detail="webhook event payload mismatch")
        # Also minimize a legacy full receipt when its exact original is redelivered.
        connection.execute("UPDATE app.webhook_events SET payload=%s WHERE provider='revenuecat' AND event_id=%s AND payload IS DISTINCT FROM %s", (retained, event_id, retained))
    # Receipt is durable before processing; a crash leaves 'received' for the worker.
    try:
        process_revenuecat_event(os.environ["DATABASE_URL"], event_id)
    except psycopg.Error:
        logging.warning("billing receipt %s retained for retry", event_id)
    return {"accepted": True}


class ProductRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"\S")
    description: str = Field(default="", max_length=1000)
    asset_key: uuid.UUID = Field(alias="assetKey")


class RenameProductRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"\S")


def _product_result(row) -> dict:
    return {"id": str(row[0]), "name": row[1], "description": row[2],
            "assetKey": str(row[3]), "createdAt": row[4].isoformat()}


@app.post("/v1/products", status_code=201)
def save_product(payload: ProductRequest, request: Request, subject: Subject = Depends(authenticated_subject)) -> dict:
    key = request.headers.get("Idempotency-Key")
    if key is not None and (not key or len(key) > 200):
        raise HTTPException(status_code=422, detail="invalid Idempotency-Key")
    request_hash = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
    with _connection() as connection:
        connection.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (subject.id,))
        if key:
            previous = connection.execute(
                "SELECT request_hash,response FROM app.command_keys WHERE account_id=%s AND route='products' AND key=%s",
                (subject.id, key),
            ).fetchone()
            if previous:
                if previous[0] != request_hash:
                    raise HTTPException(status_code=409, detail="idempotency key payload mismatch")
                return previous[1]
        row = connection.execute(
            "INSERT INTO app.products (id, owner_id, name, description, source_asset_id) "
            "SELECT %s, owner_id, %s, %s, asset_key FROM app.assets "
            "WHERE asset_key=%s AND owner_id=%s AND verification_state='verified' "
            "RETURNING id, name, description, source_asset_id, created_at",
            (uuid.uuid4(), payload.name.strip(), payload.description, payload.asset_key, subject.id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=422, detail="verified source asset is required")
        response = _product_result(row)
        if key:
            connection.execute(
                "INSERT INTO app.command_keys(account_id,route,key,request_hash,response) VALUES (%s,'products',%s,%s,%s)",
                (subject.id, key, request_hash, psycopg.types.json.Jsonb(response)),
            )
    return response


@app.get("/v1/products")
def list_products(limit: int = Query(default=20, ge=1, le=100), cursor: str | None = None,
                  subject: Subject = Depends(authenticated_subject)) -> dict:
    after = _parse_job_cursor(cursor) if cursor else None
    with _connection() as connection:
        rows = connection.execute(
            "SELECT id, name, description, source_asset_id, created_at FROM app.products "
            "WHERE owner_id=%s AND deleted_at IS NULL AND (%s::timestamptz IS NULL OR "
            "(created_at,id)<(%s::timestamptz,%s::uuid)) ORDER BY created_at DESC,id DESC LIMIT %s",
            (subject.id, after[0] if after else None, after[0] if after else None,
             after[1] if after else None, limit + 1),
        ).fetchall()
    page = rows[:limit]
    return {"items": [_product_result(row) for row in page],
            "nextCursor": _job_cursor(page[-1][4], page[-1][0]) if len(rows) > limit else None}


@app.get("/v1/products/{product_id}")
def get_product(product_id: uuid.UUID, subject: Subject = Depends(authenticated_subject)) -> dict:
    with _connection() as connection:
        row = connection.execute(
            "SELECT id, name, description, source_asset_id, created_at FROM app.products "
            "WHERE id=%s AND owner_id=%s AND deleted_at IS NULL", (product_id, subject.id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="product not found")
    return _product_result(row)


@app.patch("/v1/products/{product_id}")
def rename_product(product_id: uuid.UUID, payload: RenameProductRequest,
                   subject: Subject = Depends(authenticated_subject)) -> dict:
    with _connection() as connection:
        row = connection.execute(
            "UPDATE app.products SET name=%s WHERE id=%s AND owner_id=%s AND deleted_at IS NULL "
            "RETURNING id, name, description, source_asset_id, created_at",
            (payload.name.strip(), product_id, subject.id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="product not found")
    return _product_result(row)


@app.delete("/v1/products/{product_id}")
def delete_product(product_id: uuid.UUID, subject: Subject = Depends(authenticated_subject)) -> dict:
    with _connection() as connection:
        row = connection.execute(
            "UPDATE app.products SET deleted_at=COALESCE(deleted_at,now()) "
            "WHERE id=%s AND owner_id=%s RETURNING id", (product_id, subject.id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="product not found")
    return {"id": str(product_id), "state": "deleted", "assetsRetained": True}


class ApproveProductImageRequest(BaseModel):
    asset_key: uuid.UUID = Field(alias="assetKey")
    expected_version: int = Field(alias="expectedVersion", ge=0)


@app.post("/v1/products/{product_id}/approved-image")
def approve_product_image(product_id: uuid.UUID, payload: ApproveProductImageRequest,
                          subject: Subject = Depends(authenticated_subject)) -> dict:
    with _connection() as connection:
        product = connection.execute(
            "SELECT id FROM app.products WHERE id=%s AND owner_id=%s AND deleted_at IS NULL FOR UPDATE",
            (product_id, subject.id),
        ).fetchone()
        if not product:
            raise HTTPException(status_code=404, detail="product not found")
        current = connection.execute(
            "SELECT version, asset_key FROM app.product_images WHERE product_id=%s ORDER BY version DESC LIMIT 1",
            (product_id,),
        ).fetchone()
        # The same approval replay returns its existing version without new work.
        if current and current[1] == payload.asset_key and current[0] == payload.expected_version + 1:
            return {"assetKey": str(current[1]), "version": current[0]}
        version = current[0] if current else 0
        if version != payload.expected_version:
            raise HTTPException(status_code=409, detail="product image version changed")
        asset = connection.execute(
            "SELECT asset_key FROM app.assets WHERE asset_key=%s AND owner_id=%s AND verification_state='verified'",
            (payload.asset_key, subject.id),
        ).fetchone()
        if not asset:
            raise HTTPException(status_code=422, detail="verified owned image is required")
        if current and current[1] == payload.asset_key:
            return {"assetKey": str(current[1]), "version": version}
        connection.execute(
            "INSERT INTO app.product_images(product_id,owner_id,version,asset_key) VALUES (%s,%s,%s,%s)",
            (product_id, subject.id, version + 1, payload.asset_key),
        )
    return {"assetKey": str(payload.asset_key), "version": version + 1}


@app.get("/v1/products/{product_id}/approved-image")
def get_approved_product_image(product_id: uuid.UUID, version: int | None = Query(default=None, ge=1),
                              subject: Subject = Depends(authenticated_subject)) -> dict:
    with _connection() as connection:
        if not connection.execute(
            "SELECT id FROM app.products WHERE id=%s AND owner_id=%s AND deleted_at IS NULL",
            (product_id, subject.id),
        ).fetchone():
            raise HTTPException(status_code=404, detail="product not found")
        row = connection.execute(
            "SELECT version,asset_key FROM app.product_images WHERE product_id=%s "
            "AND (%s::integer IS NULL OR version=%s) ORDER BY version DESC LIMIT 1",
            (product_id, version, version),
        ).fetchone()
    return {"image": {"version": row[0], "assetKey": str(row[1])} if row else None}


class CampaignRequest(BaseModel):
    campaignLanguage: Literal["en", "tr", "pt-BR", "es"] | None = None
    objective: Literal["new_product", "weekend", "seasonal", "clearance"] | None = None
    font: Literal["sans", "serif"] | None = None
    contact: str | None = Field(default=None, max_length=100, pattern=r"^[^\x00-\x1f\x7f]*$")
    logo_asset_key: uuid.UUID | None = Field(default=None, alias="logoAssetKey")
    product_id: uuid.UUID = Field(alias="productId")
    image_version: int = Field(alias="imageVersion", ge=1)
    template_id: str | None = Field(default=None, alias="templateId", max_length=100)
    template_version: int | None = Field(default=None, alias="templateVersion", ge=1, strict=True)
    offer: str = Field(default="", max_length=300)
    instructions: str = Field(default="", max_length=500)
    caption: str = Field(default="", max_length=2200)
    cta: str = Field(default="", max_length=100)
    color: str = Field(default="#FFFFFF", pattern=r"^#[0-9a-fA-F]{6}$")


def create_campaign_record(connection, payload: CampaignRequest, subject: Subject, key: str) -> dict:
    if not key or len(key) > 200:
        raise HTTPException(status_code=422, detail="valid Idempotency-Key is required")
    request_hash = hashlib.sha256(payload.model_dump_json(exclude_none=True).encode()).hexdigest()
    if not connection.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (subject.id,)).fetchone():
        raise HTTPException(status_code=404, detail="account not found")
    previous = connection.execute(
        "SELECT request_hash,response FROM app.command_keys WHERE account_id=%s AND route='campaigns' AND key=%s",
        (subject.id, key),
    ).fetchone()
    if previous:
        if previous[0] != request_hash:
            raise HTTPException(status_code=409, detail="idempotency key payload mismatch")
        return previous[1]
    image = connection.execute(
        "SELECT i.asset_key FROM app.products p JOIN app.product_images i ON i.product_id=p.id "
        "WHERE p.id=%s AND p.owner_id=%s AND p.deleted_at IS NULL AND i.version=%s FOR UPDATE OF p",
        (payload.product_id, subject.id, payload.image_version),
    ).fetchone()
    if not image:
        raise HTTPException(status_code=422, detail="approved owned product image is required")
    campaign_id = uuid.uuid4()
    from admaker.catalogue import require_template
    if (payload.template_id is None) != (payload.template_version is None):
        raise HTTPException(status_code=422, detail="template ID and version must be selected together")
    style = None
    if payload.template_id is not None:
        try:
            style = require_template(payload.template_id, payload.template_version, "video")
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    brief = payload.model_dump(exclude_none=True, exclude={"product_id", "image_version", "template_id", "template_version", "logo_asset_key"})
    if payload.logo_asset_key is not None:
        from admaker.campaign_logo import owned_logo
        try:
            owned_logo(connection, subject.id, payload.logo_asset_key)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        brief["logoAssetKey"] = str(payload.logo_asset_key)
    if style:
        brief["style"] = {"id": style["id"], "version": style["version"], "name": style["name"]}
    connection.execute(
        "INSERT INTO app.campaigns(id,owner_id,product_id,image_version,brief,style_snapshot) VALUES (%s,%s,%s,%s,%s,%s)",
        (campaign_id, subject.id, payload.product_id, payload.image_version, psycopg.types.json.Jsonb(brief),
         psycopg.types.json.Jsonb(style) if style else None),
    )
    response = {"id": str(campaign_id), "productId": str(payload.product_id),
                "imageVersion": payload.image_version, "assetKey": str(image[0]),
                "brief": brief, "version": 1, "state": "draft"}
    connection.execute(
        "INSERT INTO app.command_keys(account_id,route,key,request_hash,response) VALUES (%s,'campaigns',%s,%s,%s)",
        (subject.id, key, request_hash, psycopg.types.json.Jsonb(response)),
    )
    return response


@app.post("/v1/campaigns", status_code=201)
def create_campaign(payload: CampaignRequest, request: Request,
                    subject: Subject = Depends(authenticated_subject)) -> dict:
    with _connection() as connection:
        return create_campaign_record(connection, payload, subject, request.headers.get("Idempotency-Key", ""))


class NewCampaignGenerateRequest(CampaignRequest):
    template_id: str = Field(alias="templateId", min_length=1, max_length=100)
    template_version: int = Field(alias="templateVersion", ge=1, strict=True)
    confirmed_credits: int = Field(alias="confirmedCredits", ge=1, le=10000, strict=True)


@app.post("/v1/campaign-pack/generate", status_code=202)
def generate_new_campaign(payload: NewCampaignGenerateRequest, request: Request,
                          subject: Subject = Depends(authenticated_subject)):
    from admaker.new_campaign import new_campaign_command
    with _connection() as connection:
        result = new_campaign_command(connection, payload, subject, request.headers.get("Idempotency-Key", ""))
        if result.get("state") == "cancelled":
            raise HTTPException(409, "This saved request was closed; review the price and use a new request")
        return result


@app.post("/v1/campaign-pack/generate/close")
def close_new_campaign(payload: NewCampaignGenerateRequest, request: Request,
                       subject: Subject = Depends(authenticated_subject)):
    from admaker.new_campaign import new_campaign_command
    with _connection() as connection:
        return new_campaign_command(connection, payload, subject, request.headers.get("Idempotency-Key", ""), close=True)


@app.get("/v1/campaigns/{campaign_id}")
def get_campaign(campaign_id: uuid.UUID, subject: Subject = Depends(authenticated_subject)) -> dict:
    with _connection() as connection:
        row = connection.execute(
            "SELECT c.product_id,c.image_version,i.asset_key,c.brief,c.version FROM app.campaigns c "
            "JOIN app.product_images i ON i.product_id=c.product_id AND i.version=c.image_version "
            "WHERE c.id=%s AND c.owner_id=%s", (campaign_id, subject.id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="campaign not found")
    return {"id": str(campaign_id), "productId": str(row[0]), "imageVersion": row[1],
            "assetKey": str(row[2]), "brief": row[3], "version": row[4], "state": "draft"}


class CampaignEditRequest(BaseModel):
    campaignLanguage: Literal["en", "tr", "pt-BR", "es"] | None = None
    objective: Literal["new_product", "weekend", "seasonal", "clearance"] | None = None
    font: Literal["sans", "serif"] | None = None
    contact: str | None = Field(default=None, max_length=100, pattern=r"^[^\x00-\x1f\x7f]*$")
    logo_asset_key: uuid.UUID | None = Field(default=None, alias="logoAssetKey")
    expected_version: int = Field(alias="expectedVersion", ge=1)
    offer: str = Field(max_length=300)
    caption: str = Field(max_length=2200)
    cta: str = Field(max_length=100)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


@app.patch("/v1/campaigns/{campaign_id}")
def edit_campaign(campaign_id: uuid.UUID, payload: CampaignEditRequest,
                  subject: Subject = Depends(authenticated_subject)) -> dict:
    with _connection() as connection:
        row = connection.execute(
            "SELECT version FROM app.campaigns WHERE id=%s AND owner_id=%s FOR UPDATE",
            (campaign_id, subject.id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="campaign not found")
        if row[0] != payload.expected_version:
            raise HTTPException(status_code=409, detail="campaign version changed")
        changes = payload.model_dump(exclude_none=True, exclude={"expected_version", "logo_asset_key"})
        if "logo_asset_key" in payload.model_fields_set:
            if payload.logo_asset_key is not None:
                from admaker.campaign_logo import owned_logo
                try:
                    owned_logo(connection, subject.id, payload.logo_asset_key)
                except ValueError as error:
                    raise HTTPException(422, str(error)) from None
            changes["logoAssetKey"] = str(payload.logo_asset_key) if payload.logo_asset_key else None
        brief, version = connection.execute(
            "UPDATE app.campaigns SET brief=brief || %s,version=version+1 WHERE id=%s RETURNING brief,version",
            (psycopg.types.json.Jsonb(changes), campaign_id),
        ).fetchone()
    return {"id": str(campaign_id), "brief": brief, "version": version}


@app.get("/v1/products/{product_id}/campaigns")
def list_product_campaigns(product_id: uuid.UUID, limit: int = Query(default=20, ge=1, le=100),
                           cursor: str | None = None,
                           subject: Subject = Depends(authenticated_subject)) -> dict:
    after = _parse_job_cursor(cursor) if cursor else None
    with _connection() as connection:
        if not connection.execute("SELECT id FROM app.products WHERE id=%s AND owner_id=%s", (product_id, subject.id)).fetchone():
            raise HTTPException(status_code=404, detail="product not found")
        rows = connection.execute(
            "SELECT id,image_version,brief,version,created_at FROM app.campaigns WHERE owner_id=%s AND product_id=%s "
            "AND (%s::timestamptz IS NULL OR (created_at,id)<(%s::timestamptz,%s::uuid)) "
            "ORDER BY created_at DESC,id DESC LIMIT %s",
            (subject.id, product_id, after[0] if after else None, after[0] if after else None,
             after[1] if after else None, limit + 1),
        ).fetchall()
    page = rows[:limit]
    return {"items": [{"id": str(row[0]), "productId": str(product_id), "imageVersion": row[1],
                       "brief": row[2], "version": row[3], "createdAt": row[4].isoformat()} for row in page],
            "nextCursor": _job_cursor(page[-1][4], page[-1][0]) if len(rows) > limit else None}


class AIConsentRequest(BaseModel):
    granted: bool
    disclosure_version: str = Field(alias="disclosureVersion")


@app.get("/v1/account/ai-consent")
def get_ai_consent(subject: Subject = Depends(authenticated_subject)) -> dict:
    from admaker.consent import DISCLOSURE, DISCLOSURE_VERSION

    with _connection() as connection:
        row = connection.execute("SELECT granted,disclosure_version FROM app.ai_consent WHERE account_id=%s", (subject.id,)).fetchone()
    return {"granted": bool(row and row[0] and row[1] == DISCLOSURE_VERSION),
            "disclosureVersion": DISCLOSURE_VERSION, "disclosure": DISCLOSURE}


@app.put("/v1/account/ai-consent")
def set_ai_consent(payload: AIConsentRequest, subject: Subject = Depends(authenticated_subject)) -> dict:
    from admaker.consent import DISCLOSURE_VERSION

    if payload.granted and payload.disclosure_version != DISCLOSURE_VERSION:
        raise HTTPException(status_code=409, detail="AI disclosure has changed")
    if payload.granted:
        from admaker.eligibility import require_eligibility
        require_eligibility(subject.id)
    _account(subject)
    with _connection() as connection:
        connection.execute(
            "INSERT INTO app.ai_consent(account_id,disclosure_version,granted) VALUES (%s,%s,%s) "
            "ON CONFLICT(account_id) DO UPDATE SET disclosure_version=EXCLUDED.disclosure_version,granted=EXCLUDED.granted,updated_at=now()",
            (subject.id, DISCLOSURE_VERSION, payload.granted),
        )
    return {"granted": payload.granted, "disclosureVersion": DISCLOSURE_VERSION}


@app.get("/v1/catalogue")
def get_catalogue(category: str | None = None, outputKind: str | None = None,
                  subject: Subject = Depends(authenticated_subject)) -> dict:
    from admaker.catalogue import CATEGORIES, catalogue_items
    from admaker.catalogue_execution import catalogue_execution

    try:
        items = catalogue_items(category, outputKind)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return {"modes": catalogue_execution(), "categories": [{"id": key, "name": value} for key, value in CATEGORIES.items()],
            "items": items, "status": "development", "executionMode": "fixture", "requiresAiConsent": False,
            "generationEnabled": os.environ.get("ENABLE_LOCAL_FIXTURE_UI") == "true" and os.environ.get("ENABLE_REAL_VEO") != "true",
            "prices": {"photo": 1, "video": 1},
            "formats": {"photo": "image/png", "video": "video/mp4"},
            "supportedPlatforms": sorted(PUBLIC_PLATFORMS)}


@app.get("/v1/assets/{asset_key}")
def get_verified_asset(asset_key: uuid.UUID, subject: Subject = Depends(authenticated_subject)) -> Response:
    with _connection() as connection:
        row = connection.execute(
            "SELECT storage_key, mime_type FROM app.assets WHERE asset_key=%s AND owner_id=%s AND verification_state='verified'",
            (asset_key, subject.id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="asset not found")
    from admaker.cloud_objects import private_object_download_url
    try:
        cloud_url = private_object_download_url(os.environ["DATABASE_URL"], subject.id, row[0])
    except (OSError, ValueError):
        raise HTTPException(503, "Private image download is unavailable") from None
    if cloud_url:
        return RedirectResponse(cloud_url, status_code=302, headers={"Cache-Control": "private, no-store"})
    if not _storage().path(row[0]).is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(_storage().path(row[0]), media_type=row[1], headers={"Cache-Control": "private, no-store"})


class SavePhotoAssetRequest(BaseModel):
    expected_result_version: str = Field(alias="expectedResultVersion", pattern="^[a-f0-9]{64}$")
    platform: str = Field(pattern="^(feed|feed_square|tiktok|reels|stories)$")


@app.post("/v1/jobs/{job_id}/photo-asset")
def save_photo_asset(job_id: uuid.UUID, payload: SavePhotoAssetRequest,
                     subject: Subject = Depends(authenticated_subject)) -> dict:
    from admaker.cloud_objects import stage_private_object
    from admaker.veo import read_video_image, image_mime_type
    with _connection() as connection:
        lock_media_writer(connection, subject.id)
        job = connection.execute("SELECT state,settings,result FROM app.jobs WHERE id=%s AND owner_id=%s FOR SHARE",
                                 (job_id, subject.id)).fetchone()
        if not job:
            raise HTTPException(404, "job not found")
        if job[0] != "delivered" or job[1].get("outputKind") != "photo":
            raise HTTPException(409, "A delivered photo is required")
        if hashlib.sha256(json.dumps(job[2], sort_keys=True).encode()).hexdigest() != payload.expected_result_version:
            raise HTTPException(409, "Result changed; refresh before saving")
        exports = job[2].get("exports", {})
        item = exports.get(payload.platform) or exports.get("feed_square" if payload.platform == "feed" else payload.platform) or {}
        key, checksum = item.get("key"), item.get("sha256")
        if not isinstance(key, str) or not isinstance(checksum, str) or not re.fullmatch("[a-f0-9]{64}", checksum):
            raise HTTPException(409, "A verified photo export is required")
        root = _storage().root.resolve()
        path = root / key
        if not path.resolve().is_relative_to(root) or any(p.is_symlink() for p in [path, *path.parents] if p != root and p.is_relative_to(root)):
            raise HTTPException(409, "Photo export is unavailable")
        try:
            stage_private_object(os.environ["DATABASE_URL"], subject.id, key, root)
            content = read_video_image(path)
            mime = image_mime_type(content)
        except (OSError, ValueError):
            raise HTTPException(503, "Photo export is unavailable") from None
        if hashlib.sha256(content).hexdigest() != checksum or mime != item.get("mimeType"):
            raise HTTPException(409, "Photo export content changed")
        asset = uuid.uuid5(job_id, key)
        connection.execute("""INSERT INTO app.assets(asset_key,owner_id,storage_key,mime_type,size_bytes,checksum,verification_state,verified_at)
            VALUES (%s,%s,%s,%s,%s,%s,'verified',clock_timestamp()) ON CONFLICT(storage_key) DO NOTHING""",
            (asset, subject.id, key, mime, len(content), checksum))
        saved = connection.execute("SELECT asset_key FROM app.assets WHERE storage_key=%s AND owner_id=%s AND checksum=%s AND verification_state='verified'",
                                   (key, subject.id, checksum)).fetchone()
        if not saved:
            raise HTTPException(409, "Photo asset ownership or content changed")
    return {"assetKey": str(saved[0])}


class ResultReportRequest(BaseModel):
    attempt_sequence: int | None = Field(default=None, alias="attemptSequence", ge=1, strict=True)
    expected_result_version: str = Field(alias="expectedResultVersion", pattern="^[a-f0-9]{64}$")
    reason: str = Field(pattern="^(unsafe_content|product_accuracy|rights|other)$")
    details: str = Field(default="", max_length=1000)


@app.post("/v1/jobs/{job_id}/reports", status_code=status.HTTP_201_CREATED)
def report_result(job_id: uuid.UUID, payload: ResultReportRequest, request: Request,
                  subject: Subject = Depends(authenticated_subject)) -> dict:
    key = request.headers.get("Idempotency-Key", "")
    if not 1 <= len(key) <= 200:
        raise HTTPException(status_code=422, detail="Idempotency-Key between 1 and 200 characters is required")
    request_hash = hashlib.sha256((str(job_id) + payload.model_dump_json(exclude_none=True)).encode()).hexdigest()
    with _connection() as connection:
        connection.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (subject.id,))
        existing = connection.execute("SELECT request_hash,response FROM app.command_keys WHERE account_id=%s AND route='result-report' AND key=%s", (subject.id, key)).fetchone()
        if existing:
            if existing[0] != request_hash:
                raise HTTPException(status_code=409, detail="idempotency key payload mismatch")
            return existing[1]
        job = connection.execute("SELECT active_run_id,result FROM app.jobs WHERE id=%s AND owner_id=%s FOR SHARE", (job_id, subject.id)).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        if payload.attempt_sequence is not None:
            run = connection.execute("SELECT id FROM app.job_runs WHERE job_id=%s AND sequence=%s", (job_id, payload.attempt_sequence)).fetchone()
            if not run:
                raise HTTPException(404, "generation attempt not found")
            job = (run[0], job[1].get("runs", {}).get(str(payload.attempt_sequence), {}))
        if not job[1].get("exports"):
            raise HTTPException(status_code=409, detail="this job has no result to report")
        if hashlib.sha256(json.dumps(job[1], sort_keys=True).encode()).hexdigest() != payload.expected_result_version:
            raise HTTPException(status_code=409, detail="result changed; refresh the result before reporting")
        report_id = uuid.uuid4()
        connection.execute(
            "INSERT INTO app.result_reports(id,owner_id,job_id,run_id,result_snapshot,reason,details) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (report_id, subject.id, job_id, job[0], psycopg.types.json.Jsonb(job[1]), payload.reason, payload.details),
        )
        response = {"id": str(report_id), "jobId": str(job_id), "status": "open"}
        connection.execute("INSERT INTO app.command_keys(account_id,route,key,request_hash,response) VALUES (%s,'result-report',%s,%s,%s)",
                           (subject.id, key, request_hash, psycopg.types.json.Jsonb(response)))
    return response


@app.get("/v1/jobs/{job_id}/reports")
def list_result_reports(job_id: uuid.UUID, subject: Subject = Depends(authenticated_subject)) -> dict:
    with _connection() as connection:
        if not connection.execute("SELECT id FROM app.jobs WHERE id=%s AND owner_id=%s", (job_id, subject.id)).fetchone():
            raise HTTPException(status_code=404, detail="job not found")
        rows = connection.execute(
            "SELECT id,reason,details,status,resolution,created_at FROM app.result_reports WHERE job_id=%s AND owner_id=%s ORDER BY created_at DESC,id DESC LIMIT 50",
            (job_id, subject.id),
        ).fetchall()
    return {"items": [{"id": str(row[0]), "reason": row[1], "details": row[2], "status": row[3],
                       "resolution": row[4], "createdAt": row[5].isoformat()} for row in rows]}


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
