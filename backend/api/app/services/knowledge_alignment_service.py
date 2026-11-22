"""Locate existing excerpts in the linked document's verified body blocks."""

import hashlib
import re
import unicodedata
from bisect import bisect_right
from collections import defaultdict
from collections.abc import AsyncIterator, Iterable, Iterator
from contextlib import aclosing
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.knowledge_repository import KnowledgeRepository
from app.schemas.knowledge import (
    DocumentExtraction,
    ExtractedBlock,
    QuoteAlignment,
    QuoteCandidate,
    QuoteSource,
    SourceSpan,
)
from app.services.knowledge_extraction_service import extract_documents

MATCHER_VERSION = "body-v1-align-v1"
PARSER_VERSION = "apache-poi-5.5.1"
EXTRACTION_VERSION = "body-v1"
MIN_PARTIAL = 24
Profile = Literal["raw", "layout", "letters_digits"]
HANGUL = re.compile(r"[가-힣]")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _utf16(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _clusters(value: str) -> Iterator[tuple[int, int]]:
    """Keep combining marks and modern Hangul L/V/T together for reversible NFKC."""
    i = 0
    while i < len(value):
        start = i
        cp = ord(value[i])
        i += 1
        if 0x1100 <= cp <= 0x1112 and i < len(value) and 0x1161 <= ord(value[i]) <= 0x1175:
            i += 1
            cp = 0xAC00  # Treat a consumed L/V pair as an LV syllable.
        if (
            0xAC00 <= cp <= 0xD7A3
            and (cp - 0xAC00) % 28 == 0
            and i < len(value)
            and 0x11A8 <= ord(value[i]) <= 0x11C2
        ):
            i += 1
        while i < len(value) and unicodedata.category(value[i]).startswith("M"):
            i += 1
        yield start, i


@dataclass(frozen=True)
class MappedText:
    text: str
    starts: list[int]
    ends: list[int]

    def whole_clusters(self, start: int, end: int) -> bool:
        return (start == 0 or self.starts[start] != self.starts[start - 1]) and (
            end == len(self.text) or self.ends[end - 1] != self.ends[end]
        )

    def raw_range(self, start: int, end: int) -> tuple[int, int]:
        return self.starts[start], self.ends[end - 1]


def _normalize(value: str, profile: Profile) -> MappedText:
    pieces, starts, ends = [], [], []
    for start, end in _clusters(value):
        piece = unicodedata.normalize("NFKC", value[start:end]).lower()
        if profile == "letters_digits":
            piece = "".join(c for c in piece if c.isalpha() or c.isdecimal())
        else:
            piece = "".join(
                c for c in piece if not c.isspace() and unicodedata.category(c) not in ("Cc", "Cf")
            )
        pieces.append(piece)
        starts.extend([start] * len(piece))
        ends.extend([end] * len(piece))
    return MappedText("".join(pieces), starts, ends)


def _occurrences(text: str, query: str) -> Iterator[int]:
    if query:
        start = text.find(query)
        while start >= 0:
            yield start
            start = text.find(query, start + 1)


@dataclass(frozen=True)
class Segment:
    text: str
    blocks: list[ExtractedBlock]
    starts: list[int]

    def spans(self, start: int, end: int, *, exact: bool) -> list[SourceSpan]:
        spans, pieces = [], []
        verified_until = start
        for i in range(max(0, bisect_right(self.starts, start) - 1), len(self.blocks)):
            block, base = self.blocks[i], self.starts[i]
            if base >= end:
                break
            a, b = max(start - base, 0), min(end - base, len(block.text_raw))
            if a >= b:
                continue
            if exact and base + a != verified_until:
                return []  # An inserted newline between OOXML blocks isn't raw text.
            verified_until = base + b
            raw = block.text_raw[a:b]
            pieces.append(raw)
            spans.append(
                SourceSpan(
                    block_order=block.block_order,
                    source_locator=block.source_locator,
                    start_utf16=_utf16(block.text_raw[:a]),
                    end_utf16=_utf16(block.text_raw[:b]),
                    text_sha256=_sha(raw),
                )
            )
        if exact and (verified_until != end or "".join(pieces) != self.text[start:end]):
            return []
        return spans


def _segments(document: DocumentExtraction) -> Iterator[Segment]:
    blocks, starts, pieces = [], [], []
    size = 0
    for block in document.blocks:
        if blocks and (
            block.block_type == "table_cell"
            or blocks[-1].block_type == "table_cell"
            or (
                document.detected_format == "ole"
                and blocks[-1].source_locator.end != block.source_locator.start
            )
        ):
            yield Segment("".join(pieces), blocks, starts)
            blocks, starts, pieces, size = [], [], [], 0
        if blocks and document.detected_format == "ooxml":
            pieces.append("\n")
            size += 1
        starts.append(size)
        blocks.append(block)
        pieces.append(block.text_raw)
        size += len(block.text_raw)
    if blocks:
        yield Segment("".join(pieces), blocks, starts)


def _partial_matches(
    body: MappedText,
    quote: MappedText,
    minimum: int,
) -> Iterator[tuple[int, int, int]]:
    """Find maximal spans by testing every minimum-length query window."""
    covered_until: dict[int, int] = {}
    for q in range(len(quote.text) - minimum + 1):
        for s in _occurrences(body.text, quote.text[q : q + minimum]):
            diagonal = s - q
            if covered_until.get(diagonal, -1) >= q + minimum:
                continue
            left, right = 0, minimum
            while s > left and q > left and body.text[s - left - 1] == quote.text[q - left - 1]:
                left += 1
            while s + right < len(body.text) and q + right < len(quote.text):
                if body.text[s + right] != quote.text[q + right]:
                    break
                right += 1
            covered_until[diagonal] = q + right
            a, b, length = s - left, q - left, left + right
            # A compatibility character may expand to multiple code points. Keep whole units.
            while length >= minimum and not (
                body.whole_clusters(a, a + length) and quote.whole_clusters(b, b + length)
            ):
                if (a > 0 and body.starts[a] == body.starts[a - 1]) or (
                    b > 0 and quote.starts[b] == quote.starts[b - 1]
                ):
                    a, b, length = a + 1, b + 1, length - 1
                else:
                    length -= 1
            if length >= minimum:
                yield a, b, length


def _candidate(
    segment: Segment,
    raw_quote: str,
    profile: Profile,
    source: tuple[int, int],
    query: tuple[int, int],
    length: int,
    total: int,
) -> QuoteCandidate | None:
    start, end = source
    q_start, q_end = query
    spans = segment.spans(start, end, exact=profile == "raw")
    if not spans:
        return None
    if profile != "raw":
        actual = _normalize(segment.text[start:end], profile).text
        expected = _normalize(raw_quote[q_start:q_end], profile).text
        if actual != expected or len(actual) != length:
            return None
    return QuoteCandidate(
        profile=profile,
        quote_start_utf16=_utf16(raw_quote[:q_start]),
        quote_end_utf16=_utf16(raw_quote[:q_end]),
        matched_length=length,
        quote_length=total,
        spans=spans,
    )


def _ordered(candidates: list[QuoteCandidate]) -> tuple[QuoteCandidate, ...]:
    return tuple(
        sorted(
            candidates,
            key=lambda c: (
                c.spans[0].block_order,
                c.spans[0].start_utf16,
                c.quote_start_utf16,
            ),
        )
    )


class QuoteMatcher:
    def __init__(self, document: DocumentExtraction):
        self.document = document
        self.segments = list(_segments(document))
        self._maps: dict[Profile, list[MappedText]] = {}

    def _normalized(self, profile: Profile) -> list[MappedText]:
        if profile not in self._maps:
            self._maps[profile] = [_normalize(segment.text, profile) for segment in self.segments]
        return self._maps[profile]

    def match(self, quote: str) -> QuoteAlignment:
        if self.document.status != "success":
            return QuoteAlignment("unverified", f"extraction_{self.document.status}")
        if not quote.strip():
            return QuoteAlignment("unverified", "empty_quote")
        if not any(segment.text.strip() for segment in self.segments):
            return QuoteAlignment("unverified", "empty_body")
        exact = []
        for segment in self.segments:
            for start in _occurrences(segment.text, quote):
                candidate = _candidate(
                    segment,
                    quote,
                    "raw",
                    (start, start + len(quote)),
                    (0, len(quote)),
                    len(quote),
                    len(quote),
                )
                if candidate:
                    exact.append(candidate)
        if exact:
            return QuoteAlignment("exact", "raw_text", _ordered(exact))

        for profile in ("layout", "letters_digits"):
            query = _normalize(quote, profile)
            full = []
            seen = set()
            for segment, body in zip(self.segments, self._normalized(profile), strict=True):
                for start in _occurrences(body.text, query.text):
                    end = start + len(query.text)
                    if not body.whole_clusters(start, end):
                        continue
                    source = body.raw_range(start, end)
                    key = (segment.blocks[0].block_order, source)
                    if key in seen:
                        continue
                    candidate = _candidate(
                        segment,
                        quote,
                        profile,
                        source,
                        (0, len(quote)),
                        len(query.text),
                        len(query.text),
                    )
                    if candidate:
                        seen.add(key)
                        full.append(candidate)
            if full:
                return QuoteAlignment("normalized", profile, _ordered(full))

        partial, best = [], MIN_PARTIAL
        for segment, body in zip(self.segments, self._normalized("letters_digits"), strict=True):
            for a, b, length in _partial_matches(body, query, MIN_PARTIAL):
                if length < best:
                    continue
                candidate = _candidate(
                    segment,
                    quote,
                    "letters_digits",
                    body.raw_range(a, a + length),
                    query.raw_range(b, b + length),
                    length,
                    len(query.text),
                )
                if candidate:
                    if length > best:
                        partial, best = [], length
                    partial.append(candidate)
        if partial:
            unique = {c.model_dump_json(): c for c in partial}
            return QuoteAlignment("partial", "longest_contiguous", _ordered(list(unique.values())))

        if len(query.text) < MIN_PARTIAL:
            reason = "quote_below_partial_threshold"
        elif len(HANGUL.findall(quote)) >= 10 and not any(
            HANGUL.search(segment.text) for segment in self.segments
        ):
            reason = "korean_quote_no_hangul_in_body"
        elif any(
            next(_partial_matches(body, query, 12), None) is not None
            for body in self._normalized("letters_digits")
        ):
            reason = "shared_12_to_23_chars"
        else:
            reason = "no_12_char_span"
        return QuoteAlignment("unverified", reason)


async def read_quote_sources(session: AsyncSession, case_id: str | None) -> list[QuoteSource]:
    async with session.begin():
        return await KnowledgeRepository(session).read_quote_sources(case_id)


async def save_alignments(
    session: AsyncSession,
    matches: list[tuple[QuoteSource, QuoteAlignment]],
    case_id: str | None,
) -> dict[str, int]:
    inserted = 0
    async with session.begin():
        repo = KnowledgeRepository(session)
        sources = await repo.read_quote_sources(case_id, lock_for_alignment=True)
        if len(matches) != len(sources) or {source for source, _ in matches} != set(sources):
            raise ValueError("Quote sources changed during matching; rerun the alignment")

        document_ids = {source.document_id for source in sources if source.document_id is not None}
        extraction_ids = await repo.alignment_extraction_ids(
            document_ids, PARSER_VERSION, EXTRACTION_VERSION
        )
        for source, match in matches:
            extraction_id = None
            if source.document_id is not None:
                extraction_id = extraction_ids.get((source.document_id, source.source_sha256 or ""))
                if extraction_id is None:
                    raise ValueError(
                        f"Missing compatible extraction for document {source.document_id}"
                    )
            inserted += await repo.save_alignment(source, extraction_id, MATCHER_VERSION, match)
    return {"inserted": inserted, "already_exists": len(matches) - inserted}


async def align_quotes(
    sources: Iterable[QuoteSource],
    archive: Path,
    jar: Path,
) -> AsyncIterator[tuple[QuoteSource, QuoteAlignment]]:
    grouped: dict[str, list[QuoteSource]] = defaultdict(list)
    for source in sources:
        if source.document_id is None:
            yield source, QuoteAlignment("unlinked", "document_not_linked")
        elif not source.source_sha256:
            yield source, QuoteAlignment("unverified", "document_hash_missing")
        else:
            grouped[source.source_sha256].append(source)
    if not grouped:
        return
    async with aclosing(extract_documents(archive, jar)) as documents:
        async for document in documents:
            group = grouped.pop(document.source_sha256, [])
            if group:
                matcher = QuoteMatcher(document)
                cache: dict[str, QuoteAlignment] = {}
                for source in group:
                    if source.quote_raw not in cache:
                        cache[source.quote_raw] = matcher.match(source.quote_raw)
                    yield source, cache[source.quote_raw]
    for missing in grouped.values():
        for source in missing:
            yield source, QuoteAlignment("unverified", "document_hash_not_in_zip")
