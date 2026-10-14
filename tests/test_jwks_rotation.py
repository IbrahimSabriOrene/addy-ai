import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import HTTPException

from admaker.auth import _jwks, verify_access_token


def test_http_jwks_rotation_expiry_and_failure(monkeypatch):
    first = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    second = ec.generate_private_key(ec.SECP256R1())
    first_jwk = {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(first.public_key())), "kid": "first", "use": "sig", "alg": "RS256"}
    second_jwk = {**json.loads(jwt.algorithms.ECAlgorithm.to_jwk(second.public_key())), "kid": "second", "use": "sig", "alg": "ES256"}
    response = {"keys": [first_jwk]}
    requests = []
    status = 200

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            assert self.headers.get("Authorization") is None
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    issuer = f"http://127.0.0.1:{server.server_port}"
    url = f"{issuer}/jwks"
    monkeypatch.setenv("SUPABASE_JWKS_URL", url)
    monkeypatch.setenv("SUPABASE_ISSUER", issuer)
    monkeypatch.setenv("SUPABASE_AUDIENCE", "authenticated")
    claims = {"sub": str(uuid.uuid4()), "iss": issuer, "aud": "authenticated", "exp": int(time.time()) + 3600}
    first_token = jwt.encode(claims, first, algorithm="RS256", headers={"kid": "first"})
    second_token = jwt.encode(claims, second, algorithm="ES256", headers={"kid": "second"})
    try:
        assert verify_access_token(first_token).id == claims["sub"]
        assert verify_access_token(first_token).id == claims["sub"]
        assert len(requests) == 1, "Known keys use the bounded JWKS cache"
        response["keys"] = [second_jwk]
        assert verify_access_token(second_token).id == claims["sub"]
        assert len(requests) == 2, "An unknown kid refreshes the set immediately"
        with pytest.raises(HTTPException) as error:
            verify_access_token(first_token)
        assert error.value.status_code == 401, "Removed keys must not survive in an unbounded per-key cache"

        client = _jwks(url)
        assert client.timeout == 5
        assert client.jwk_set_cache.lifespan == 300
        # Expire the actual SDK cache without waiting five minutes.
        client.jwk_set_cache.jwk_set_with_timestamp.timestamp -= 301
        response["keys"] = [first_jwk]
        with pytest.raises(HTTPException) as error:
            verify_access_token(second_token)
        assert error.value.status_code == 401
        assert verify_access_token(first_token).id == claims["sub"]

        client.jwk_set_cache.jwk_set_with_timestamp.timestamp -= 301
        status = 503
        with pytest.raises(HTTPException) as error:
            verify_access_token(first_token)
        assert error.value.status_code == 401, "No stale fallback after JWKS expiry during an outage"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        _jwks.cache_clear()
