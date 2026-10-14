"""Supabase access-token verification; no development authentication bypass."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Header, HTTPException, Request, status


@dataclass(frozen=True)
class Subject:
    id: str
    email: str


@lru_cache
def _jwks(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=False, lifespan=300, timeout=5)


def verify_access_token(token: str) -> Subject:
    jwks_url = os.environ.get("SUPABASE_JWKS_URL")
    issuer = os.environ.get("SUPABASE_ISSUER")
    audience = os.environ.get("SUPABASE_AUDIENCE")
    if not all((jwks_url, issuer, audience)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication is not configured")
    try:
        key = _jwks(jwks_url).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token, key, algorithms=["RS256", "ES256"], issuer=issuer, audience=audience,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
        subject_id = str(uuid.UUID(claims["sub"]))
        email = claims.get("email") or ""
        if not isinstance(email, str):
            raise ValueError("invalid email claim")
        return Subject(id=subject_id, email=email)
    except (jwt.PyJWTError, KeyError, ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid access token") from None


def authenticated_subject(request: Request, authorization: str | None = Header(default=None)) -> Subject:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    subject = verify_access_token(authorization.removeprefix("Bearer "))
    from admaker.account_deletion import deletion_requested
    if deletion_requested(subject.id):
        raise HTTPException(410, "Account deletion has been requested")
    from admaker.rate_limit import enforce_account_rate_limit
    enforce_account_rate_limit(subject.id)
    # Read access, erasure and consent withdrawal must not require accepting an age statement.
    reporting = request.method == "POST" and request.url.path.startswith("/v1/jobs/") and request.url.path.endswith("/reports")
    if not reporting and request.method not in {"GET", "HEAD", "OPTIONS", "DELETE"} and request.url.path not in {
        "/v1/account/eligibility", "/v1/account/ai-consent", "/v1/account/deletion",
        "/v1/credits/purchases/status",
    }:
        from admaker.eligibility import require_eligibility
        require_eligibility(subject.id)
    return subject
