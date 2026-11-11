"""Track AIHub claim revisions and keep review decisions separate from intake.

Revision ID: aihub_claim_review_v1
Revises: 0018
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "aihub_claim_review_v1"
down_revision = "0018"
branch_labels = None
depends_on = None

LEGACY_SUPPORT = (
    "support_status IN ('pending', 'direct', 'indirect', 'insufficient', 'contradicting')"
)


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM public.aihub_ingredient_mention
                GROUP BY seq, mention_type, raw_text HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION 'Duplicate AIHub ingredient mentions need manual reconciliation';
            END IF;
        END $$;
        """
    )
    op.create_unique_constraint(
        "uq_aihub_ingredient_mention_raw",
        "aihub_ingredient_mention",
        ["seq", "mention_type", "raw_text"],
    )
    op.add_column(
        "aihub_qa_case",
        sa.Column("review_progress", sa.Text(), nullable=False, server_default="not_started"),
    )
    op.create_check_constraint(
        "ck_aihub_qa_case_review_progress",
        "aihub_qa_case",
        "review_progress IN ('not_started', 'in_progress', 'completed')",
    )
    op.add_column("aihub_knowledge_document", sa.Column("source_identifier", sa.Text()))
    op.add_column("aihub_knowledge_document", sa.Column("source_version", sa.Text()))
    op.create_check_constraint(
        "ck_aihub_document_source_version",
        "aihub_knowledge_document",
        "(source_identifier IS NULL AND source_version IS NULL) OR "
        "(source_identifier IS NOT NULL AND btrim(source_identifier) <> '' "
        "AND source_version IS NOT NULL AND btrim(source_version) <> '')",
    )
    op.create_unique_constraint(
        "uq_aihub_document_version",
        "aihub_knowledge_document",
        ["source_identifier", "source_version"],
    )

    op.create_table(
        "aihub_claim_version",
        sa.Column("claim_version_id", sa.BigInteger(), primary_key=True),
        sa.Column("claim_key", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("canonical_text", sa.Text(), nullable=False),
        sa.Column("applicability", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("review_progress", sa.Text(), server_default="not_started", nullable=False),
        sa.Column("approval_status", sa.Text()),
        sa.Column(
            "approved_uses",
            sa.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("reviewer", sa.Text()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("decision_reason", sa.Text()),
        sa.UniqueConstraint("claim_key", "revision", name="uq_aihub_claim_revision"),
        sa.CheckConstraint(
            "revision > 0 AND btrim(canonical_text) <> '' "
            "AND jsonb_typeof(applicability) = 'object'",
            name="ck_aihub_claim_version_content",
        ),
        sa.CheckConstraint(
            "(review_progress IN ('not_started', 'in_progress') AND approval_status IS NULL "
            "AND reviewer IS NULL AND reviewed_at IS NULL AND decision_reason IS NULL) OR "
            "(review_progress = 'completed' AND approval_status IS NOT NULL "
            "AND approval_status IN ('approved', 'limited_approved', 'on_hold', 'excluded') "
            "AND reviewer IS NOT NULL AND btrim(reviewer) <> '' AND reviewed_at IS NOT NULL "
            "AND decision_reason IS NOT NULL AND btrim(decision_reason) <> '')",
            name="ck_aihub_claim_version_decision",
        ),
        sa.CheckConstraint(
            "array_position(approved_uses, NULL) IS NULL "
            "AND approved_uses <@ ARRAY['explain', 'rank', 'avoid']::text[] "
            "AND (CASE WHEN approval_status IN ('approved', 'limited_approved') "
            "THEN cardinality(approved_uses) > 0 ELSE cardinality(approved_uses) = 0 END) "
            "AND (approval_status IS DISTINCT FROM 'limited_approved' "
            "OR applicability <> '{}'::jsonb)",
            name="ck_aihub_claim_version_uses",
        ),
    )
    op.create_table(
        "aihub_qa_claim",
        sa.Column("seq", sa.Text(), sa.ForeignKey("aihub_qa_case.seq"), primary_key=True),
        sa.Column(
            "claim_version_id",
            sa.BigInteger(),
            sa.ForeignKey("aihub_claim_version.claim_version_id"),
            primary_key=True,
        ),
        sa.Column("answer_locator", sa.Text(), nullable=False),
        sa.CheckConstraint("btrim(answer_locator) <> ''", name="ck_aihub_qa_claim_locator"),
    )
    op.create_index("ix_aihub_qa_claim_version", "aihub_qa_claim", ["claim_version_id"])

    op.add_column("aihub_claim_review", sa.Column("claim_version_id", sa.BigInteger()))
    op.add_column("aihub_claim_review", sa.Column("source_position", sa.SmallInteger()))
    op.add_column("aihub_claim_review", sa.Column("source_locator", sa.Text()))
    op.add_column("aihub_claim_review", sa.Column("study_type", sa.Text()))
    op.create_foreign_key(
        "fk_aihub_claim_review_version",
        "aihub_claim_review",
        "aihub_claim_version",
        ["claim_version_id"],
        ["claim_version_id"],
    )
    op.create_foreign_key(
        "fk_aihub_claim_review_qa_claim",
        "aihub_claim_review",
        "aihub_qa_claim",
        ["seq", "claim_version_id"],
        ["seq", "claim_version_id"],
    )
    op.create_foreign_key(
        "fk_aihub_claim_review_source_position",
        "aihub_claim_review",
        "aihub_qa_source_link",
        ["seq", "source_position"],
        ["seq", "source_position"],
    )
    op.create_index("ix_aihub_claim_review_version", "aihub_claim_review", ["claim_version_id"])
    op.drop_constraint("ck_aihub_claim_review_support", "aihub_claim_review", type_="check")
    op.create_check_constraint(
        "ck_aihub_claim_review_support",
        "aihub_claim_review",
        LEGACY_SUPPORT + " OR (claim_version_id IS NOT NULL "
        "AND support_status IN ('limited', 'unverifiable'))",
    )
    op.create_check_constraint(
        "ck_aihub_claim_review_version_source",
        "aihub_claim_review",
        "(source_position IS NULL OR (seq IS NOT NULL AND claim_version_id IS NOT NULL)) "
        "AND (claim_version_id IS NULL OR document_id IS NOT NULL OR source_position IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_aihub_claim_review_version_finding",
        "aihub_claim_review",
        "claim_version_id IS NULL OR support_status = 'pending' OR "
        "(reviewer IS NOT NULL AND btrim(reviewer) <> '' "
        "AND notes IS NOT NULL AND btrim(notes) <> '' "
        "AND (support_status IN ('insufficient', 'unverifiable') OR "
        "(document_id IS NOT NULL AND source_locator IS NOT NULL "
        "AND btrim(source_locator) <> '' AND study_type IS NOT NULL AND btrim(study_type) <> '')))",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM public.aihub_claim_version)
               OR EXISTS (
                   SELECT 1 FROM public.aihub_qa_case WHERE review_progress <> 'not_started'
               )
               OR EXISTS (
                   SELECT 1 FROM public.aihub_knowledge_document WHERE source_identifier IS NOT NULL
               )
            THEN
                RAISE EXCEPTION 'Preserve AIHub review data before downgrading';
            END IF;
        END $$;
        """
    )
    for name in ("version_finding", "version_source", "support"):
        op.drop_constraint(f"ck_aihub_claim_review_{name}", "aihub_claim_review", type_="check")
    op.create_check_constraint(
        "ck_aihub_claim_review_support", "aihub_claim_review", LEGACY_SUPPORT
    )
    op.drop_index("ix_aihub_claim_review_version", table_name="aihub_claim_review")
    for name in ("source_position", "qa_claim", "version"):
        op.drop_constraint(
            f"fk_aihub_claim_review_{name}", "aihub_claim_review", type_="foreignkey"
        )
    for column in ("study_type", "source_locator", "source_position", "claim_version_id"):
        op.drop_column("aihub_claim_review", column)
    op.drop_table("aihub_qa_claim")
    op.drop_table("aihub_claim_version")
    op.drop_constraint(
        "uq_aihub_ingredient_mention_raw", "aihub_ingredient_mention", type_="unique"
    )
    op.drop_constraint("uq_aihub_document_version", "aihub_knowledge_document", type_="unique")
    op.drop_constraint(
        "ck_aihub_document_source_version", "aihub_knowledge_document", type_="check"
    )
    op.drop_column("aihub_knowledge_document", "source_version")
    op.drop_column("aihub_knowledge_document", "source_identifier")
    op.drop_constraint("ck_aihub_qa_case_review_progress", "aihub_qa_case", type_="check")
    op.drop_column("aihub_qa_case", "review_progress")
