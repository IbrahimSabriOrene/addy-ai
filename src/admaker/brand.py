"""Private brand defaults; campaigns keep explicit snapshots of these fields."""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from psycopg.types.json import Jsonb

from admaker.auth import Subject, authenticated_subject
from admaker.campaign_logo import owned_logo
from admaker.media_drain import lock_media_writer

router = APIRouter()


class BrandProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="", max_length=100)
    color: str = Field(default="#FFFFFF", pattern=r"^#[0-9a-fA-F]{6}$")
    font: Literal["sans", "serif"] = "sans"
    contact: str = Field(default="", max_length=100, pattern=r"^[^\x00-\x1f\x7f]*$")
    logoAssetKey: uuid.UUID | None = None


class BrandUpdate(BrandProfile):
    expectedVersion: int = Field(ge=0, strict=True)


@router.get("/v1/account/brand")
def get_brand(subject: Subject = Depends(authenticated_subject)):
    from admaker.api import _connection
    with _connection() as connection:
        row = connection.execute("SELECT profile,version FROM app.brand_profiles WHERE account_id=%s", (subject.id,)).fetchone()
    return {"profile": row[0] if row else BrandProfile().model_dump(mode="json"), "version": row[1] if row else 0}


@router.put("/v1/account/brand")
def save_brand(payload: BrandUpdate, subject: Subject = Depends(authenticated_subject)):
    from admaker.api import _connection
    with _connection() as connection:
        lock_media_writer(connection, subject.id)
        if not connection.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (subject.id,)).fetchone():
            raise HTTPException(404, "Account not found")
        row = connection.execute("SELECT version FROM app.brand_profiles WHERE account_id=%s", (subject.id,)).fetchone()
        version = row[0] if row else 0
        if payload.expectedVersion != version:
            raise HTTPException(409, "Brand profile changed. Reload before saving.")
        if payload.logoAssetKey:
            try:
                owned_logo(connection, subject.id, payload.logoAssetKey)
            except ValueError as error:
                raise HTTPException(422, str(error)) from None
        profile = payload.model_dump(mode="json", exclude={"expectedVersion"})
        connection.execute(
            "INSERT INTO app.brand_profiles(account_id,profile,version) VALUES (%s,%s,1) "
            "ON CONFLICT(account_id) DO UPDATE SET profile=EXCLUDED.profile,version=app.brand_profiles.version+1",
            (subject.id, Jsonb(profile)),
        )
    return {"profile": profile, "version": version + 1}
