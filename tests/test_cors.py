import os
import subprocess
import sys


def test_browser_origins_and_auth_remain_restricted():
    # Import in a fresh process so startup configuration cannot contaminate other tests.
    script = '''
from fastapi.testclient import TestClient
from admaker.api import app
client = TestClient(app)
headers = {"Origin": "http://localhost:8081", "Access-Control-Request-Method": "POST",
           "Access-Control-Request-Headers": "authorization,content-type,idempotency-key"}
allowed = client.options("/v1/products", headers=headers)
assert allowed.status_code == 200
assert allowed.headers["access-control-allow-origin"] == "http://localhost:8081"
assert "access-control-allow-credentials" not in allowed.headers
blocked = client.options("/v1/products", headers={**headers, "Origin": "https://untrusted.example"})
assert blocked.status_code == 400
assert "access-control-allow-origin" not in blocked.headers
unauthorized = client.get("/v1/account", headers={"Origin": "http://localhost:8081"})
assert unauthorized.status_code == 401
assert unauthorized.headers["access-control-allow-origin"] == "http://localhost:8081"
'''
    result = subprocess.run([sys.executable, "-c", script], env={**os.environ, "WEB_ORIGINS": "http://localhost:8081"}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
