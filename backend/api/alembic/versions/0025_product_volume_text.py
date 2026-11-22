"""Store the full product volume text instead of cutting it at 50 characters.

Olive Young volume notices for sets and gift bundles run up to about 300 characters, so the
50-character limit from 0001 cut off what the product page and comparison table show.
Decided with the data owner on 2026-11-17.

Revision ID: 0025
Revises: 0024
"""

import sqlalchemy as sa

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "products",
        "volume",
        existing_type=sa.String(50),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Values longer than 50 characters are cut, as they were before this revision.
    op.alter_column(
        "products",
        "volume",
        existing_type=sa.Text(),
        type_=sa.String(50),
        existing_nullable=False,
        postgresql_using="left(volume, 50)",
    )
