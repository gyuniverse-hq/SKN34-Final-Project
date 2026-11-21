"""Store versioned excerpt matches and source spans."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "aihub_quote_alignment",
        sa.Column("alignment_id", sa.BigInteger(), primary_key=True),
        sa.Column("seq", sa.Text(), nullable=False),
        sa.Column("source_position", sa.SmallInteger(), nullable=False),
        sa.Column("quote_sha256", sa.Text(), nullable=False),
        sa.Column(
            "document_id", sa.BigInteger(), sa.ForeignKey("aihub_knowledge_document.document_id")
        ),
        sa.Column(
            "extraction_id",
            sa.BigInteger(),
            sa.ForeignKey("aihub_document_extraction.extraction_id"),
        ),
        sa.Column("matcher_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("candidates", postgresql.JSONB(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["seq", "source_position"],
            ["aihub_qa_source_link.seq", "aihub_qa_source_link.source_position"],
            name="fk_aihub_alignment_source",
        ),
        sa.UniqueConstraint(
            "seq",
            "source_position",
            "quote_sha256",
            "document_id",
            "extraction_id",
            "matcher_version",
            name="uq_aihub_alignment_input",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint(
            "status IN ('exact', 'normalized', 'partial', 'unverified', 'unlinked')",
            name="ck_aihub_alignment_status",
        ),
        sa.CheckConstraint(
            "(status = 'unlinked') = (document_id IS NULL) AND "
            "(extraction_id IS NULL OR document_id IS NOT NULL)",
            name="ck_aihub_alignment_document",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(candidates) = 'array' AND "
            "((status IN ('exact', 'normalized', 'partial') AND verified AND "
            "extraction_id IS NOT NULL AND jsonb_array_length(candidates) > 0) OR "
            "(status IN ('unverified', 'unlinked') AND NOT verified AND "
            "jsonb_array_length(candidates) = 0))",
            name="ck_aihub_alignment_result",
        ),
    )
    op.create_index("ix_aihub_alignment_document", "aihub_quote_alignment", ["document_id"])
    op.create_index("ix_aihub_alignment_extraction", "aihub_quote_alignment", ["extraction_id"])


def downgrade() -> None:
    op.drop_table("aihub_quote_alignment")
