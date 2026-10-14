import time
import uuid
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from admaker.auth import verify_access_token


def test_signed_tokens_require_valid_identity_and_expiry(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("SUPABASE_JWKS_URL", "https://auth.example.test/jwks")
    monkeypatch.setenv("SUPABASE_ISSUER", "https://auth.example.test")
    monkeypatch.setenv("SUPABASE_AUDIENCE", "authenticated")
    monkeypatch.setattr("admaker.auth._jwks", lambda url: SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=private.public_key())
    ))
    claims = {"sub": str(uuid.uuid4()), "email": "merchant@example.com",
              "iss": "https://auth.example.test", "aud": "authenticated",
              "exp": int(time.time()) + 300}
    assert verify_access_token(jwt.encode(claims, private, algorithm="RS256")).id == claims["sub"]
    invalid = [dict(claims, exp=1), dict(claims, iss="wrong"),
               dict(claims, aud="wrong"), dict(claims, sub="not-a-uuid"),
               dict(claims, email=["unexpected"])]
    invalid.extend({key: value for key, value in claims.items() if key != missing}
                   for missing in ("exp", "iss", "aud", "sub"))
    for payload in invalid:
        with pytest.raises(HTTPException) as error:
            verify_access_token(jwt.encode(payload, private, algorithm="RS256"))
        assert error.value.status_code == 401
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for token in (jwt.encode(claims, other_key, algorithm="RS256"),
                  jwt.encode(claims, "untrusted-secret", algorithm="HS256")):
        with pytest.raises(HTTPException) as error:
            verify_access_token(token)
        assert error.value.status_code == 401
