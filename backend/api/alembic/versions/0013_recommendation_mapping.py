"""피부 고민별 성분 추천 매핑과 논문 근거 테이블.

전달본의 등급 컬럼은 그대로 보존한다. 구 수집본 ID(ingredient_id_bridge)는 현재
raw_oy_ingredient 와 계보가 달라 적재하지 않으며, 성분 코드와 수집 성분의 연결은
rec_ingredient_link 에 이름을 근거로 새로 만든다.
"""

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

MAPPING_STATUSES = (
    "candidate_after_match",
    "research_only",
    "support_only",
    "formula_evidence_only",
    "excluded_treatment_scope",
    "excluded_wrong_endpoint",
    "excluded_context_mismatch",
)
LINK_METHODS = ("exact_name", "manual", "group_member")


def _in_list(column, values):
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade():
    op.create_table(
        "rec_concern",
        sa.Column("target_concern", sa.Text(), primary_key=True),
        sa.Column("display_label", sa.Text(), nullable=False),
        sa.Column("recommendation_reason", sa.Text(), nullable=False),
    )
    op.create_table(
        "rec_evidence",
        sa.Column("evidence_id", sa.Text(), primary_key=True),
        sa.Column("pmid", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("ai_paper_review", sa.Text(), nullable=True),
        sa.Column("study_limit", sa.Text(), nullable=True),
    )
    op.create_table(
        "rec_ingredient_dictionary",
        sa.Column("ingredient_code", sa.Text(), primary_key=True),
        sa.Column("name_ko", sa.Text(), nullable=False),
        sa.Column("inci_name", sa.Text(), nullable=True),
        sa.Column("source_match_status", sa.Text(), nullable=True),
    )
    op.create_table(
        "rec_mapping",
        sa.Column("mapping_id", sa.Text(), primary_key=True),
        sa.Column("mapping_type", sa.Text(), nullable=False),
        sa.Column(
            "target_concern",
            sa.Text(),
            sa.ForeignKey("rec_concern.target_concern"),
            nullable=False,
        ),
        sa.Column("ingredient_codes", sa.Text(), nullable=True),
        sa.Column(
            "evidence_id", sa.Text(), sa.ForeignKey("rec_evidence.evidence_id"), nullable=True
        ),
        sa.Column("mapping_status", sa.Text(), nullable=False),
        sa.Column("human_mapping_review", sa.Text(), nullable=True),
        sa.Column("ai_paper_review", sa.Text(), nullable=True),
        sa.Column("re_review_required", sa.Boolean(), nullable=False),
        sa.Column("runtime_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("requirements_scope", sa.Text(), nullable=True),
        sa.CheckConstraint("mapping_type IN ('single', 'combination')", name="ck_rec_mapping_type"),
        sa.CheckConstraint(
            _in_list("mapping_status", MAPPING_STATUSES), name="ck_rec_mapping_status"
        ),
    )
    op.create_index("ix_rec_mapping_concern", "rec_mapping", ["target_concern"])
    op.create_table(
        "rec_mapping_ingredient",
        sa.Column(
            "mapping_id", sa.Text(), sa.ForeignKey("rec_mapping.mapping_id"), primary_key=True
        ),
        sa.Column(
            "ingredient_code",
            sa.Text(),
            sa.ForeignKey("rec_ingredient_dictionary.ingredient_code"),
            primary_key=True,
        ),
        sa.Column("component_order", sa.Integer(), nullable=False),
    )
    op.create_table(
        "rec_manual_review_candidate",
        sa.Column(
            "ingredient_code",
            sa.Text(),
            sa.ForeignKey("rec_ingredient_dictionary.ingredient_code"),
            primary_key=True,
        ),
        sa.Column("source_name", sa.Text(), primary_key=True),
        sa.Column("source_ingredient_id", sa.BigInteger(), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("approved", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "rec_ingredient_link",
        sa.Column(
            "ingredient_code",
            sa.Text(),
            sa.ForeignKey("rec_ingredient_dictionary.ingredient_code"),
            primary_key=True,
        ),
        sa.Column(
            "oy_ingredient_id",
            sa.BigInteger(),
            sa.ForeignKey("raw_oy_ingredient.ingredient_id"),
            primary_key=True,
        ),
        sa.Column("link_method", sa.Text(), nullable=False),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint(_in_list("link_method", LINK_METHODS), name="ck_rec_link_method"),
        sa.CheckConstraint(
            "link_method = 'exact_name' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_rec_link_provenance",
        ),
    )
    op.create_index("ix_rec_ingredient_link_oy", "rec_ingredient_link", ["oy_ingredient_id"])
    op.create_table(
        "rec_concern_match",
        sa.Column(
            "mapping_id", sa.Text(), sa.ForeignKey("rec_mapping.mapping_id"), primary_key=True
        ),
        sa.Column(
            "option_id",
            sa.Text(),
            sa.ForeignKey("raw_oy_product_option.option_id"),
            primary_key=True,
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_rec_concern_match_option", "rec_concern_match", ["option_id"])


def downgrade():
    op.drop_index("ix_rec_concern_match_option", table_name="rec_concern_match")
    op.drop_table("rec_concern_match")
    op.drop_index("ix_rec_ingredient_link_oy", table_name="rec_ingredient_link")
    op.drop_table("rec_ingredient_link")
    op.drop_table("rec_manual_review_candidate")
    op.drop_table("rec_mapping_ingredient")
    op.drop_index("ix_rec_mapping_concern", table_name="rec_mapping")
    op.drop_table("rec_mapping")
    op.drop_table("rec_ingredient_dictionary")
    op.drop_table("rec_evidence")
    op.drop_table("rec_concern")
