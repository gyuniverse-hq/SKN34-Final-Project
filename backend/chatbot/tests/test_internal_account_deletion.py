import hmac
import json
import time
from secrets import token_hex
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core import internal_deletion_auth
from app.core.config import get_settings
from app.main import create_app
from app.services.owner_deletion_service import OwnerDeletionService

PATH = "/internal/g7/account-deletion"
KEY = token_hex(32)
OWNER_ID = str(uuid4())
BODY = json.dumps({"jobId": str(uuid4()), "ownerId": OWNER_ID}).encode()


class NonceStore:
    def __init__(self):
        self.keys = set()

    async def set(self, key, _value, *, nx, ex):
        assert nx and ex > 0
        if key in self.keys:
            return None
        self.keys.add(key)
        return True


def signed_headers(body=BODY, *, offset=0):
    issued_at = str(int(time.time()) + offset)
    nonce = token_hex(16)
    prefix = f"vishue:g7:account-deletion:v1\nPOST\n{PATH}\n{issued_at}\n{nonce}\n".encode()
    return {
        "content-type": "application/json",
        "x-g7-deletion-timestamp": issued_at,
        "x-g7-deletion-nonce": nonce,
        "x-g7-deletion-signature": hmac.digest(KEY.encode(), prefix + body, "sha256").hex(),
    }


@pytest.fixture
def deletion_setup(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "env", "test")
    monkeypatch.setattr(settings, "g7_internal_deletion_enabled", True)
    monkeypatch.setattr(settings, "g7_internal_deletion_key", SecretStr(KEY))
    store, deleted = NonceStore(), []
    monkeypatch.setattr(internal_deletion_auth, "get_redis", lambda: store)

    async def delete_owner(self, owner_id):
        deleted.append(owner_id)

    monkeypatch.setattr(OwnerDeletionService, "delete", delete_owner)
    return store, deleted


def local_client():
    return TestClient(create_app(), client=("127.0.0.1", 51000))


@pytest.mark.parametrize(("env", "enabled"), [("test", False), ("production", True)])
def test_route_is_unavailable_unless_enabled_locally(deletion_setup, monkeypatch, env, enabled):
    settings = get_settings()
    monkeypatch.setattr(settings, "env", env)
    monkeypatch.setattr(settings, "g7_internal_deletion_enabled", enabled)
    response = local_client().post(PATH, content=BODY, headers=signed_headers())
    assert response.status_code == 404
    assert deletion_setup[1] == []


@pytest.mark.parametrize("case", ["missing", "user-bearer", "altered", "expired", "future"])
def test_authentication_failure_never_invokes_deletion(deletion_setup, case):
    body = BODY
    if case == "missing":
        headers = {}
    elif case == "user-bearer":
        headers = {"authorization": "Bearer user-token"}
    elif case == "altered":
        headers = signed_headers()
        body = BODY.replace(OWNER_ID.encode(), str(uuid4()).encode())
    else:
        headers = signed_headers(offset=-120 if case == "expired" else 120)

    response = local_client().post(PATH, content=body, headers=headers)
    assert (response.status_code, response.json()["code"]) == (403, "account_deletion_forbidden")
    store, deleted = deletion_setup
    assert store.keys == set()
    assert deleted == []


def test_signed_requests_require_a_loopback_peer(deletion_setup):
    client = TestClient(create_app(), client=("192.0.2.10", 51000))
    response = client.post(PATH, content=BODY, headers=signed_headers())
    assert response.status_code == 403
    assert deletion_setup[1] == []


def test_reused_nonce_is_denied_and_new_signature_can_retry_same_job(deletion_setup):
    client = local_client()
    headers = signed_headers()
    first = client.post(PATH, content=BODY, headers=headers)
    assert first.status_code == 204 and first.content == b""
    repeated = client.post(PATH, content=BODY, headers=headers)
    assert (repeated.status_code, repeated.json()["code"]) == (403, "account_deletion_forbidden")
    assert deletion_setup[1] == [OWNER_ID]
    assert client.post(PATH, content=BODY, headers=signed_headers()).status_code == 204
    assert deletion_setup[1] == [OWNER_ID, OWNER_ID]


@pytest.mark.parametrize("failure", ["missing-key", "missing-redis", "redis-error"])
def test_auth_dependency_failure_returns_503_before_deleting(deletion_setup, monkeypatch, failure):
    store, deleted = deletion_setup

    async def unavailable(*_args, **_kwargs):
        raise RedisConnectionError("test Redis outage")

    if failure == "missing-key":
        monkeypatch.setattr(get_settings(), "g7_internal_deletion_key", None)
    elif failure == "missing-redis":
        monkeypatch.setattr(internal_deletion_auth, "get_redis", lambda: None)
    else:
        monkeypatch.setattr(store, "set", unavailable)

    response = local_client().post(PATH, content=BODY, headers=signed_headers())
    assert (response.status_code, response.json()["code"]) == (
        503,
        "account_deletion_auth_unavailable",
    )
    assert deleted == []


@pytest.mark.parametrize(
    ("body", "expected_status"),
    [
        (json.dumps({"jobId": "not-a-uuid", "ownerId": OWNER_ID}).encode(), 400),
        (json.dumps({"jobId": str(uuid4()), "ownerId": 123}).encode(), 400),
        (b" " * 1025, 413),
    ],
)
def test_signed_request_must_have_valid_payload(deletion_setup, body, expected_status):
    response = local_client().post(PATH, content=body, headers=signed_headers(body))
    assert (response.status_code, response.json()["code"]) == (expected_status, "invalid_request")
    assert deletion_setup[1] == []
