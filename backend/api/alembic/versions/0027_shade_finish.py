"""Carry the reviewed eyeshadow finish onto each serving shade.

Lip texture lives on products because a lip product has one texture. An eyeshadow line mixes
finishes across its shades, so the finish from raw_oy_option_finish (0026) goes on the shade.
Empty for every other product. Decided with the data owner on 2026-11-18.

Revision ID: 0027
Revises: 0026
"""

import sqlalchemy as sa

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shades", sa.Column("finish", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("shades", "finish")
