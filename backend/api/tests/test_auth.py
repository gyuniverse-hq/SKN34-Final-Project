import pytest

from app.core import auth
from app.core.auth import bearer_token, user_from_claims


def test_bearer_token_parsing():
    assert bearer_token("Bearer abc.def") == "abc.def"
    assert bearer_token("bearer   xyz  ") == "xyz"
    assert bearer_token("Basic abc") is None
    assert bearer_token(None) is None


def test_only_authenticated_role_becomes_a_user():
    assert (
        user_from_claims({"sub": "u1", "role": "authenticated", "email": "a@b.c"}).email == "a@b.c"
    )
    assert user_from_claims({"sub": "u1", "role": "anon"}) is None
    assert user_from_claims({"role": "authenticated"}) is None


def test_me_is_unavailable_without_supabase_config(client, monkeypatch):
    monkeypatch.setattr(auth, "get_verifier", lambda: None)
    res = client.get("/api/me")
    assert res.status_code == 503
    assert res.json()["code"] == "auth_unavailable"


class _Verifier:
    async def verify(self, token):
        return (
            {"sub": "user-1", "role": "authenticated", "email": None} if token == "good" else None
        )


@pytest.mark.parametrize(
    ("header", "status"), [(None, 401), ("Bearer bad", 401), ("Bearer good", 200)]
)
def test_me_requires_a_valid_token(client, monkeypatch, header, status):
    monkeypatch.setattr(auth, "get_verifier", lambda: _Verifier())
    res = client.get("/api/me", headers={"Authorization": header} if header else {})
    assert res.status_code == status
    if status == 200:
        assert res.json() == {"user": {"id": "user-1", "email": None}}
