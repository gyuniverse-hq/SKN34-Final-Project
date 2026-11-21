"""Knowledge retrieval and validated source reconstruction for G5."""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from time import perf_counter

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.openai_embedding_client import OpenAIEmbeddings
from app.core.config import get_settings
from app.core.errors import ApiError, UpstreamError
from app.repositories.rag_repository import RagRepository
from app.schemas.rag import (
    RagCandidate,
    RagLocation,
    RagNeighbors,
    RagOriginal,
    RagSearch,
    RagSearchResponse,
    RagSegment,
    RagSpan,
)
from app.services.rag_chunking import Block, cut, digest, utf16

_SECTION = re.compile(
    r"^\s*(?:[Ⅰ-ⅫIVX]{1,9}\s*[.．)]|제\s*\d+\s*장|(?:\d+\.){1,4}\s+"
    r"|\(\d+\)\s+|[•●]\s*[ⓐ-ⓩ])"
)


@dataclass(frozen=True)
class Match:
    row: dict
    score: float
    channels: tuple[str, ...]


def fuse(keyword, vector, limit):
    rows, scores, channels = {}, defaultdict(float), defaultdict(list)
    for channel, candidates in (("keyword", keyword), ("vector", vector)):
        for rank, row in enumerate(candidates, 1):
            key = row["chunk_id"]
            rows[key] = row
            scores[key] += 1 / (60 + rank)
            channels[key].append(channel)
    spread, held, doc_counts = [], [], Counter()
    for key in sorted(scores, key=lambda k: (-scores[k], k)):
        row = rows[key]
        match = Match(row, scores[key], tuple(channels[key]))
        doc = row["document_id"]
        if doc_counts[doc] < 5:
            spread.append(match)
            doc_counts[doc] += 1
        else:
            held.append(match)
    return (spread + held)[:limit]


def candidate(row, score, channels):
    segments = [
        RagSegment(
            span=RagSpan.model_validate(span),
            text=cut(row["content"], span["chunk_start_utf16"], span["chunk_end_utf16"]),
        )
        for span in row["source_spans"]
    ]
    return RagCandidate(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        extraction_id=row["extraction_id"],
        source_version=row["source_version"],
        source_file_id=row["file_id"],
        title=row["title"],
        score=score,
        channels=list(channels),
        segments=segments,
    )


def checked(row):
    return Block.create(
        row["block_order"],
        row["block_type"],
        row["text_raw"],
        row["source_locator"],
        row["text_sha256"],
    )


def full_span(block, start, end, chunk_start=0):
    return RagSpan(
        block_order=block.order,
        start_utf16=start,
        end_utf16=end,
        chunk_start_utf16=chunk_start,
        chunk_end_utf16=chunk_start + end - start,
        source_locator=block.locator,
    )


def seed_candidate(row, key, segments, channel):
    return RagCandidate(
        chunk_id=key,
        document_id=row["document_id"],
        extraction_id=row["extraction_id"],
        source_version=row["source_version"],
        source_file_id=row["file_id"],
        title=row["title"],
        score=row["score"],
        channels=[channel],
        segments=segments,
    )


def section_heading(block):
    return (
        len(block.text.strip()) <= 125 and block.kind == "paragraph" and _SECTION.match(block.text)
    )


class RagSearchService:
    def __init__(self, repo: RagRepository):
        self.repo = repo
        self.settings = get_settings()

    async def search(self, request: RagSearch):
        start = perf_counter()
        local = self.settings.g5_local_mode
        tokens = embedding_ms = 0
        if request.strategy != "large":
            if not local:
                raise ApiError(400, "Experimental search strategy is unavailable", "g5_strategy")
            if request.strategy == "section":
                found = await self.section(request.question, request.limit)
            else:
                found = await self.qa(request.question, request.limit)
        else:
            key = self.settings.g5_openai_api_key
            if not key:
                raise ApiError(503, "G5 is unavailable", "g5_unavailable")
            async with httpx.AsyncClient(
                base_url="https://api.openai.com/v1/",
                headers={"Authorization": f"Bearer {key}"},
                timeout=httpx.Timeout(30, connect=8),
                follow_redirects=False,
            ) as http:
                try:
                    vector = await OpenAIEmbeddings(http).embed([request.question])
                except UpstreamError as exc:
                    raise ApiError(
                        502, "Knowledge embedding failed", "g5_embedding_failed"
                    ) from exc  # noqa: E501
            tokens, embedding_ms = vector.input_tokens, vector.elapsed_ms
            start = perf_counter()
            dense = await self.repo.vector(vector.vectors[0], local=local)
            found = [candidate(row, row["score"], ("vector",)) for row in dense[: request.limit]]
        return RagSearchResponse(
            candidates=found,
            embedding_input_tokens=tokens,
            embedding_ms=embedding_ms,
            lookup_ms=round((perf_counter() - start) * 1000),
        )

    async def context(self, loc: RagLocation):
        rows = await self.repo.original(loc, local=self.settings.g5_local_mode)
        blocks = [checked(row) for row in rows]
        chosen = next((b for b in blocks if b.order == loc.block_order), None)
        if not chosen or not cut(chosen.text, loc.start_utf16, loc.end_utf16).strip():
            raise ApiError(409, "Original source changed", "g5_source_changed")
        return RagNeighbors(
            source=loc,
            blocks=[
                RagOriginal(block_order=b.order, kind=b.kind, text=b.text, source_locator=b.locator)
                for b in blocks
            ],
        )

    async def section(self, question, limit):
        seeds = await self.repo.section_seeds(question, local=True)
        found, seen, cache = [], set(), {}
        for row in seeds:
            eid, order = row["extraction_id"], row["block_order"]
            if eid not in cache:
                cache[eid] = [checked(r) for r in await self.repo.blocks(eid)]
            blocks = cache[eid]
            near = {b.order: b for b in blocks if order - 7 <= b.order <= order + 12}
            if order not in near:
                continue
            previous = [
                p for p, b in near.items() if order - 7 <= p <= order and section_heading(b)
            ]
            following = [p for p, b in near.items() if p > order and section_heading(b)]
            low = max(previous, default=max(0, order - 2))
            high = min(following, default=order + 11)
            tag = (eid, low, high)
            if tag in seen:
                continue
            seen.add(tag)
            selected = [near[order]]
            available = 3200 - near[order].offsets[-1]
            for b in sorted(
                (n for n in near.values() if low <= n.order < high and n.order != order),
                key=lambda n: abs(n.order - order),
            ):
                width = b.offsets[-1] + 1
                if b.kind == "paragraph" and b.text.strip() and width <= available:
                    selected.append(b)
                    available -= width
            segments = []
            cursor = 0
            for block in sorted(selected, key=lambda b: b.order):
                span = full_span(block, 0, block.offsets[-1], cursor)
                segments.append(RagSegment(span=span, text=block.text))
                cursor = span.chunk_end_utf16 + 1
            found.append(seed_candidate(row, f"section:{eid}:{low}:{high}", segments, "keyword"))
            if len(found) == limit:
                break
        return found

    async def qa(self, question, limit):
        found, seen, cache = [], set(), {}
        for row in await self.repo.qa_seeds(question, local=True):
            if len(row["candidates"]) != 1:
                continue
            eid = row["extraction_id"]
            if eid not in cache:
                cache[eid] = {b.order: b for b in map(checked, await self.repo.blocks(eid))}
            segments, cursor = [], 0
            refs = row["candidates"][0]["spans"]
            for s in refs:
                block = cache[eid].get(s["block_order"])
                if not block:
                    break
                a, z = s["start_utf16"], s["end_utf16"]
                body = cut(block.text, a, z)
                if digest(body) != s["text_sha256"] or block.locator != s["source_locator"]:
                    break
                span = full_span(block, a, z, cursor)
                segments.append(RagSegment(span=span, text=body))
                cursor += utf16(body) + 1
            else:
                marker = (
                    eid,
                    tuple(
                        (s.span.block_order, s.span.start_utf16, s.span.end_utf16) for s in segments
                    ),
                )
                if not segments or marker in seen:
                    continue
                seen.add(marker)
                key = digest(f"{eid}:{row['seq']}:{row['source_position']}")
                found.append(seed_candidate(row, f"qa:{key}", segments, "qa"))
                if len(found) == limit:
                    break
        return found


def create_search_service(db: AsyncSession) -> RagSearchService:
    return RagSearchService(RagRepository(db))
