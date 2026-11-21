"""Versioned AIHub body extraction and original source locations.

Revision ID: 0027
Revises: 0026
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "aihub_document_extraction",
        sa.Column("extraction_id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "document_id",
            sa.BigInteger(),
            sa.ForeignKey("aihub_knowledge_document.document_id"),
            nullable=False,
        ),
        sa.Column(
            "file_id",
            sa.BigInteger(),
            sa.ForeignKey("aihub_knowledge_document_file.file_id"),
            nullable=False,
        ),
        sa.Column("source_sha256", sa.Text(), nullable=False),
        sa.Column("detected_format", sa.Text(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("extraction_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("block_count", sa.Integer(), nullable=False),
        sa.Column("warnings", postgresql.JSONB(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "document_id",
            "parser_version",
            "extraction_version",
            name="uq_aihub_extraction_version",
        ),
        sa.CheckConstraint(
            "status IN ('success', 'failed', 'unsupported')", name="ck_aihub_extraction_status"
        ),
        sa.CheckConstraint("block_count >= 0", name="ck_aihub_extraction_count"),
        sa.CheckConstraint(
            "(status = 'success' AND verified AND error_code IS NULL) OR "
            "(status <> 'success' AND NOT verified AND block_count = 0 AND error_code IS NOT NULL)",
            name="ck_aihub_extraction_result",
        ),
    )
    op.create_table(
        "aihub_document_block",
        sa.Column("block_id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "extraction_id",
            sa.BigInteger(),
            sa.ForeignKey("aihub_document_extraction.extraction_id"),
            nullable=False,
        ),
        sa.Column("block_order", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.Text(), nullable=False),
        sa.Column("text_raw", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.Text(), nullable=False),
        sa.Column("source_locator", postgresql.JSONB(), nullable=False),
        sa.Column("locator_version", sa.Text(), nullable=False),
        sa.UniqueConstraint("extraction_id", "block_order", name="uq_aihub_block_order"),
        sa.CheckConstraint("block_order >= 0", name="ck_aihub_block_order"),
        sa.CheckConstraint("block_type IN ('paragraph', 'table_cell')", name="ck_aihub_block_type"),
    )
    op.create_index("ix_aihub_block_text_hash", "aihub_document_block", ["text_sha256"])


def downgrade() -> None:
    op.drop_index("ix_aihub_block_text_hash", table_name="aihub_document_block")
    op.drop_table("aihub_document_block")
    op.drop_table("aihub_document_extraction")
