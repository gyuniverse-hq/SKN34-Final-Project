import anyio
import httpx
import pytest
from fastapi.testclient import TestClient

from app.clients.supabase_admin_client import SupabaseAdminClient
from app.core.auth import AuthUser, require_user
from app.core.errors import ApiError
from app.main import create_app
from app.services.member_service import TERMS_VERSION, MemberService, get_member_service
from tests.conftest import FakeAccounts, FakeMembers

USER = AuthUser(id="user-1", email="a@b.c")


def client_with(members: FakeMembers, accounts: FakeAccounts) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_member_service] = lambda: MemberService(members, accounts)
    app.dependency_overrides[require_user] = lambda: USER
    return TestClient(app)


def test_me_reports_missing_consent_until_the_current_terms_are_agreed():
    members = FakeMembers()
    client = client_with(members, FakeAccounts())

    before = client.get("/api/me").json()
    assert before == {
        "user": {"id": "user-1", "email": "a@b.c"},
        "terms": {"version": TERMS_VERSION, "agreedVersion": None, "agreedAt": None},
    }

    agreed = client.post("/api/me/terms", json={"version": TERMS_VERSION})
    assert agreed.status_code == 200
    assert agreed.json()["agreedVersion"] == TERMS_VERSION
    assert client.get("/api/me").json()["terms"]["agreedAt"] is not None


def test_outdated_or_missing_terms_versions_are_rejected():
    members = FakeMembers()
    client = client_with(members, FakeAccounts())

    outdated = client.post("/api/me/terms", json={"version": "2000-01-01"})
    assert outdated.status_code == 409
    assert outdated.json()["code"] == "terms_outdated"
    assert client.post("/api/me/terms", json={}).status_code == 400
    assert members.rows == {}


def test_deleting_the_account_removes_the_supabase_user_and_member_record():
    members, accounts = FakeMembers(), FakeAccounts()
    client = client_with(members, accounts)
    client.post("/api/me/terms", json={"version": TERMS_VERSION})

    res = client.delete("/api/me")
    assert res.status_code == 204
    assert accounts.deleted == ["user-1"]
    assert members.rows == {}


def test_a_failed_account_deletion_keeps_the_member_record():
    members = FakeMembers()
    error = ApiError(503, "Account deletion is not configured", "account_deletion_unavailable")
    client = client_with(members, FakeAccounts(error))
    client.post("/api/me/terms", json={"version": TERMS_VERSION})

    res = client.delete("/api/me")
    assert res.status_code == 503
    assert res.json()["code"] == "account_deletion_unavailable"
    assert "user-1" in members.rows


def admin_client(status: int, calls: list[httpx.Request], key: str = "sb_secret_x"):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status)

    mock = httpx.MockTransport(handler)
    return SupabaseAdminClient("https://p.supabase.co/", key, transport=mock)


def test_admin_client_sends_a_secret_key_only_as_apikey():
    calls: list[httpx.Request] = []
    anyio.run(admin_client(200, calls).delete_user, "user-1")
    assert calls[0].method == "DELETE"
    assert str(calls[0].url) == "https://p.supabase.co/auth/v1/admin/users/user-1"
    assert calls[0].headers["apikey"] == "sb_secret_x"
    assert "authorization" not in calls[0].headers


def test_admin_client_sends_a_legacy_service_role_key_as_bearer_too():
    calls: list[httpx.Request] = []
    anyio.run(admin_client(200, calls, key="eyJlegacy").delete_user, "user-1")
    assert calls[0].headers["authorization"] == "Bearer eyJlegacy"


def test_admin_client_treats_a_missing_user_as_deleted_and_reports_other_failures():
    anyio.run(admin_client(404, []).delete_user, "user-1")
    with pytest.raises(ApiError) as failed:
        anyio.run(admin_client(500, []).delete_user, "user-1")
    assert failed.value.code == "account_deletion_failed"


def test_unconfigured_admin_client_makes_no_requests():
    with pytest.raises(ApiError) as unavailable:
        anyio.run(SupabaseAdminClient(None, None).delete_user, "user-1")
    assert unavailable.value.status == 503
