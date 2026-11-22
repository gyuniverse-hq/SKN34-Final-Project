"""The evaluated 3,200 UTF-16 unit chunker with 1,000 units of overlap."""

import hashlib
import re
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass

from app.schemas.rag import RagSpan

CAP = 3200
OVERLAP = 1000
_SENTENCE = re.compile(r"""[.!?。！？](?:["'”’)\]]*)(?:\s+|$)|[\r\n]{2,}""")
_SPACES = re.compile(r"\s+")
_WORD = re.compile(r"[가-힣a-z0-9]+")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def utf16(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def cut(value: str, start: int, end: int) -> str:
    raw = value.encode("utf-16-le")
    if not 0 <= start <= end <= len(raw) // 2:
        raise ValueError("Invalid UTF-16 range")
    return raw[start * 2 : end * 2].decode("utf-16-le")


def search_terms(value: str) -> list[str]:
    terms = []
    for word in _WORD.findall(unicodedata.normalize("NFKC", value).casefold()):
        if re.fullmatch("[가-힣]+", word):
            terms.extend(word[i : i + 2] for i in range(len(word) - 1))
        elif len(word) > 1:
            terms.append(word)
    return terms


@dataclass(frozen=True)
class Block:
    order: int
    kind: str
    text: str
    locator: dict
    offsets: tuple[int, ...]

    @classmethod
    def create(cls, order, kind, text, locator, text_hash):
        offsets = [0]
        for char in text:
            offsets.append(offsets[-1] + (1 if ord(char) <= 0xFFFF else 2))
        if digest(text) != text_hash or locator["end"] - locator["start"] != offsets[-1]:
            raise ValueError(f"Invalid source block {order}")
        return cls(order, kind, text, locator, tuple(offsets))


@dataclass(frozen=True)
class Piece:
    block: Block
    first: int
    last: int

    @property
    def width(self):
        return self.block.offsets[self.last] - self.block.offsets[self.first]


@dataclass(frozen=True)
class Chunk:
    content: str
    spans: tuple[RagSpan, ...]


def _pieces(block):
    first = 0
    cuts = [m.end() for m in _SENTENCE.finditer(block.text)]
    spaces = [m.end() for m in _SPACES.finditer(block.text)]
    while block.offsets[-1] - block.offsets[first] > CAP:
        limit = bisect_right(block.offsets, block.offsets[first] + CAP) - 1
        end = limit
        for boundaries in (cuts, spaces):
            index = bisect_right(boundaries, limit) - 1
            if index >= 0 and boundaries[index] > first:
                end = boundaries[index]
                break
        yield Piece(block, first, end)
        first = end
    yield Piece(block, first, len(block.text))


def _width(pieces):
    return sum(p.width for p in pieces) + sum(
        a.block.order != b.block.order for a, b in zip(pieces, pieces[1:], strict=False)
    )


def _row(block):
    loc = block.locator
    if loc["format"] == "ole":
        return ("ole", loc["table"], loc["row"])
    return ("ooxml", *loc["path"][:-1])


def _render(pieces):
    spans, parts = [], []
    cursor = 0
    for p in pieces:
        if spans and spans[-1].block_order != p.block.order:
            parts.append("\n")
            cursor += 1
        parts.append(p.block.text[p.first : p.last])
        spans.append(
            RagSpan(
                block_order=p.block.order,
                start_utf16=p.block.offsets[p.first],
                end_utf16=p.block.offsets[p.last],
                chunk_start_utf16=cursor,
                chunk_end_utf16=cursor + p.width,
                source_locator=p.block.locator,
            )
        )
        cursor += p.width
    return Chunk("".join(parts), tuple(spans))


def chunk_document(blocks: list[Block]):
    paragraphs, row = [], []
    for block in blocks:
        if not block.text:
            continue
        if block.kind == "table_cell":
            if paragraphs:
                yield _render(paragraphs)
                paragraphs = []
            if row and _row(row[-1].block) != _row(block):
                yield _render(row)
                row = []
            piece = Piece(block, 0, len(block.text))
            if _width([*row, piece]) > CAP:
                if row:
                    yield _render(row)
                    row = []
                for split in _pieces(block):
                    yield _render([split])
            else:
                row.append(piece)
            continue
        if row:
            yield _render(row)
            row = []
        for piece in _pieces(block):
            if _width([*paragraphs, piece]) > CAP:
                yield _render(paragraphs)
                suffix = []
                for trailing in reversed(paragraphs):
                    if trailing.first or trailing.last != len(trailing.block.text):
                        break
                    keep = [trailing, *suffix]
                    if _width(keep) > OVERLAP or _width([*keep, piece]) > CAP:
                        break
                    suffix = keep
                paragraphs = suffix
            paragraphs.append(piece)
    if paragraphs:
        yield _render(paragraphs)
    if row:
        yield _render(row)
