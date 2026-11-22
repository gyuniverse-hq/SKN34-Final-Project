"""Internal API contracts for provenance-preserving knowledge search."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_VERSION = "openai-3072-title-body-v1"
DIMENSIONS = 3072
INDEX_VERSION = "large-3200-overlap-1000-v1"


class RagModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class RagSpan(RagModel):
    block_order: int
    start_utf16: int
    end_utf16: int
    chunk_start_utf16: int
    chunk_end_utf16: int
    source_locator: dict


class RagSegment(RagModel):
    span: RagSpan
    text: str


class RagCandidate(RagModel):
    chunk_id: str
    document_id: int
    extraction_id: int
    source_version: str
    source_file_id: int
    title: str
    score: float
    channels: list[Literal["keyword", "vector", "qa"]]
    segments: list[RagSegment]


class RagSearch(RagModel):
    question: str = Field(min_length=1, max_length=2000)
    strategy: Literal["large", "section", "qa"] = "large"
    limit: int = Field(default=20, ge=1, le=20)


class RagSearchResponse(RagModel):
    candidates: list[RagCandidate]
    embedding_input_tokens: int = 0
    embedding_ms: int = 0
    lookup_ms: int = 0


class RagLocation(RagModel):
    document_id: int
    extraction_id: int
    source_version: str
    block_order: int
    chunk_id: str
    start_utf16: int
    end_utf16: int


class RagContext(RagModel):
    evidence: list[RagLocation] = Field(min_length=1, max_length=8)


class RagOriginal(RagModel):
    block_order: int
    kind: str
    text: str
    source_locator: dict


class RagNeighbors(RagModel):
    source: RagLocation
    blocks: list[RagOriginal]
