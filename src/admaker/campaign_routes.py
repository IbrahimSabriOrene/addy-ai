"""Owner-only deterministic layouts, separate from paid campaign generation."""
import uuid
import hashlib
import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from admaker.auth import Subject, authenticated_subject
from admaker.campaign_layouts import render_campaign_layouts
from admaker.campaign_failure import campaign_failure
from admaker.media_drain import lock_media_writer

router = APIRouter()

PACK_MEDIA_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "video/mp4": "mp4"}


def campaign_pack_configuration():
    import os
    import re

    price, queue = os.environ.get("CAMPAIGN_PACK_CREDITS", ""), os.environ.get("CAMPAIGN_PACK_QUEUE", "")
    if (os.environ.get("ENABLE_CAMPAIGN_PACKS") != "true" or not price.isdecimal()
            or not 0 < int(price) <= 10000 or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,47}", queue)):
        return None, None
    return int(price), queue


class CampaignGenerateRequest(BaseModel):
    expected_version: int = Field(alias="expectedVersion", ge=1, strict=True)
    confirmed_credits: int = Field(alias="confirmedCredits", ge=1, le=10000, strict=True)


@router.post("/v1/campaigns/{campaign_id}/generate/close")
def close_pending_campaign_command(campaign_id: uuid.UUID, payload: CampaignGenerateRequest, request: Request,
                                   subject: Subject = Depends(authenticated_subject)):
    from admaker.api import _connection
    from admaker.campaign_commands import close_campaign_command

    with _connection() as connection:
        try:
            return close_campaign_command(connection, campaign_id, subject.id, payload.expected_version,
                                          payload.confirmed_credits, request.headers.get("Idempotency-Key", ""))
        except LookupError as error:
            raise HTTPException(404, str(error)) from None
        except ValueError as error:
            raise HTTPException(409, str(error)) from None


def campaign_pack_quote():
    price, _ = campaign_pack_configuration()
    return {"available": price is not None, "priceCredits": price, "scope": "campaign_pack",
            "outputs": ["cleanImage", "video", "story", "feed", "copy"],
            "settlement": "Credits are reserved when you generate and spent when the complete pack is delivered or you accept it. Incomplete work may need review; reserved credits remain held until it is completed or closed."}


@router.get("/v1/campaign-pack/quote")
def quote_new_campaign_pack(subject: Subject = Depends(authenticated_subject)):
    return campaign_pack_quote()


@router.get("/v1/campaigns/{campaign_id}/generation-quote")
def quote_campaign_generation(campaign_id: uuid.UUID, subject: Subject = Depends(authenticated_subject)):
    from admaker.api import _connection

    with _connection() as connection:
        row = connection.execute("SELECT version FROM app.campaigns WHERE id=%s AND owner_id=%s", (campaign_id, subject.id)).fetchone()
    if not row:
        raise HTTPException(404, "campaign not found")
    return {"campaignId": str(campaign_id), "campaignVersion": row[0], **campaign_pack_quote()}


@router.post("/v1/campaigns/{campaign_id}/generate", status_code=202)
def generate_campaign(campaign_id: uuid.UUID, payload: CampaignGenerateRequest, request: Request,
                      subject: Subject = Depends(authenticated_subject)):
    from admaker.api import _connection
    from admaker.campaign_generation import admit_campaign_generation
    from admaker.consent import require_ai_consent

    key = request.headers.get("Idempotency-Key", "")
    if not 1 <= len(key) <= 200:
        raise HTTPException(422, "Valid Idempotency-Key required")
    price, queue = campaign_pack_configuration()
    with _connection() as connection:
        previous = connection.execute("SELECT 1 FROM app.command_keys WHERE account_id=%s AND route='campaign-generate' AND key=%s", (subject.id, key)).fetchone()
        if not previous:
            if price is None:
                raise HTTPException(503, "Campaign generation is not available yet")
            try:
                require_ai_consent(subject.id)
            except PermissionError:
                raise HTTPException(403, "Current AI-processing permission is required") from None
        try:
            result = admit_campaign_generation(connection, campaign_id, subject.id, payload.expected_version, key,
                price_credits=price, confirmed_credits=payload.confirmed_credits, queue=queue)
            if result.get("state") == "cancelled":
                raise HTTPException(409, "This saved request was closed; review the current price before starting a new request")
            return result
        except LookupError as error:
            raise HTTPException(404, str(error)) from None
        except ValueError as error:
            raise HTTPException(409, str(error)) from None


@router.get("/v1/campaigns/{campaign_id}/generations")
def list_campaign_generations(campaign_id: uuid.UUID, limit: int = Query(default=20, ge=1, le=100),
                              before_version: int | None = Query(default=None, alias="beforeVersion", ge=1),
                              subject: Subject = Depends(authenticated_subject)):
    from admaker.api import _connection

    with _connection() as connection:
        if not connection.execute("SELECT id FROM app.campaigns WHERE id=%s AND owner_id=%s", (campaign_id, subject.id)).fetchone():
            raise HTTPException(404, "campaign not found")
        rows = connection.execute(
            "SELECT g.campaign_version,g.job_id,g.price_credits,g.created_at,j.state FROM app.campaign_generations g "
            "JOIN app.jobs j ON j.id=g.job_id WHERE g.campaign_id=%s AND j.owner_id=%s "
            "AND (%s::integer IS NULL OR g.campaign_version<%s) ORDER BY g.campaign_version DESC LIMIT %s",
            (campaign_id, subject.id, before_version, before_version, limit + 1),
        ).fetchall()
    return {"items": [{"version": row[0], "jobId": str(row[1]), "priceCredits": row[2],
                       "createdAt": row[3].isoformat(), "jobState": row[4]} for row in rows[:limit]],
            "nextBeforeVersion": rows[limit - 1][0] if len(rows) > limit else None}


def owned_campaign_generation(connection, campaign_id, version, owner_id):
    row = connection.execute(
        "SELECT g.job_id,g.price_credits,j.state,j.result FROM app.campaign_generations g "
        "JOIN app.campaigns c ON c.id=g.campaign_id JOIN app.jobs j ON j.id=g.job_id "
        "WHERE c.id=%s AND c.owner_id=%s AND j.owner_id=c.owner_id AND g.campaign_version=%s",
        (campaign_id, owner_id, version),
    ).fetchone()
    if not row:
        raise HTTPException(404, "campaign generation not found")
    return row


def campaign_attempt_result(connection, job, result, sequence):
    row = connection.execute("SELECT state FROM app.job_runs WHERE job_id=%s AND sequence=%s", (job, sequence)).fetchone()
    if not row:
        raise HTTPException(404, "campaign attempt not found")
    saved = result.get("runs", {}).get(str(sequence), {})
    # Only worker-published, policy-reviewed exports enter runs; raw stages stay private.
    return ("archived" if saved.get("exports") else row[0]), saved


@router.get("/v1/campaigns/{campaign_id}/generations/{version}")
def get_campaign_generation(campaign_id: uuid.UUID, version: int, subject: Subject = Depends(authenticated_subject),
                            attempt: int | None = Query(default=None, ge=1)):
    from admaker.api import _connection, _storage

    with _connection() as connection:
        job, price, state, result = owned_campaign_generation(connection, campaign_id, version, subject.id)
        attempts = connection.execute("SELECT sequence,state FROM app.job_runs WHERE job_id=%s ORDER BY sequence DESC", (job,)).fetchall()
        if attempt is not None:
            state, result = campaign_attempt_result(connection, job, result, attempt)
    root = _storage().root.resolve()
    manifest = result.get("exports", {}) if state in {"delivered", "awaiting_user_decision", "archived"} else {}
    media_keys = [item['key'] for item in manifest.values() if isinstance(item, dict) and isinstance(item.get('key'), str)]
    with _connection() as connection:
        cloud_keys = {row[0] for row in connection.execute("SELECT local_key FROM app.cloud_objects WHERE account_id=%s AND local_key=ANY(%s::text[]) AND state='ready'", (subject.id, media_keys))}
    outputs = {}
    for kind in ("cleanImage", "video", "story", "feed", "copy"):
        item = manifest.get(kind, {})
        ready = False
        projected = {}
        if kind == "copy":
            ready = isinstance(item.get("caption"), str) and isinstance(item.get("cta"), str)
            if ready:
                projected = {"caption": item["caption"], "cta": item["cta"]}
        elif isinstance(item.get("key"), str) and item.get("mimeType") in PACK_MEDIA_TYPES:
            path = (root / item["key"]).resolve()
            ready = item['key'] in cloud_keys or (path.is_relative_to(root) and path.is_file() and path.stat().st_size > 0)
            if ready:
                projected = {key: item[key] for key in ("mimeType", "width", "height", "duration", "hasAudio", "offer", "cta") if key in item}
                projected["url"] = f"/v1/campaigns/{campaign_id}/generations/{version}/{kind}" + (f"?attempt={attempt}" if attempt is not None else "")
        outputs[kind] = {"state": "ready" if ready else "unavailable" if state in {"delivered", "failed", "aborted", "awaiting_user_decision", "archived"} else "pending", **projected}
    complete = all(item["state"] == "ready" for item in outputs.values())
    return {"campaignId": str(campaign_id), "campaignVersion": version, "jobId": str(job),
            "priceCredits": price, "jobState": state, "attemptSequence": attempt,
            "attempts": [{"sequence": seq, "state": status} for seq, status in attempts],
            "resultVersion": hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest(),
            "failure": campaign_failure(state, result),
            "state": "delivered" if state == "delivered" and complete else "incomplete" if state == "delivered" else state,
            "outputs": outputs}


@router.get("/v1/campaigns/{campaign_id}/generations/{version}/{kind}")
def download_campaign_output(campaign_id: uuid.UUID, version: int, kind: str, subject: Subject = Depends(authenticated_subject),
                             attempt: int | None = Query(default=None, ge=1)):
    from admaker.api import _connection, _storage

    if kind not in {"cleanImage", "video", "story", "feed"}:
        raise HTTPException(404, "campaign output not found")
    with _connection() as connection:
        job, _, state, result = owned_campaign_generation(connection, campaign_id, version, subject.id)
        if attempt is not None:
            state, result = campaign_attempt_result(connection, job, result, attempt)
    item = result.get("exports", {}).get(kind, {}) if state in {"delivered", "awaiting_user_decision", "archived"} else {}
    if not isinstance(item.get("key"), str) or item.get("mimeType") not in PACK_MEDIA_TYPES:
        raise HTTPException(404, "campaign output not found")
    from admaker.cloud_objects import private_object_download_url
    try:
        cloud_url = private_object_download_url(os.environ["DATABASE_URL"], subject.id, item['key'])
    except (OSError, ValueError):
        raise HTTPException(503, "Private campaign download is unavailable") from None
    if cloud_url:
        return RedirectResponse(cloud_url, status_code=302, headers={"Cache-Control": "private, no-store"})
    root = _storage().root.resolve()
    path = (root / item["key"]).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size == 0:
        raise HTTPException(404, "campaign output not found")
    if "sha256" in item:
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                raise HTTPException(503, "Private campaign integrity could not be verified")
    return FileResponse(path, media_type=item["mimeType"], filename=f"addy-{kind}.{PACK_MEDIA_TYPES[item['mimeType']]}", headers={"Cache-Control": "private, no-store"})


class LayoutRequest(BaseModel):
    expected_version: int = Field(alias="expectedVersion", ge=1, strict=True)


def layout_response(campaign_id, version, manifest):
    return {"version": version, "state": "ready", "outputs": {
        kind: {**{k: v for k, v in value.items() if k != "key"},
               "url": f"/v1/campaigns/{campaign_id}/layouts/{version}/{kind}"}
        for kind, value in manifest.items()}}


@router.get("/v1/campaigns/{campaign_id}/layouts")
def get_layouts(campaign_id: uuid.UUID, subject: Subject = Depends(authenticated_subject)):
    from admaker.api import _connection

    with _connection() as connection:
        row = connection.execute("SELECT c.version,l.manifest FROM app.campaigns c LEFT JOIN app.campaign_layouts l ON l.campaign_id=c.id AND l.version=c.version WHERE c.id=%s AND c.owner_id=%s", (campaign_id, subject.id)).fetchone()
    if not row:
        raise HTTPException(404, "campaign not found")
    return layout_response(campaign_id, row[0], row[1]) if row[1] else {"version": row[0], "state": "not_generated", "outputs": {}}


@router.post("/v1/campaigns/{campaign_id}/layouts")
def create_layouts(campaign_id: uuid.UUID, payload: LayoutRequest, subject: Subject = Depends(authenticated_subject)):
    from admaker.api import _connection, _storage

    with _connection() as connection:
        lock_media_writer(connection, subject.id)
        row = connection.execute("SELECT c.version,c.brief,a.storage_key,a.verification_state,a.owner_id FROM app.campaigns c JOIN app.product_images i ON i.product_id=c.product_id AND i.version=c.image_version JOIN app.assets a ON a.asset_key=i.asset_key WHERE c.id=%s AND c.owner_id=%s FOR UPDATE OF c", (campaign_id, subject.id)).fetchone()
        if not row:
            raise HTTPException(404, "campaign not found")
        if row[0] != payload.expected_version:
            raise HTTPException(409, "campaign version changed")
        saved = connection.execute("SELECT manifest FROM app.campaign_layouts WHERE campaign_id=%s AND version=%s", (campaign_id, row[0])).fetchone()
        if saved:
            return publish_layout_response(campaign_id, row[0], saved[0], subject.id)
        if row[3] != "verified" or str(row[4]) != subject.id:
            raise HTTPException(409, "approved image is unavailable")
        root = _storage().root.resolve()
        source = (root / row[2]).resolve()
        if not source.is_relative_to(root):
            raise HTTPException(409, "approved image is unavailable")
        destination = root / "campaigns" / str(campaign_id) / str(row[0]) / str(uuid.uuid4())
        try:
            from admaker.cloud_objects import stage_private_object
            stage_private_object(os.environ["DATABASE_URL"], subject.id, row[2], root)
            from admaker.campaign_logo import stage_campaign_logo
            logo = stage_campaign_logo(connection, subject.id, row[1], root)
            outputs = render_campaign_layouts(source, destination, row[1], **({"logo": logo} if logo else {}))
        except (OSError, ValueError) as error:
            raise HTTPException(422, "campaign layout could not be rendered; check the image, text and font") from error
        manifest = {kind: {**{k: v for k, v in value.items() if k != "path"},
                           "key": Path(value["path"]).relative_to(root).as_posix(),
                           "sha256": hashlib.sha256(Path(value["path"]).read_bytes()).hexdigest()} for kind, value in outputs.items()}
        connection.execute("INSERT INTO app.campaign_layouts(campaign_id,version,manifest) VALUES (%s,%s,%s)", (campaign_id, row[0], Jsonb(manifest)))
    return publish_layout_response(campaign_id, row[0], manifest, subject.id)


def publish_layout_response(campaign_id, version, manifest, account_id):
    from admaker.api import _connection, _storage
    from admaker.cloud_objects import publish_account_outputs
    if os.environ.get("PUBLISH_PRIVATE_OUTPUTS") == "true":
        with _connection() as connection:
            lock_media_writer(connection, account_id)
            try:
                publish_account_outputs(os.environ["DATABASE_URL"], account_id, _storage().root, manifest)
            except (OSError, ValueError):
                raise HTTPException(503, "Layout upload is unconfirmed; retry the same campaign version") from None
    return layout_response(campaign_id, version, manifest)


@router.get("/v1/campaigns/{campaign_id}/layouts/{version}/{kind}")
def download_layout(campaign_id: uuid.UUID, version: int, kind: str, subject: Subject = Depends(authenticated_subject)):
    from admaker.api import _connection, _storage

    with _connection() as connection:
        row = connection.execute("SELECT l.manifest FROM app.campaign_layouts l JOIN app.campaigns c ON c.id=l.campaign_id WHERE c.id=%s AND c.owner_id=%s AND l.version=%s", (campaign_id, subject.id, version)).fetchone()
    item = row[0].get(kind) if row else None
    if not item:
        raise HTTPException(404, "layout not found")
    if not isinstance(item.get("key"), str):
        raise HTTPException(404, "layout not found")
    from admaker.cloud_objects import private_object_download_url
    try:
        cloud_url = private_object_download_url(os.environ["DATABASE_URL"], subject.id, item["key"])
    except (OSError, ValueError):
        raise HTTPException(503, "Private layout download is unavailable") from None
    if cloud_url:
        return RedirectResponse(cloud_url, status_code=302, headers={"Cache-Control": "private, no-store"})
    root = _storage().root.resolve()
    path = (root / item["key"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, "layout not found")
    if "sha256" in item:
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                raise HTTPException(503, "Private layout integrity could not be verified")
    mime = item.get("mimeType")
    if kind not in {"story", "feed", "video"} or mime not in {"image/png", "video/mp4"}:
        raise HTTPException(404, "layout not found")
    return FileResponse(path, media_type=mime, filename=f"{kind}.{PACK_MEDIA_TYPES[mime]}", headers={"Cache-Control": "private, no-store"})


class VideoLayoutRequest(BaseModel):
    expected_version: int = Field(alias="expectedVersion", ge=1, strict=True)
    source_version: int = Field(alias="sourceVersion", ge=1, strict=True)


@router.post("/v1/campaigns/{campaign_id}/video-layout")
def create_video_layout(campaign_id: uuid.UUID, payload: VideoLayoutRequest, subject: Subject = Depends(authenticated_subject)):
    import subprocess
    from admaker.api import _connection, _storage
    from admaker.campaign_video_source import delivered_video_source
    from admaker.campaign_video import render_campaign_video
    from admaker.cloud_objects import stage_private_object

    with _connection() as connection:
        lock_media_writer(connection, subject.id)
        campaign = connection.execute("SELECT version,product_id,image_version,brief,style_snapshot FROM app.campaigns WHERE id=%s AND owner_id=%s FOR UPDATE", (campaign_id, subject.id)).fetchone()
        if not campaign:
            raise HTTPException(404, "campaign not found")
        version, product, image_version, brief, style = campaign
        if version != payload.expected_version:
            raise HTTPException(409, "Campaign changed. Save and reload before editing video.")
        saved = connection.execute("SELECT manifest FROM app.campaign_layouts WHERE campaign_id=%s AND version=%s", (campaign_id, version)).fetchone()
        if not saved or not {"story", "feed"} <= set(saved[0]):
            raise HTTPException(409, "Prepare story and feed images for this version first.")
        manifest = saved[0]
        if "video" in manifest:
            if manifest["video"].get("sourceVersion") != payload.source_version:
                raise HTTPException(409, "This version already uses another source video. Save a new campaign version to change it.")
        else:
            job, _, _, _ = owned_campaign_generation(connection, campaign_id, payload.source_version, subject.id)
            settings = connection.execute("SELECT settings FROM app.jobs WHERE id=%s", (job,)).fetchone()[0]
            style = style or {}
            if (settings.get("productId") != str(product) or settings.get("imageVersion") != image_version
                    or settings.get("templateId") != style.get("id") or settings.get("templateVersion") != style.get("version")
                    or settings.get("campaignBrief", {}).get("instructions", "") != brief.get("instructions", "")):
                raise HTTPException(409, "The source video uses a different product, style or direction. Choose a matching delivered video.")
            try:
                source = delivered_video_source(connection, job, subject.id)
            except ValueError:
                raise HTTPException(409, "A matching delivered video is unavailable.") from None
            review = connection.execute("SELECT result FROM app.job_stages WHERE run_id=%s AND stage_key='candidate_review'", (source["runId"],)).fetchone()
            provider_exports = connection.execute("SELECT result FROM app.job_stages WHERE run_id=%s AND stage_key='provider_compose'", (source["runId"],)).fetchone()[0]
            if (not review or review[0].get("offerFree") is not True or review[0].get("policyAllowed") is not True
                    or review[0].get("technicalPassed") is not True or not isinstance(review[0].get("sourceSha256"), str)
                    or review[0].get("exportsHash") != hashlib.sha256(json.dumps(provider_exports, sort_keys=True).encode()).hexdigest()):
                raise HTTPException(409, "This video's picture and speech have not been verified free of old offers. Video editing is unavailable; any new paid generation needs separate confirmation.")
            root = _storage().root.resolve()
            path = (root / source["key"]).resolve()
            try:
                stage_private_object(os.environ["DATABASE_URL"], subject.id, source["key"], root)
                if (not path.is_relative_to(root) or not path.is_file() or not 0 < path.stat().st_size <= 100 * 1024 * 1024
                        or hashlib.sha256(path.read_bytes()).hexdigest() != review[0]["sourceSha256"]):
                    raise ValueError("Reviewed source changed")
                destination = root / "campaigns" / str(campaign_id) / str(version) / str(uuid.uuid4())
                from admaker.campaign_logo import stage_campaign_logo
                logo = stage_campaign_logo(connection, subject.id, brief, root)
                output = render_campaign_video(path, destination, brief, **({"logo": logo} if logo else {}))
                rendered = Path(output["path"]).resolve()
                if not rendered.is_relative_to(destination.resolve()):
                    raise ValueError("Invalid video output")
            except (OSError, ValueError, subprocess.SubprocessError):
                raise HTTPException(503, "Video layout could not be prepared. No credits were spent; retry this version.") from None
            manifest["video"] = {**{key: value for key, value in output.items() if key != "path"},
                                 "key": rendered.relative_to(root).as_posix(), "sourceVersion": payload.source_version,
                                 "sha256": hashlib.sha256(rendered.read_bytes()).hexdigest()}
            connection.execute("UPDATE app.campaign_layouts SET manifest=%s WHERE campaign_id=%s AND version=%s", (Jsonb(manifest), campaign_id, version))
    return publish_layout_response(campaign_id, version, manifest, subject.id)
