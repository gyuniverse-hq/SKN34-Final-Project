"""Incremental embedding and atomic per-document publication."""

import json
import logging
from dataclasses import asdict, dataclass
from itertools import batched
from time import perf_counter

import httpx

from app.clients.openai_embedding_client import EmbeddingRequestError, OpenAIEmbeddings
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.errors import UpstreamError
from app.repositories.rag_repository import RagRepository
from app.schemas.rag import DIMENSIONS, EMBEDDING_MODEL, EMBEDDING_VERSION, INDEX_VERSION
from app.services.rag_chunking import Block, chunk_document, digest, search_terms

logger = logging.getLogger(__name__)


@dataclass
class IndexStats:
    documents: int = 0
    chunks: int = 0
    embedding_inputs: int = 0
    api_calls: int = 0
    failed_api_calls: int = 0
    input_tokens: int = 0
    updated_chunks: int = 0
    removed_chunks: int = 0
    failed_documents: int = 0
    abort_reason: str | None = None
    elapsed_ms: int = 0

    def report(self):
        return asdict(self) | {"estimated_usd": self.input_tokens * 0.13 / 1_000_000}


def build_records(source, blocks):
    doc = source["document_id"]
    records, inputs = [], {}
    for index, chunk in enumerate(chunk_document(blocks)):
        payload = (source["title"] + "\n" + chunk.content).strip()
        if not payload or not chunk.content:
            continue
        content_hash, input_hash = digest(chunk.content), digest(payload)
        key = digest(f"{EMBEDDING_MODEL}:{EMBEDDING_VERSION}:{DIMENSIONS}:{input_hash}")
        inputs[key] = (payload, input_hash)
        records.append(
            {
                "chunk_id": digest(
                    f"{doc}:{INDEX_VERSION}:{EMBEDDING_MODEL}:{EMBEDDING_VERSION}:{index}"
                ),
                "doc": doc,
                "eid": source["extraction_id"],
                "idx": index,
                "source_version": source["source_sha256"],
                "content": chunk.content,
                "content_hash": content_hash,
                "embedding_key": key,
                "spans": json.dumps([s.model_dump() for s in chunk.spans], ensure_ascii=False),
                "terms": " ".join(search_terms(source["title"] + "\n" + chunk.content)),
            }
        )
    return records, inputs


async def index_sources(ids: list[int] | None, *, local: bool, dry_run: bool = False):
    settings = get_settings()
    if local and not settings.g5_local_mode:
        raise ValueError("G5 local document mode is disabled")
    key = settings.g5_openai_api_key
    stats = IndexStats()
    start = perf_counter()
    async with session_scope() as session:
        sources = await RagRepository(session).sources(ids, local=local)
    if ids and {row["document_id"] for row in sources} != set(ids):
        raise ValueError("One or more requested documents are unavailable for indexing")
    if not dry_run and not key:
        raise ValueError("G5_OPENAI_API_KEY is required")
    async with httpx.AsyncClient(
        base_url="https://api.openai.com/v1/",
        headers={"Authorization": f"Bearer {key}"} if key else {},
        timeout=httpx.Timeout(60.0, connect=10.0),
        follow_redirects=False,
    ) as http:
        client = OpenAIEmbeddings(http, retry_wait_limit=None)
        for source in sources:
            try:
                async with session_scope() as session:
                    rows = await RagRepository(session).blocks(source["extraction_id"])
                blocks = [
                    Block.create(
                        row["block_order"],
                        row["block_type"],
                        row["text_raw"],
                        row["source_locator"],
                        row["text_sha256"],
                    )
                    for row in rows
                ]
                if not blocks:
                    raise ValueError("Verified extraction has no blocks")
                records, inputs = build_records(source, blocks)
                for group in batched(sorted(inputs), 24):
                    async with session_scope() as session, session.begin():
                        repo = RagRepository(session)
                        if not dry_run:
                            # Common input locks are taken in the same order on concurrent runs.
                            for k in group:
                                await repo.lock(f"g5-embedding:{k}")
                        known = await repo.stored_keys(list(group))
                        missing = [k for k in group if k not in known]
                        stats.embedding_inputs += len(missing)
                        if missing and not dry_run:
                            batch = await client.embed([inputs[k][0] for k in missing])
                            stats.input_tokens += batch.input_tokens
                            stats.api_calls += batch.attempts
                            stats.failed_api_calls += batch.attempts - 1
                            await repo.save_embeddings(
                                [
                                    {
                                        "key": k,
                                        "hash": inputs[k][1],
                                        "vector": json.dumps(vector, separators=(",", ":")),
                                    }
                                    for k, vector in zip(missing, batch.vectors, strict=True)
                                ]
                            )
                if not dry_run:
                    async with session_scope() as session, session.begin():
                        changed, removed = await RagRepository(session).replace_chunks(
                            source, records, local=local
                        )
                        stats.updated_chunks += changed
                        stats.removed_chunks += removed
                stats.documents += 1
                stats.chunks += len(records)
            except (ValueError, UnicodeError, UpstreamError) as exc:
                stats.failed_documents += 1
                if isinstance(exc, EmbeddingRequestError):
                    stats.api_calls += exc.attempts
                    stats.failed_api_calls += exc.attempts
                    stats.abort_reason = exc.abort_reason
                logger.error(
                    "g5_index_document_failed doc=%s type=%s abort_reason=%s",
                    source["document_id"],
                    type(exc).__name__,
                    stats.abort_reason,
                )
                if stats.abort_reason is not None:
                    break
    stats.elapsed_ms = round((perf_counter() - start) * 1000)
    return stats
