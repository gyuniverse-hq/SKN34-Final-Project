"""Record AR recommendations, visible chips, and a member's own activity.

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ar_recommendation_requests",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "member_id",
            sa.String(64),
            sa.ForeignKey("members.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("makeup_zone", sa.String(20), nullable=False),
        sa.Column("strategy", sa.String(40), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_ar_requests_member_created",
        "ar_recommendation_requests",
        ["member_id", "created_at"],
    )

    op.create_table(
        "ar_recommendation_candidates",
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ar_recommendation_requests.request_id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Soft catalog references preserve history when the serving catalog is rebuilt.
        sa.Column("product_id", sa.String(64), nullable=False),
        sa.Column("shade_id", sa.String(64), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.CheckConstraint("rank > 0", name="ck_ar_candidates_rank"),
        sa.UniqueConstraint(
            "request_id", "product_id", "shade_id", name="uq_ar_candidates_request_shade"
        ),
        sa.UniqueConstraint("request_id", "rank", name="uq_ar_candidates_request_rank"),
    )

    op.create_table(
        "ar_recommendation_impressions",
        sa.Column("impression_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ar_recommendation_candidates.candidate_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("view_instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("displayed_position", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("visibility_policy_version", sa.String(64), nullable=False),
        sa.CheckConstraint("displayed_position > 0", name="ck_ar_impressions_position"),
        sa.UniqueConstraint(
            "candidate_id", "view_instance_id", name="uq_ar_impressions_candidate_view"
        ),
    )

    op.create_table(
        "ar_activity_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "member_id",
            sa.String(64),
            sa.ForeignKey("members.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", sa.String(64), nullable=False),
        sa.Column("shade_id", sa.String(64), nullable=False),
        sa.Column("makeup_zone", sa.String(20), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column(
            "impression_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ar_recommendation_impressions.impression_id", ondelete="SET NULL"),
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('try_on', 'cart_add')", name="ck_ar_activity_events_type"
        ),
    )
    op.create_index(
        "ix_ar_activity_member_occurred", "ar_activity_events", ["member_id", "occurred_at"]
    )
    op.create_index(
        "ix_ar_activity_session_occurred", "ar_activity_events", ["session_id", "occurred_at"]
    )
    op.create_index("ix_ar_activity_impression", "ar_activity_events", ["impression_id"])

    # Like recommendation history, these member records are written through the backend only.
    for table in (
        "ar_recommendation_requests",
        "ar_recommendation_candidates",
        "ar_recommendation_impressions",
        "ar_activity_events",
    ):
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))


def downgrade() -> None:
    op.drop_table("ar_activity_events")
    op.drop_table("ar_recommendation_impressions")
    op.drop_table("ar_recommendation_candidates")
    op.drop_table("ar_recommendation_requests")
