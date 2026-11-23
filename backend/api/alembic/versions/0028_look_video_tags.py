"""Store the reviewed visual tags of each makeup video (look consultation feature 6).

One row per video. The nine 0-4 scores are columns because recommendation compares them on
every request; the 23 code-list attributes sit in one JSON column because they are filtered
less often and the code list may still grow. Scores are the Gemini/Claude average and text
values keep both sources. The code list lives in a backend file, and full transcripts are
never stored here. Decided with the data owner on 2026-11-20 (option B).

Revision ID: 0028
Revises: 0027
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

SCORE_COLUMNS = (
    "overall_sparkle",
    "eye_sparkle",
    "glamour",
    "naturalness",
    "eye_emphasis",
    "spring_mood",
    "summer_mood",
    "autumn_mood",
    "winter_mood",
)


def upgrade() -> None:
    op.create_table(
        "look_video_tags",
        sa.Column(
            "video_id",
            sa.String(32),
            sa.ForeignKey("youtube_videos.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("review_status", sa.String(20), nullable=False),
        sa.Column("rubric_version", sa.String(40), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        *(sa.Column(name, sa.Numeric(3, 2), nullable=True) for name in SCORE_COLUMNS),
        sa.Column(
            "attributes",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "free_tags", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "evidence", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.CheckConstraint(
            "review_status IN ('ai_merged', 'user_reviewed')",
            name="ck_look_video_tags_review_status",
        ),
        *(
            sa.CheckConstraint(
                f"{name} IS NULL OR {name} BETWEEN 0 AND 4", name=f"ck_look_video_tags_{name}"
            )
            for name in SCORE_COLUMNS
        ),
    )


def downgrade() -> None:
    op.drop_table("look_video_tags")
