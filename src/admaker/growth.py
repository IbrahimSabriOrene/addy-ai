"""Private campaign outcomes, opt-in engagement preferences and minimal daily events."""
import uuid
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from psycopg.types.json import Jsonb
from admaker.auth import Subject, authenticated_subject

router = APIRouter()


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    locale: Literal["en", "tr", "pt-BR", "es"] = "en"
    completion: bool = False
    weekly: bool = False
    analytics: bool = False
    weekday: int = Field(default=0, ge=0, le=6, strict=True)
    hour: int = Field(default=10, ge=9, le=19, strict=True)
    timezone: str = Field(default="UTC", max_length=80)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Choose an IANA time zone, such as Europe/Istanbul") from None
        return value


class PreferenceUpdate(Preferences):
    expectedVersion: int = Field(ge=0, strict=True)


class LanguageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    locale: Literal["en", "tr", "pt-BR", "es"]


@router.put("/v1/account/language")
def save_language(payload: LanguageUpdate, subject: Subject = Depends(authenticated_subject)):
    from admaker.api import _connection
    with _connection() as c:
        lock_account(c, subject.id)
        # A language change never opts in, restarts notification collection, or
        # overwrites the consent/schedule saved on another device.
        c.execute("INSERT INTO app.growth_preferences(account_id,preferences) VALUES (%s,%s) ON CONFLICT(account_id) DO UPDATE SET preferences=app.growth_preferences.preferences || %s",
                  (subject.id, Jsonb(Preferences(locale=payload.locale).model_dump()), Jsonb({"locale": payload.locale})))
    return {"locale": payload.locale}


def lock_account(connection, account):
    if not connection.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (account,)).fetchone():
        raise HTTPException(404, "Account not found")
    if connection.execute("SELECT 1 FROM app.account_deletions WHERE account_id=%s", (account,)).fetchone():
        raise HTTPException(409, "Account deletion is in progress")


@router.get("/v1/account/engagement")
def get_preferences(subject: Subject = Depends(authenticated_subject)):
    from admaker.api import _connection
    with _connection() as c:
        row = c.execute("SELECT preferences,version FROM app.growth_preferences WHERE account_id=%s", (subject.id,)).fetchone()
    return {"preferences": row[0] if row else Preferences().model_dump(), "version": row[1] if row else 0}


@router.put("/v1/account/engagement")
def save_preferences(payload: PreferenceUpdate, subject: Subject = Depends(authenticated_subject)):
    from admaker.api import _connection
    with _connection() as c:
        lock_account(c, subject.id)
        row = c.execute("SELECT version FROM app.growth_preferences WHERE account_id=%s", (subject.id,)).fetchone()
        version = row[0] if row else 0
        if version != payload.expectedVersion:
            raise HTTPException(409, "Preferences changed. Reload before saving.")
        value = payload.model_dump(exclude={"expectedVersion"})
        c.execute("INSERT INTO app.growth_preferences(account_id,preferences) VALUES (%s,%s) ON CONFLICT(account_id) DO UPDATE SET preferences=EXCLUDED.preferences,version=app.growth_preferences.version+1,updated_at=now()", (subject.id, Jsonb(value)))
        if not value["analytics"]:
            c.execute("DELETE FROM app.growth_events WHERE account_id=%s", (subject.id,))
        for kind in ("completion", "weekly"):
            if not value[kind]:
                c.execute("DELETE FROM app.growth_notifications WHERE account_id=%s AND kind=%s", (subject.id, kind))
        if not value["completion"] and not value["weekly"]:
            c.execute("DELETE FROM app.push_devices WHERE account_id=%s", (subject.id,))
    return {"preferences": value, "version": version + 1}


class Device(BaseModel):
    token: str = Field(max_length=250, pattern=r"^(ExponentPushToken|ExpoPushToken)\[[A-Za-z0-9_-]+\]$")


@router.put("/v1/account/push-device")
def register_device(payload: Device, subject: Subject = Depends(authenticated_subject)):
    from admaker.api import _connection
    with _connection() as c:
        lock_account(c, subject.id)
        row = c.execute("SELECT preferences FROM app.growth_preferences WHERE account_id=%s", (subject.id,)).fetchone()
        if not row or not (row[0].get("completion") or row[0].get("weekly")):
            raise HTTPException(409, "Enable a notification category first")
        c.execute("INSERT INTO app.push_devices(token,account_id,expires_at) VALUES (%s,%s,now()+interval '7 days') ON CONFLICT(token) DO UPDATE SET account_id=EXCLUDED.account_id,expires_at=EXCLUDED.expires_at", (payload.token, subject.id))
    return {"registered": True}


@router.delete("/v1/account/push-device")
def unregister_device(payload: Device, subject: Subject = Depends(authenticated_subject)):
    from admaker.api import _connection
    with _connection() as c:
        c.execute("DELETE FROM app.push_devices WHERE account_id=%s AND token=%s", (subject.id, payload.token))
    return {"registered": False}


class Outcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    published: bool = False
    channel: Literal["instagram", "tiktok", "facebook", "other"] = "instagram"
    messages: int | None = Field(default=None, ge=0, le=10000000, strict=True)
    orders: int | None = Field(default=None, ge=0, le=10000000, strict=True)
    useful: bool | None = None
    expectedVersion: int = Field(ge=0, strict=True)


def owned_campaign(c, campaign, account):
    if not c.execute("SELECT id FROM app.campaigns WHERE id=%s AND owner_id=%s", (campaign, account)).fetchone():
        raise HTTPException(404, "Campaign not found")


@router.get("/v1/campaigns/{campaign_id}/outcome")
def get_outcome(campaign_id: uuid.UUID, subject: Subject = Depends(authenticated_subject)):
    from admaker.api import _connection
    with _connection() as c:
        owned_campaign(c, campaign_id, subject.id)
        row = c.execute("SELECT result,version FROM app.campaign_outcomes WHERE campaign_id=%s AND account_id=%s", (campaign_id, subject.id)).fetchone()
    return {"result": row[0] if row else Outcome(expectedVersion=0).model_dump(exclude={"expectedVersion"}), "version": row[1] if row else 0}


@router.put("/v1/campaigns/{campaign_id}/outcome")
def save_outcome(campaign_id: uuid.UUID, payload: Outcome, subject: Subject = Depends(authenticated_subject)):
    from admaker.api import _connection
    with _connection() as c:
        lock_account(c, subject.id)
        owned_campaign(c, campaign_id, subject.id)
        row = c.execute("SELECT version FROM app.campaign_outcomes WHERE campaign_id=%s", (campaign_id,)).fetchone()
        version = row[0] if row else 0
        if payload.expectedVersion != version:
            raise HTTPException(409, "Results changed. Reload before saving.")
        result = payload.model_dump(exclude={"expectedVersion"})
        c.execute("INSERT INTO app.campaign_outcomes(campaign_id,account_id,result) VALUES (%s,%s,%s) ON CONFLICT(campaign_id) DO UPDATE SET result=EXCLUDED.result,version=app.campaign_outcomes.version+1", (campaign_id, subject.id, Jsonb(result)))
    return {"result": result, "version": version + 1}


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Literal["browse", "customize", "result", "export"]


@router.post("/v1/account/engagement/events", status_code=204)
def record_event(payload: Event, subject: Subject = Depends(authenticated_subject)):
    from admaker.api import _connection
    with _connection() as c:
        lock_account(c, subject.id)
        row = c.execute("SELECT preferences FROM app.growth_preferences WHERE account_id=%s", (subject.id,)).fetchone()
        if row and row[0].get("analytics"):
            c.execute("INSERT INTO app.growth_events(account_id,name) VALUES (%s,%s) ON CONFLICT DO NOTHING", (subject.id, payload.name))


@router.get("/v1/account/engagement/stats")
def account_stats(subject: Subject = Depends(authenticated_subject)):
    from admaker.api import _connection
    with _connection() as c:
        products = c.execute("SELECT count(*) FROM app.products WHERE owner_id=%s AND deleted_at IS NULL", (subject.id,)).fetchone()[0]
        campaigns = c.execute("SELECT count(*) FROM app.campaigns WHERE owner_id=%s", (subject.id,)).fetchone()[0]
        delivered = c.execute("SELECT count(*) FROM app.jobs WHERE owner_id=%s AND state='delivered'", (subject.id,)).fetchone()[0]
        published = c.execute("SELECT count(*) FROM app.campaign_outcomes WHERE account_id=%s AND result->>'published'='true'", (subject.id,)).fetchone()[0]
    return {"products": products, "campaigns": campaigns, "delivered": delivered, "publishedSelfReported": published}


@router.get("/v1/account/notifications")
def notifications(subject: Subject = Depends(authenticated_subject)):
    from admaker.api import _connection
    from admaker.growth_worker import collect_notifications
    with _connection() as c:
        lock_account(c, subject.id)
        collect_notifications(c, subject.id)
        rows = c.execute("SELECT id,kind,created_at,read_at FROM app.growth_notifications WHERE account_id=%s ORDER BY created_at DESC LIMIT 50", (subject.id,)).fetchall()
    return {"items": [{"id": str(r[0]), "kind": r[1], "createdAt": r[2].isoformat(), "read": r[3] is not None} for r in rows]}


@router.post("/v1/account/notifications/{notification_id}/read")
def read_notification(notification_id: uuid.UUID, subject: Subject = Depends(authenticated_subject)):
    from admaker.api import _connection
    with _connection() as c:
        c.execute("UPDATE app.growth_notifications SET read_at=now() WHERE id=%s AND account_id=%s", (notification_id, subject.id))
    return {"read": True}
