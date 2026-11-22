import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.clients import openai_embedding_client
from app.clients.openai_embedding_client import EmbeddingRequestError, OpenAIEmbeddings
from app.core.errors import UpstreamError
from app.schemas.rag import DIMENSIONS, EMBEDDING_MODEL, RagSearch
from app.services import rag_search_service
from app.services.rag_chunking import Block, chunk_document, cut, digest, utf16
from app.services.rag_index_service import build_records
from app.services.rag_search_service import fuse


def source_block(order, text):
    return Block.create(order, "paragraph", text, {"start": 0, "end": utf16(text)}, digest(text))


def test_original_utf16_round_trip():
    blocks = [source_block(0, "앞문장 😀\n"), source_block(1, "긴 문장. " * 1700)]
    chunks = list(chunk_document(blocks))
    assert len(chunks) > 1
    for chunk in chunks:
        assert utf16(chunk.content) <= 3200
        for s in chunk.spans:
            original = cut(blocks[s.block_order].text, s.start_utf16, s.end_utf16)
            assert original == cut(chunk.content, s.chunk_start_utf16, s.chunk_end_utf16)


def test_only_changed_content_changes_embedding_input_identity():
    source = {"document_id": 1, "extraction_id": 2, "source_sha256": "a", "title": "제목"}
    original, first_inputs = build_records(
        source,
        [
            source_block(0, "하" * 2700),
            source_block(1, "가" * 2700),
        ],
    )
    updated, second_inputs = build_records(
        source | {"source_sha256": "b"},
        [
            source_block(0, "하" * 2700),
            source_block(1, "가" * 2699 + "나"),
        ],
    )
    assert len(original) == len(updated) == 2
    assert original[0]["embedding_key"] == updated[0]["embedding_key"]
    assert original[1]["embedding_key"] != updated[1]["embedding_key"]
    assert len(set(second_inputs) - set(first_inputs)) == 1
    assert json.loads(updated[0]["spans"])[0]["end_utf16"] == 2700


def test_fusion_keeps_both_channels_and_disjoint_same_document():
    a = {"chunk_id": "a", "document_id": 1}
    b = {"chunk_id": "b", "document_id": 1}
    c = {"chunk_id": "c", "document_id": 2}
    found = fuse([a, b], [a, c], 3)
    assert [x.row["chunk_id"] for x in found] == ["a", "b", "c"]
    assert found[0].channels == ("keyword", "vector")


def test_large_search_keeps_exact_vector_order_without_keyword_lookup(monkeypatch):
    @asynccontextmanager
    async def search_client(**_):
        yield None

    monkeypatch.setattr(
        rag_search_service,
        "httpx",
        SimpleNamespace(AsyncClient=search_client, Timeout=httpx.Timeout),
    )
    monkeypatch.setattr(
        rag_search_service,
        "get_settings",
        lambda: SimpleNamespace(g5_local_mode=True, g5_openai_api_key="test"),
    )
    vector = [0.01] * DIMENSIONS
    embed = AsyncMock(return_value=SimpleNamespace(vectors=[vector], input_tokens=4, elapsed_ms=5))
    monkeypatch.setattr(
        rag_search_service, "OpenAIEmbeddings", lambda _http: SimpleNamespace(embed=embed)
    )
    rows = [
        {
            "chunk_id": str(i),
            "document_id": 1 if i < 20 else 2,
            "extraction_id": 1 if i < 20 else 2,
            "source_version": "current",
            "file_id": 1 if i < 20 else 2,
            "title": "source",
            "content": "body",
            "source_spans": [],
            "score": 1 - i / 100,
        }
        for i in range(21)
    ]
    repo = SimpleNamespace(keyword=AsyncMock(), vector=AsyncMock(return_value=rows))
    service = rag_search_service.RagSearchService(repo)

    result = asyncio.run(service.search(RagSearch(question="test")))

    embed.assert_awaited_once_with(["test"])
    repo.vector.assert_awaited_once_with(vector, local=True)
    repo.keyword.assert_not_awaited()
    assert [item.chunk_id for item in result.candidates] == [str(i) for i in range(20)]
    assert all(item.channels == ["vector"] for item in result.candidates)


def test_embedding_rejects_wrong_shape():
    async def invoke():
        def broken(_request):
            return httpx.Response(
                200,
                json={
                    "model": EMBEDDING_MODEL,
                    "data": [{"index": 0, "embedding": [1, 2, 3]}],
                    "usage": {"prompt_tokens": 1},
                },
            )

        async with httpx.AsyncClient(
            base_url="https://example.test/", transport=httpx.MockTransport(broken)
        ) as http:
            with pytest.raises(EmbeddingRequestError, match="Invalid embedding") as error:
                await OpenAIEmbeddings(http).embed(["test"])
            assert isinstance(error.value, UpstreamError)
            assert error.value.attempts == 1

    asyncio.run(invoke())


@pytest.mark.parametrize(
    ("retry_after", "delay"),
    [("0", 0), ("60", 60), ("Thu, 19 Nov 2026 12:01:00 GMT", 60), ("invalid", 1)],
)
def test_bulk_embedding_honors_retry_after(monkeypatch, retry_after, delay):
    wait = AsyncMock()
    now = datetime(2026, 11, 19, 12, tzinfo=UTC)
    monkeypatch.setattr(openai_embedding_client, "asyncio", SimpleNamespace(sleep=wait))
    monkeypatch.setattr(openai_embedding_client, "datetime", SimpleNamespace(now=lambda _: now))

    async def invoke():
        seen = 0

        def transport(request):
            nonlocal seen
            seen += 1
            assert json.loads(request.content)["dimensions"] == DIMENSIONS
            if seen == 1:
                return httpx.Response(429, headers={"Retry-After": retry_after})
            return httpx.Response(
                200,
                json={
                    "model": EMBEDDING_MODEL,
                    "data": [{"index": 0, "embedding": [0.1] * DIMENSIONS}],
                    "usage": {"prompt_tokens": 3},
                },
            )

        async with httpx.AsyncClient(
            base_url="https://example.test/", transport=httpx.MockTransport(transport)
        ) as http:
            assert (
                await OpenAIEmbeddings(http, retry_wait_limit=None).embed(["test"])
            ).attempts == 2
        wait.assert_awaited_once_with(delay)

    asyncio.run(invoke())


@pytest.mark.parametrize(
    ("http_status", "detail", "abort_reason"),
    [
        (401, {"code": "invalid_api_key"}, "authentication"),
        (403, {"code": "permission_denied"}, "authentication"),
        (429, {"code": "insufficient_quota"}, "quota"),
        (429, {"type": "billing_hard_limit_reached"}, "quota"),
        (429, {"code": "credit_balance_exhausted"}, "quota"),
        (429, {"code": "organization_spend_limit_exceeded"}, "quota"),
        (429, {"code": "organization_usage_limit_exceeded"}, "quota"),
        (429, {"code": "project_spend_limit_exceeded"}, "quota"),
    ],
)
def test_embedding_does_not_retry_authentication_or_quota(
    monkeypatch, http_status, detail, abort_reason
):
    wait = AsyncMock()
    monkeypatch.setattr(openai_embedding_client, "asyncio", SimpleNamespace(sleep=wait))

    async def invoke():
        def transport(_):
            return httpx.Response(http_status, json={"error": detail})

        async with httpx.AsyncClient(
            base_url="https://example.test/", transport=httpx.MockTransport(transport)
        ) as http:
            with pytest.raises(EmbeddingRequestError) as error:
                await OpenAIEmbeddings(http, retry_wait_limit=None).embed(["fixture"])
        assert (error.value.attempts, error.value.abort_reason) == (1, abort_reason)
        wait.assert_not_awaited()

    asyncio.run(invoke())


def test_search_client_does_not_retry_earlier_than_a_long_retry_after(monkeypatch):
    wait = AsyncMock()
    monkeypatch.setattr(openai_embedding_client, "asyncio", SimpleNamespace(sleep=wait))

    async def invoke():
        def transport(_):
            return httpx.Response(429, headers={"Retry-After": "60"})

        async with httpx.AsyncClient(
            base_url="https://example.test/", transport=httpx.MockTransport(transport)
        ) as http:
            with pytest.raises(EmbeddingRequestError, match="exceeds the wait limit") as error:
                await OpenAIEmbeddings(http).embed(["fixture"])
        assert error.value.attempts == 1
        wait.assert_not_awaited()

    asyncio.run(invoke())
