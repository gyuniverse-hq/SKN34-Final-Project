"""Derived document bodies; existing AIHub document/QA rows remain authoritative."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AihubDocumentExtractionRow(Base):
    __tablename__ = "aihub_document_extraction"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "parser_version",
            "extraction_version",
            name="uq_aihub_extraction_version",
        ),
        CheckConstraint(
            "status IN ('success', 'failed', 'unsupported')", name="ck_aihub_extraction_status"
        ),
        CheckConstraint("block_count >= 0", name="ck_aihub_extraction_count"),
        CheckConstraint(
            "(status = 'success' AND verified AND error_code IS NULL) OR "
            "(status <> 'success' AND NOT verified AND block_count = 0 AND error_code IS NOT NULL)",
            name="ck_aihub_extraction_result",
        ),
    )
    extraction_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("aihub_knowledge_document.document_id"), nullable=False
    )
    file_id: Mapped[int] = mapped_column(
        ForeignKey("aihub_knowledge_document_file.file_id"), nullable=False
    )
    source_sha256: Mapped[str] = mapped_column(Text)
    detected_format: Mapped[str] = mapped_column(Text)
    parser_version: Mapped[str] = mapped_column(Text)
    extraction_version: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean)
    block_count: Mapped[int] = mapped_column(Integer)
    warnings: Mapped[list] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AihubDocumentBlockRow(Base):
    __tablename__ = "aihub_document_block"
    __table_args__ = (
        UniqueConstraint("extraction_id", "block_order", name="uq_aihub_block_order"),
        CheckConstraint("block_order >= 0", name="ck_aihub_block_order"),
        CheckConstraint("block_type IN ('paragraph', 'table_cell')", name="ck_aihub_block_type"),
        Index("ix_aihub_block_text_hash", "text_sha256"),
    )
    block_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    extraction_id: Mapped[int] = mapped_column(
        ForeignKey("aihub_document_extraction.extraction_id"), nullable=False
    )
    block_order: Mapped[int] = mapped_column(Integer)
    block_type: Mapped[str] = mapped_column(Text)
    text_raw: Mapped[str] = mapped_column(Text)
    text_sha256: Mapped[str] = mapped_column(Text)
    source_locator: Mapped[dict] = mapped_column(JSONB)
    locator_version: Mapped[str] = mapped_column(Text)


class AihubQuoteAlignmentRow(Base):
    __tablename__ = "aihub_quote_alignment"
    __table_args__ = (
        ForeignKeyConstraint(
            ["seq", "source_position"],
            ["aihub_qa_source_link.seq", "aihub_qa_source_link.source_position"],
            name="fk_aihub_alignment_source",
        ),
        UniqueConstraint(
            "seq",
            "source_position",
            "quote_sha256",
            "document_id",
            "extraction_id",
            "matcher_version",
            name="uq_aihub_alignment_input",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "status IN ('exact', 'normalized', 'partial', 'unverified', 'unlinked')",
            name="ck_aihub_alignment_status",
        ),
        CheckConstraint(
            "(status = 'unlinked') = (document_id IS NULL) AND "
            "(extraction_id IS NULL OR document_id IS NOT NULL)",
            name="ck_aihub_alignment_document",
        ),
        CheckConstraint(
            "jsonb_typeof(candidates) = 'array' AND "
            "((status IN ('exact', 'normalized', 'partial') AND verified AND "
            "extraction_id IS NOT NULL AND jsonb_array_length(candidates) > 0) OR "
            "(status IN ('unverified', 'unlinked') AND NOT verified AND "
            "jsonb_array_length(candidates) = 0))",
            name="ck_aihub_alignment_result",
        ),
        Index("ix_aihub_alignment_document", "document_id"),
        Index("ix_aihub_alignment_extraction", "extraction_id"),
    )
    alignment_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    seq: Mapped[str] = mapped_column(Text)
    source_position: Mapped[int] = mapped_column(SmallInteger)
    quote_sha256: Mapped[str] = mapped_column(Text)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("aihub_knowledge_document.document_id")
    )
    extraction_id: Mapped[int | None] = mapped_column(
        ForeignKey("aihub_document_extraction.extraction_id")
    )
    matcher_version: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    reason_code: Mapped[str] = mapped_column(Text)
    candidates: Mapped[list] = mapped_column(JSONB)
    verified: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
