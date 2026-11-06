"""Move recommendation data to verified, reproducible rules.

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def _archive_table(table: str, key_sql: str = "row_to_json(t)::text") -> None:
    op.execute(
        sa.text(
            f"INSERT INTO recommendation_legacy_archive (source_table, source_key, row_data) "
            f"SELECT '{table}', {key_sql}, to_jsonb(t) FROM public.{table} AS t"
        )
    )


def upgrade() -> None:
    # Persistent audit copy: this keeps removed approval states, candidate rows, and
    # old serving payloads recoverable without keeping them in operational rec_* tables.
    op.create_table(
        "recommendation_legacy_archive",
        sa.Column("archive_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source_table", sa.Text(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("row_data", JSONB(), nullable=False),
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("source_table", "source_key", name="uq_recommendation_archive_key"),
    )
    for table in (
        "rec_concern",
        "rec_evidence",
        "rec_ingredient_dictionary",
        "rec_mapping",
        "rec_mapping_ingredient",
        "rec_manual_review_candidate",
        "rec_ingredient_link",
        "rec_concern_match",
        "skincare_serving",
    ):
        _archive_table(table)

    # The old serving bundle has the former approval contract. Clear it so the API
    # cannot load stale approval-gated data under the new schema.
    op.execute("DELETE FROM public.skincare_serving")

    op.execute("DELETE FROM public.rec_concern_match")
    # Old mappings contain review states and lack verified endpoint-level evidence.
    # Preserve their full rows above; require revalidation before they become active.
    op.execute("DELETE FROM public.rec_mapping_ingredient")
    op.execute("DELETE FROM public.rec_mapping")
    # Retain only links produced by the existing exact-name rule. Manual/group links
    # remain in the archive and are rebuilt only from versioned rules.
    op.execute("DELETE FROM public.rec_ingredient_link WHERE link_method <> 'exact_name'")
    op.drop_table("rec_manual_review_candidate")

    op.execute(
        "INSERT INTO public.rec_concern (target_concern, display_label, recommendation_reason) "
        "VALUES ('oiliness', '유분·피지', "
        "'유분·피지 고민과 관련된 검증된 성분 정보를 바탕으로 한 참고 정보입니다.') "
        "ON CONFLICT (target_concern) DO NOTHING"
    )

    op.add_column("rec_evidence", sa.Column("study_type", sa.Text(), nullable=True))
    op.add_column("rec_evidence", sa.Column("publication_year", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_rec_evidence_study_type",
        "rec_evidence",
        "study_type IS NULL OR study_type IN "
        "('human_intervention','human_observational','in_vitro','animal','method_validation','review','other')",
    )
    op.create_check_constraint(
        "ck_rec_evidence_publication_year",
        "rec_evidence",
        "publication_year IS NULL OR publication_year BETWEEN 1800 AND 2200",
    )
    op.drop_column("rec_evidence", "ai_paper_review")

    op.drop_column("rec_ingredient_dictionary", "source_match_status")

    op.drop_constraint("ck_rec_mapping_status", "rec_mapping", type_="check")
    for column in (
        "ingredient_codes",
        "evidence_id",
        "mapping_status",
        "human_mapping_review",
        "ai_paper_review",
        "re_review_required",
        "requirements_scope",
    ):
        op.drop_column("rec_mapping", column)
    op.add_column(
        "rec_mapping",
        sa.Column(
            "applicability_scope", sa.Text(), nullable=False, server_default="ingredient_level"
        ),
    )
    op.alter_column("rec_mapping", "applicability_scope", server_default=None)
    op.create_check_constraint(
        "ck_rec_mapping_applicability_scope",
        "rec_mapping",
        "applicability_scope IN ('ingredient_level','formula_specific')",
    )
    op.alter_column(
        "rec_mapping",
        "runtime_enabled",
        server_default=sa.text("false"),
        nullable=False,
    )

    op.create_check_constraint(
        "ck_rec_mapping_ingredient_component_order",
        "rec_mapping_ingredient",
        "component_order >= 1",
    )
    op.create_table(
        "rec_mapping_evidence",
        sa.Column(
            "mapping_id",
            sa.Text(),
            sa.ForeignKey("rec_mapping.mapping_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "evidence_id",
            sa.Text(),
            sa.ForeignKey("rec_evidence.evidence_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("supported_endpoint", sa.Text(), nullable=False),
        sa.Column(
            "study_conditions",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("applicability_note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "length(btrim(supported_endpoint)) > 0", name="ck_rec_map_evidence_endpoint"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(study_conditions) = 'object'", name="ck_rec_map_evidence_conditions"
        ),
    )
    op.create_index("ix_rec_mapping_evidence_evidence_id", "rec_mapping_evidence", ["evidence_id"])

    op.drop_constraint("ck_rec_link_method", "rec_ingredient_link", type_="check")
    op.drop_constraint("ck_rec_link_provenance", "rec_ingredient_link", type_="check")
    op.drop_column("rec_ingredient_link", "reviewed_by")
    op.drop_column("rec_ingredient_link", "reviewed_at")
    op.drop_column("rec_ingredient_link", "note")
    op.create_check_constraint(
        "ck_rec_link_method",
        "rec_ingredient_link",
        "link_method IN ('standard_id','exact_name','verified_alias','verified_group_member')",
    )


def downgrade() -> None:
    raise RuntimeError(
        "0016 changes the meaning of active recommendation data. Restore from "
        "recommendation_legacy_archive and apply a reviewed rollback migration instead."
    )
