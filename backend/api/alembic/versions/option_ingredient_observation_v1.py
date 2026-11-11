"""Append-only option ingredient observations; never promote legacy reviews."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "oy_option_observation_v1"
down_revision = "aihub_claim_publication_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "raw_oy_option_ingredient_observation",
        sa.Column(
            "option_id",
            sa.Text(),
            sa.ForeignKey("raw_oy_product_option.option_id"),
            primary_key=True,
        ),
        sa.Column("source_version", sa.Text(), primary_key=True),
        sa.Column("collected_at", sa.DateTime(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("raw_sha256", sa.Text(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("ownership_status", sa.Text(), nullable=False),
        sa.Column("completeness", sa.Text(), nullable=False),
        sa.Column("entries", JSONB(), nullable=False),
        sa.CheckConstraint("ownership_status IN ('option', 'unknown')"),
        sa.CheckConstraint("completeness IN ('complete', 'partial', 'unknown')"),
        sa.CheckConstraint("jsonb_typeof(entries) = 'array'"),
    )
    op.create_index(
        "ix_oy_observation_latest",
        "raw_oy_option_ingredient_observation",
        ["option_id", "collected_at"],
    )
    op.execute("""
        CREATE FUNCTION oy_observation_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Option observations are immutable; insert a new version'; END $$;
    """)
    op.execute("""
        CREATE TRIGGER oy_observation_immutable BEFORE UPDATE OR DELETE
        ON raw_oy_option_ingredient_observation
        FOR EACH ROW EXECUTE FUNCTION oy_observation_immutable();
    """)


def downgrade() -> None:
    op.drop_table("raw_oy_option_ingredient_observation")
    op.execute("DROP FUNCTION oy_observation_immutable()")
