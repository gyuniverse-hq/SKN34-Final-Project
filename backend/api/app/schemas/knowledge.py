"""Versioned, raw-text-preserving contract with the Java body extractor."""

import hashlib
from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SourceLocator(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["ole", "ooxml"]
    unit: Literal["utf16"]
    part: str
    path: list[int]
    paragraph: int
    table: int
    row: int
    cell: int
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def valid_range(self) -> Self:
        if self.end < self.start or any(i < 0 for i in self.path):
            raise ValueError("Invalid source range")
        if self.format == "ole":
            if self.part != "main" or self.path:
                raise ValueError("Invalid OLE part")
            if self.paragraph < 0 and min(self.table, self.row, self.cell) < 0:
                raise ValueError("Missing OLE coordinates")
        elif self.part != "/word/document.xml" or not self.path or self.start != 0:
            raise ValueError("Invalid OOXML coordinates")
        return self


class ExtractedBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    block_order: int = Field(ge=0)
    block_type: Literal["paragraph", "table_cell"]
    text_raw: str
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_locator: SourceLocator

    @model_validator(mode="after")
    def valid_text(self) -> Self:
        if hashlib.sha256(self.text_raw.encode()).hexdigest() != self.text_sha256:
            raise ValueError("Block hash mismatch")
        loc = self.source_locator
        if len(self.text_raw.encode("utf-16-le")) // 2 != loc.end - loc.start:
            raise ValueError("UTF-16 range mismatch")
        return self


class DocumentExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_path: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    detected_format: Literal["ole", "ooxml", "rtf", "empty", "unknown"]
    parser_version: Literal["apache-poi-5.5.1"]
    extraction_version: Literal["body-v1"]
    status: Literal["success", "failed", "unsupported"]
    error_code: str | None
    warnings: list[str]
    verified: bool
    blocks: list[ExtractedBlock]

    @model_validator(mode="after")
    def valid_result(self) -> Self:
        if self.status == "success":
            if not self.verified or self.error_code or self.detected_format not in ("ole", "ooxml"):
                raise ValueError("Unverified success")
        elif self.blocks or self.verified or not self.error_code:
            raise ValueError("Invalid failure result")
        for index, block in enumerate(self.blocks):
            if block.block_order != index or block.source_locator.format != self.detected_format:
                raise ValueError("Invalid block order or format")
        return self


@dataclass(frozen=True)
class QuoteSource:
    seq: str
    source_position: int
    document_id: int | None
    quote_raw: str
    source_sha256: str | None


AlignmentStatus = Literal["exact", "normalized", "partial", "unverified", "unlinked"]


class SourceSpan(BaseModel):
    block_order: int = Field(ge=0)
    source_locator: SourceLocator
    start_utf16: int = Field(ge=0)
    end_utf16: int = Field(gt=0)
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def valid_range(self) -> Self:
        if (
            not self.start_utf16
            < self.end_utf16
            <= (self.source_locator.end - self.source_locator.start)
        ):
            raise ValueError("Invalid block-relative span")
        return self


class QuoteCandidate(BaseModel):
    profile: Literal["raw", "layout", "letters_digits"]
    quote_start_utf16: int = Field(ge=0)
    quote_end_utf16: int = Field(gt=0)
    matched_length: int = Field(gt=0)
    quote_length: int = Field(gt=0)
    spans: list[SourceSpan] = Field(min_length=1)

    @property
    def fraction(self) -> float:
        return self.matched_length / self.quote_length


@dataclass(frozen=True)
class QuoteAlignment:
    status: AlignmentStatus
    reason_code: str
    candidates: tuple[QuoteCandidate, ...] = ()
