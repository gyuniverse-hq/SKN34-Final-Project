"""Record rule-based TOP 10 and its own cart and purchase events.

Revision ID: 0029
Revises: 0028
"""

import sqlalchemy as sa

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None

CANDIDATES = "recommendation_candidates"
EVENTS = "skincare_recommendation_events"
SCORES = ("primary_ingredient_score", "ingredient_score", "review_score", "v2_score")
LEGACY_RANK = "final_rank IS NULL OR final_rank BETWEEN 1 AND 5"
LEGACY_SELECTION = (
    "(final_rank IS NULL AND diversity_penalty IS NULL AND selection_score IS NULL) "
    "OR (final_rank IS NOT NULL AND diversity_penalty IS NOT NULL AND selection_score IS NOT NULL)"
)


def upgrade() -> None:
    for score in SCORES:
        op.alter_column(CANDIDATES, score, nullable=True)
    op.drop_constraint("ck_rec_candidates_final_rank", CANDIDATES, type_="check")
    op.drop_constraint("ck_rec_candidates_selection", CANDIDATES, type_="check")
    op.create_check_constraint(
        "ck_rec_candidates_final_rank",
        CANDIDATES,
        "(v2_score IS NULL AND final_rank IS NOT NULL AND final_rank BETWEEN 1 AND 10) "
        f"OR (v2_score IS NOT NULL AND ({LEGACY_RANK}))",
    )
    op.create_check_constraint(
        "ck_rec_candidates_selection",
        CANDIDATES,
        "(v2_score IS NULL AND primary_ingredient_score IS NULL "
        "AND secondary_ingredient_score IS NULL AND ingredient_score IS NULL "
        "AND review_score IS NULL AND diversity_penalty IS NULL AND selection_score IS NULL) "
        "OR (v2_score IS NOT NULL AND primary_ingredient_score IS NOT NULL "
        f"AND ingredient_score IS NOT NULL AND review_score IS NOT NULL AND ({LEGACY_SELECTION}))",
    )
    op.create_table(
        EVENTS,
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "impression_id",
            sa.Uuid(),
            sa.ForeignKey("recommendation_impressions.impression_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "order_line_id", sa.Integer(), sa.ForeignKey("order_lines.id", ondelete="CASCADE")
        ),
        sa.Column(
            "cart_event_id", sa.Uuid(), sa.ForeignKey(f"{EVENTS}.event_id", ondelete="CASCADE")
        ),
        sa.UniqueConstraint("order_line_id", "event_type", name="uq_skincare_rec_events_line_type"),
        sa.CheckConstraint(
            "(event_type IN ('product_view', 'cart_add') "
            "AND order_line_id IS NULL AND cart_event_id IS NULL) OR "
            "(event_type IN ('checkout_started', 'purchase_confirmed') "
            "AND order_line_id IS NOT NULL AND cart_event_id IS NOT NULL)",
            name="ck_skincare_rec_events_attribution",
        ),
    )
    op.create_index("ix_skincare_rec_events_impression", EVENTS, ["impression_id"])
    op.create_index(
        "uq_skincare_rec_events_paid_cart",
        EVENTS,
        ["cart_event_id"],
        unique=True,
        postgresql_where=sa.text("event_type = 'purchase_confirmed'"),
    )
    op.execute(sa.text(f"ALTER TABLE {EVENTS} ENABLE ROW LEVEL SECURITY"))


def downgrade() -> None:
    # Restoring NOT NULL fails safely if any rule-based history has already been recorded.
    for score in SCORES:
        op.alter_column(CANDIDATES, score, nullable=False)
    op.drop_constraint("ck_rec_candidates_final_rank", CANDIDATES, type_="check")
    op.drop_constraint("ck_rec_candidates_selection", CANDIDATES, type_="check")
    op.create_check_constraint("ck_rec_candidates_final_rank", CANDIDATES, LEGACY_RANK)
    op.create_check_constraint("ck_rec_candidates_selection", CANDIDATES, LEGACY_SELECTION)
    op.drop_table(EVENTS)
