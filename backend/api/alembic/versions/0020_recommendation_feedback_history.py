"""Add V2 recommendation decisions, impressions and behavior history.

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recommendation_requests",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "member_id",
            sa.String(64),
            sa.ForeignKey("members.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("environment", sa.Text(), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("primary_concern", sa.Text(), nullable=False),
        sa.Column("secondary_concern", sa.Text()),
        sa.Column("contract_version", sa.Text(), nullable=False),
        sa.Column("feature_version", sa.Text(), nullable=False),
        sa.Column("ranking_policy_version", sa.Text(), nullable=False),
        sa.Column("v2_model_version", sa.Text()),
        sa.Column("catalog_version", sa.Text()),
        sa.Column("catalog_digest", sa.Text()),
        sa.Column("policy_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("model_manifest", postgresql.JSONB()),
        sa.Column("recommendation_evidence", postgresql.JSONB()),
        sa.Column("failure_code", sa.Text()),
        sa.CheckConstraint("jsonb_typeof(input_snapshot) = 'object'", name="ck_rec_requests_input"),
        sa.CheckConstraint(
            "jsonb_typeof(policy_snapshot) = 'object'", name="ck_rec_requests_policy"
        ),
        sa.CheckConstraint(
            "model_manifest IS NULL OR jsonb_typeof(model_manifest) = 'object'",
            name="ck_rec_requests_manifest",
        ),
        sa.CheckConstraint(
            "recommendation_evidence IS NULL OR jsonb_typeof(recommendation_evidence) = 'object'",
            name="ck_rec_requests_evidence",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= requested_at",
            name="ck_rec_requests_completed_at",
        ),
    )
    op.create_index(
        "ix_rec_requests_member_requested",
        "recommendation_requests",
        ["member_id", "requested_at"],
    )
    op.create_index(
        "ix_rec_requests_session_requested",
        "recommendation_requests",
        ["session_id", "requested_at"],
    )

    op.create_table(
        "recommendation_candidates",
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recommendation_requests.request_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("option_id", sa.Text(), nullable=False),
        sa.Column("primary_ingredient_score", sa.Float(53), nullable=False),
        sa.Column("secondary_ingredient_score", sa.Float(53)),
        sa.Column("ingredient_score", sa.Float(53), nullable=False),
        sa.Column("review_score", sa.Float(53), nullable=False),
        sa.Column("v2_score", sa.Float(53), nullable=False),
        sa.Column("final_rank", sa.SmallInteger()),
        sa.Column("diversity_penalty", sa.Float(53)),
        sa.Column("selection_score", sa.Float(53)),
        sa.Column("evidence_snapshot", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("request_id", "option_id", name="uq_rec_candidates_request_option"),
        sa.CheckConstraint(
            "final_rank IS NULL OR final_rank BETWEEN 1 AND 5",
            name="ck_rec_candidates_final_rank",
        ),
        sa.CheckConstraint(
            "(final_rank IS NULL AND diversity_penalty IS NULL AND selection_score IS NULL) "
            "OR (final_rank IS NOT NULL AND diversity_penalty IS NOT NULL "
            "AND selection_score IS NOT NULL)",
            name="ck_rec_candidates_selection",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_snapshot) = 'object'", name="ck_rec_candidates_evidence"
        ),
        sa.CheckConstraint(
            "primary_ingredient_score > '-Infinity'::float8 "
            "AND primary_ingredient_score < 'Infinity'::float8 "
            "AND ingredient_score > '-Infinity'::float8 "
            "AND ingredient_score < 'Infinity'::float8 "
            "AND review_score > '-Infinity'::float8 "
            "AND review_score < 'Infinity'::float8 "
            "AND v2_score > '-Infinity'::float8 AND v2_score < 'Infinity'::float8 "
            "AND (secondary_ingredient_score IS NULL OR "
            "(secondary_ingredient_score > '-Infinity'::float8 "
            "AND secondary_ingredient_score < 'Infinity'::float8)) "
            "AND (diversity_penalty IS NULL OR "
            "(diversity_penalty > '-Infinity'::float8 "
            "AND diversity_penalty < 'Infinity'::float8)) "
            "AND (selection_score IS NULL OR "
            "(selection_score > '-Infinity'::float8 "
            "AND selection_score < 'Infinity'::float8))",
            name="ck_rec_candidates_finite_scores",
        ),
    )
    op.create_index(
        "uq_rec_candidates_final_rank",
        "recommendation_candidates",
        ["request_id", "final_rank"],
        unique=True,
        postgresql_where=sa.text("final_rank IS NOT NULL"),
    )
    op.create_index(
        "uq_rec_candidates_final_product",
        "recommendation_candidates",
        ["request_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("final_rank IS NOT NULL"),
    )

    op.create_table(
        "recommendation_impressions",
        sa.Column("impression_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recommendation_candidates.candidate_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("view_instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("surface", sa.Text(), nullable=False),
        sa.Column("displayed_position", sa.SmallInteger(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("visibility_policy_version", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "candidate_id", "view_instance_id", "surface", name="uq_rec_impressions_view"
        ),
        sa.CheckConstraint("displayed_position > 0", name="ck_rec_impressions_position"),
    )

    op.create_table(
        "user_behavior_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("member_id", sa.String(64), sa.ForeignKey("members.id", ondelete="CASCADE")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "impression_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recommendation_impressions.impression_id", ondelete="CASCADE"),
        ),
        sa.Column("order_line_id", sa.Integer(), sa.ForeignKey("order_lines.id")),
        sa.Column("product_id", sa.Text()),
        sa.Column("option_id", sa.Text()),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_source", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("attribution_policy_version", sa.Text()),
        sa.Column("source_record_key", sa.Text()),
        sa.Column("event_schema_version", sa.Text(), nullable=False),
        sa.Column("surface", sa.Text(), nullable=False),
        sa.Column("context_snapshot", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('product_view', 'save', 'unsave', 'cart_add', "
            "'cart_remove', 'category_view', 'outbound_click', 'not_interested', "
            "'product_use_feedback', 'purchase_confirmed')",
            name="ck_behavior_events_type",
        ),
        sa.CheckConstraint(
            "event_source IN ('client', 'server')", name="ck_behavior_events_source"
        ),
        sa.CheckConstraint(
            "event_type <> 'purchase_confirmed' OR "
            "(event_source = 'server' AND order_line_id IS NOT NULL)",
            name="ck_behavior_events_purchase",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(context_snapshot) = 'object'", name="ck_behavior_events_context"
        ),
    )
    op.create_index(
        "ix_behavior_events_member_occurred",
        "user_behavior_events",
        ["member_id", "occurred_at"],
    )
    op.create_index(
        "ix_behavior_events_session_occurred",
        "user_behavior_events",
        ["session_id", "occurred_at"],
    )
    op.create_index("ix_behavior_events_impression", "user_behavior_events", ["impression_id"])
    op.create_index("ix_behavior_events_order_line", "user_behavior_events", ["order_line_id"])
    op.create_index(
        "uq_behavior_events_source_record",
        "user_behavior_events",
        ["event_source", "source_record_key"],
        unique=True,
        postgresql_where=sa.text("source_record_key IS NOT NULL"),
    )
    op.create_index(
        "uq_behavior_events_purchase_line",
        "user_behavior_events",
        ["order_line_id"],
        unique=True,
        postgresql_where=sa.text("event_type = 'purchase_confirmed'"),
    )

    # The backend owns writes; no client-facing policies are created for sensitive history.
    for table in (
        "recommendation_requests",
        "recommendation_candidates",
        "recommendation_impressions",
        "user_behavior_events",
    ):
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))


def downgrade() -> None:
    op.drop_table("user_behavior_events")
    op.drop_table("recommendation_impressions")
    op.drop_table("recommendation_candidates")
    op.drop_table("recommendation_requests")
