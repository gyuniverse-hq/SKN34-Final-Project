"""Classify makeup looks into style and celebrity catalog looks.

The style and celebrity screens read two JSON files while the same 107 videos are also
makeup_looks rows, so looks had two sources and no classification. makeup_looks gets the
classification and curated display columns, and raw_yt_product_mention keeps the curated
product display entry (source_payload) next to the untouched research values. The values
are loaded by app.jobs.load_makeup_look_catalog, not here, because the JSON files are the
source being retired.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

LOOK_COLUMNS = (
    sa.Column("look_type", sa.String(20), nullable=True),
    sa.Column("style_group", sa.String(100), nullable=True),
    sa.Column("style_tag", sa.String(200), nullable=True),
    sa.Column("celebrity_id", sa.String(64), nullable=True),
    sa.Column("catalog_title", sa.String(300), nullable=True),
    sa.Column("catalog_position", sa.Integer(), nullable=True),
    sa.Column("catalog_start_seconds", sa.Integer(), nullable=True),
    sa.Column("catalog_link_status", sa.String(32), nullable=True),
    sa.Column(
        "is_catalog_published", sa.Boolean(), nullable=False, server_default=sa.text("false")
    ),
)

# Same conditions as app.models.idol_look.LOOK_CATALOG_CHECKS at this revision.
LOOK_CHECKS = {
    "ck_makeup_looks_look_type": "look_type IS NULL OR look_type IN ('style', 'celebrity')",
    "ck_makeup_looks_classification": (
        "CASE"
        " WHEN look_type IS NULL THEN style_group IS NULL AND style_tag IS NULL"
        " AND celebrity_id IS NULL AND catalog_link_status IS NULL"
        " WHEN look_type = 'style' THEN NULLIF(btrim(style_group), '') IS NOT NULL"
        " AND NULLIF(btrim(style_tag), '') IS NOT NULL"
        " AND celebrity_id IS NULL AND catalog_link_status IS NULL"
        " WHEN look_type = 'celebrity' THEN NULLIF(btrim(celebrity_id), '') IS NOT NULL"
        " AND style_group IS NULL AND style_tag IS NULL"
        " ELSE FALSE END"
    ),
    "ck_makeup_looks_catalog_position": "catalog_position IS NULL OR catalog_position >= 0",
    "ck_makeup_looks_catalog_start": "catalog_start_seconds IS NULL OR catalog_start_seconds >= 0",
    "ck_makeup_looks_catalog_link_status": (
        "catalog_link_status IS NULL"
        " OR catalog_link_status IN ('metadata_available', 'needs_review')"
    ),
    "ck_makeup_looks_catalog_published": (
        "NOT is_catalog_published OR (look_type IS NOT NULL"
        " AND NULLIF(btrim(catalog_title), '') IS NOT NULL AND catalog_position IS NOT NULL"
        " AND (look_type <> 'celebrity' OR catalog_link_status IS NOT NULL))"
    ),
}


def upgrade() -> None:
    for column in LOOK_COLUMNS:
        op.add_column("makeup_looks", column)
    for name, condition in LOOK_CHECKS.items():
        op.create_check_constraint(name, "makeup_looks", condition)
    op.add_column("raw_yt_product_mention", sa.Column("source_payload", JSONB(), nullable=True))
    op.create_check_constraint(
        "ck_raw_yt_mention_source_payload",
        "raw_yt_product_mention",
        "source_payload IS NULL OR jsonb_typeof(source_payload) = 'object'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_raw_yt_mention_source_payload", "raw_yt_product_mention", type_="check")
    op.drop_column("raw_yt_product_mention", "source_payload")
    for name in LOOK_CHECKS:
        op.drop_constraint(name, "makeup_looks", type_="check")
    for column in reversed(LOOK_COLUMNS):
        op.drop_column("makeup_looks", column.name)
