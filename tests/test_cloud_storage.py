import json

import httpx
import pytest

from admaker.cloud_storage import PrivateCloudStorage


def test_private_sdk_operations_validate_bucket_and_signed_destination():
    calls = []
    public = False
    hostile = False
    def server(request):
        calls.append(request)
        assert request.headers['authorization'] == 'Bearer server-fixture-key'
        path = request.url.path
        if path == '/storage/v1/bucket/private':
            return httpx.Response(200, json={"id": "private", "name": "private", "owner": "", "public": public,
                "created_at": "2026-09-09T00:00:00Z", "updated_at": "2026-09-09T00:00:00Z", "file_size_limit": None, "allowed_mime_types": None})
        if path == '/storage/v1/object/sign/private/verified/account/photo.png':
            assert json.loads(request.content)['expiresIn'] in {60, '60'}
            return httpx.Response(200, json={"signedURL": '/object/sign/private/verified/account/photo.png?token=fixture' if not hostile else 'https://evil.test/object?token=fixture'})
        if request.method == 'DELETE':
            assert json.loads(request.content) == {'prefixes': ['verified/account/photo.png']}
            return httpx.Response(200, json=[])
        assert request.method == 'POST' and request.headers['x-upsert'] == 'false'
        return httpx.Response(200, json={"Key": "private/verified/account/photo.png", "Id": "fixture"})
    store = PrivateCloudStorage('https://project.test', 'server-fixture-key', 'private', transport=httpx.MockTransport(server))
    key = 'verified/account/photo.png'
    store.upload(key, b'fixture', 'image/png')
    assert store.signed_download(key) == 'https://project.test/storage/v1/object/sign/private/verified/account/photo.png?token=fixture'
    store.remove(key)
    count = len(calls)
    for bad in ['../other', '/root', 'x//y', 'x/./y', 'x\\y', 'x%2fy', 'https://evil.test/a']:
        with pytest.raises(ValueError):
            store.signed_download(bad)
    with pytest.raises(ValueError):
        store.signed_download(key, 301)
    assert len(calls) == count
    public = True
    with pytest.raises(OSError, match='not confirmed'):
        store.upload(key, b'fixture', 'image/png')
    assert len(calls) == count + 1
    public = False
    hostile = True
    with pytest.raises(OSError):
        store.signed_download(key)


def test_storage_redirect_does_not_forward_service_key():
    calls = []
    def redirect(request):
        calls.append(request)
        return httpx.Response(307, headers={'location': 'https://evil.test/'})
    store = PrivateCloudStorage('https://project.test', 'secret-fixture', 'private', transport=httpx.MockTransport(redirect))
    with pytest.raises(OSError) as error:
        store.remove('verified/account/file.png')
    assert len(calls) == 1 and 'secret-fixture' not in str(error.value)


def test_download_requires_specific_missing_code_and_bounds_bytes():
    status, body = 404, {"code": "NoSuchKey"}
    def server(request):
        if '/bucket/' in request.url.path:
            return httpx.Response(200, json={"id": "private", "name": "private", "owner": "", "public": False,
                "created_at": "2026-09-09T00:00:00Z", "updated_at": "2026-09-09T00:00:00Z", "file_size_limit": None, "allowed_mime_types": None})
        return httpx.Response(status, json=body) if status != 200 else httpx.Response(200, content=b'oversized')
    store = PrivateCloudStorage('https://project.test', 'fixture', 'private', transport=httpx.MockTransport(server))
    assert store.download('file.png') is None
    body = {"code": "NoSuchBucket"}
    with pytest.raises(OSError):
        store.download('file.png')
    status = 200
    with pytest.raises(OSError):
        store.download('file.png', 3)
