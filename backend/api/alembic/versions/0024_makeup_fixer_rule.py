"""Makeup fixers need neither a texture nor a shade color in the serving catalog.

Fixers are not tried on in AR, so the texture requirement agreed in 0010 kept them out of
the catalog for no use. Decided with the data owner on 2026-11-17.

Revision ID: 0024
Revises: 0023
"""

import sqlalchemy as sa

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

CATEGORY = "메이크업 픽서"


def _set_rule(requires_texture: bool) -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE oy_catalog_category_rule "
            "SET requires_texture = :texture, requires_color = false "
            "WHERE std_category_code = :category"
        ),
        {"texture": requires_texture, "category": CATEGORY},
    )


def upgrade() -> None:
    _set_rule(False)


def downgrade() -> None:
    _set_rule(True)
