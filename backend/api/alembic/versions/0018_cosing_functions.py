"""Store CosIng ingredient functions and their skin concern classifications."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    # Add missing shared concern codes without replacing existing research data.
    op.execute(
        sa.text("""
        INSERT INTO rec_concern (target_concern, display_label, recommendation_reason)
        VALUES
        ('dryness', '보습', 'CosIng 기능과 사용자 정의 보습 분류를 참고한 정보입니다.'),
        ('oiliness', '유분·피지', 'CosIng 기능과 사용자 정의 유분 분류를 참고한 정보입니다.'),
        ('sensitivity', '진정', 'CosIng 기능과 사용자 정의 진정 분류를 참고한 정보입니다.'),
        ('pigmentation', '톤·잡티', 'CosIng 기능과 사용자 정의 톤·잡티 분류를 참고한 정보입니다.'),
        ('wrinkles', '주름', 'CosIng 기능과 사용자 정의 주름 분류를 참고한 정보입니다.'),
        ('pores', '모공', 'CosIng 기능과 사용자 정의 모공 분류를 참고한 정보입니다.'),
        ('blemish', '트러블', 'CosIng 기능과 사용자 정의 트러블 분류를 참고한 정보입니다.')
        ON CONFLICT (target_concern) DO NOTHING
    """)
    )
    op.create_table(
        "cosing_function",
        sa.Column("function_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("function_name", sa.Text(), nullable=False, unique=True),
    )
    op.create_table(
        "cosing_ingredient_lookup",
        sa.Column(
            "ingredient_id",
            sa.BigInteger(),
            sa.ForeignKey("raw_mfds_ingredient.ingredient_id"),
            primary_key=True,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("match_method", sa.Text()),
        sa.Column("query_name", sa.Text()),
        sa.Column("http_status", sa.Integer()),
        sa.Column("response_count", sa.Integer()),
        sa.Column("returned_inci", postgresql.JSONB()),
        sa.Column("cosing_cas", postgresql.JSONB()),
        sa.Column("substance_id", sa.Text()),
        sa.Column("detail", sa.Text()),
        sa.Column("collected_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('accepted', 'accepted_no_functions', 'missing_english_name', "
            "'multiple_candidates', 'no_results', 'incomplete_response', 'name_mismatch', "
            "'wrong_source', 'missing_or_multiple_substance_id')",
            name="ck_cosing_lookup_status",
        ),
        sa.CheckConstraint(
            "match_method IS NULL OR match_method IN ('exact', 'normalized')",
            name="ck_cosing_lookup_method",
        ),
    )
    op.create_table(
        "ingredient_function",
        sa.Column(
            "ingredient_id",
            sa.BigInteger(),
            sa.ForeignKey("cosing_ingredient_lookup.ingredient_id"),
            primary_key=True,
        ),
        sa.Column(
            "function_id",
            sa.BigInteger(),
            sa.ForeignKey("cosing_function.function_id"),
            primary_key=True,
        ),
    )
    op.create_index("ix_ingredient_function_function_id", "ingredient_function", ["function_id"])
    op.create_table(
        "function_concern",
        sa.Column(
            "function_id",
            sa.BigInteger(),
            sa.ForeignKey("cosing_function.function_id"),
            primary_key=True,
        ),
        sa.Column(
            "target_concern",
            sa.Text(),
            sa.ForeignKey("rec_concern.target_concern"),
            primary_key=True,
        ),
    )
    op.create_index("ix_function_concern_concern", "function_concern", ["target_concern"])


def downgrade():
    # Shared codes can be referenced by research data; preserve them on downgrade.
    op.drop_table("function_concern")
    op.drop_table("ingredient_function")
    op.drop_table("cosing_ingredient_lookup")
    op.drop_table("cosing_function")
