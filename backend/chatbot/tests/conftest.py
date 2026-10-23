import pytest
from fastapi.testclient import TestClient

from app.core import auth
from app.core.ratelimit import MemoryRateLimiter, get_rate_limiter
from app.main import create_app
from app.schemas.chat import GraphProduct
from app.services.chat_service import ChatService, get_chat_service


class FakeGraph:
    def __init__(self) -> None:
        self.terms: list[str] = []

    async def find_products(self, terms, limit=6):
        self.terms = terms
        return [GraphProduct(id="lip-1", brand="Rom&nd", name="Juicy Tint", category="lip",
                             ingredients=["shea butter"], tags=["glossy"])]  # fmt: skip


class FakeLlm:
    def __init__(self, configured: bool = True, error: Exception | None = None) -> None:
        self._configured = configured
        self._error = error
        self.messages: list[dict[str, str]] = []

    @property
    def configured(self) -> bool:
        return self._configured

    async def complete(self, messages):
        self.messages = messages
        if self._error:
            raise self._error
        return "Try Rom&nd Juicy Tint."


class FakeVerifier:
    async def verify(self, token):
        return {"sub": f"user-{token}", "role": "authenticated"} if token.startswith("ok") else None


@pytest.fixture
def graph() -> FakeGraph:
    return FakeGraph()


@pytest.fixture
def llm() -> FakeLlm:
    return FakeLlm()


@pytest.fixture
def client(graph, llm, monkeypatch) -> TestClient:
    monkeypatch.setattr(auth, "get_verifier", lambda: FakeVerifier())
    app = create_app()
    limiter = MemoryRateLimiter(limit=2)
    app.dependency_overrides[get_chat_service] = lambda: ChatService(graph, llm)
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    return TestClient(app)
