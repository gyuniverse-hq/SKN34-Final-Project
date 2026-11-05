"""curated AR presets for YouTube-backed idol looks

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PRESETS = (
    ("LOOK-001", "lip", "#C96B72", 0.52, "satin"),
    ("LOOK-001", "blush", "#E8A0A6", 0.30, "sheer"),
    ("LOOK-001", "eyeshadow", "#B98A78", 0.24, "satin"),
    ("LOOK-002", "lip", "#B45F6B", 0.58, "velvet"),
    ("LOOK-002", "blush", "#C98B92", 0.34, "sheer"),
    ("LOOK-002", "eyeshadow", "#8F6B66", 0.30, "matte"),
    ("LOOK-003", "lip", "#D45B7A", 0.62, "glossy"),
    ("LOOK-003", "blush", "#E69AAF", 0.36, "cream"),
    ("LOOK-003", "eyeshadow", "#A97891", 0.32, "shimmer"),
)

DESCRIPTIONS = {
    "LOOK-001": (
        "Approximate AR recreation: clear daily makeup with a satin rose lip, "
        "soft pink blush, and light neutral-brown eyeshadow."
    ),
    "LOOK-002": (
        "Approximate AR recreation: muted rosy makeup with a velvet lip, "
        "subtle mauve blush, and softly defined taupe eyeshadow."
    ),
    "LOOK-003": (
        "Approximate AR recreation: bright pink-point makeup with a glossy lip, "
        "fresh cream blush, and a soft mauve shimmer eye."
    ),
}


def upgrade() -> None:
    settings = sa.table(
        "look_ar_settings",
        sa.column("look_id", sa.String),
        sa.column("makeup_zone", sa.String),
        sa.column("hex", sa.String),
        sa.column("intensity", sa.Float),
        sa.column("texture", sa.String),
    )
    op.bulk_insert(
        settings,
        [
            {
                "look_id": look_id,
                "makeup_zone": zone,
                "hex": hex_value,
                "intensity": intensity,
                "texture": texture,
            }
            for look_id, zone, hex_value, intensity, texture in PRESETS
        ],
    )
    statement = sa.text(
        "UPDATE makeup_looks SET style_description = :description WHERE id = :look_id"
    )
    op.get_bind().execute(
        statement,
        [
            {"look_id": look_id, "description": description}
            for look_id, description in DESCRIPTIONS.items()
        ],
    )
    op.execute(
        sa.text(
            "UPDATE youtube_videos SET product_mapping_status = 'no_verified_products' "
            "WHERE id IN ('VIDEO-001', 'VIDEO-002', 'VIDEO-003')"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM look_ar_settings WHERE look_id IN ('LOOK-001', 'LOOK-002', 'LOOK-003')"
        )
    )
    op.execute(
        sa.text(
            "UPDATE makeup_looks "
            "SET style_description = "
            "'Video is registered. Makeup style has not been verified.' "
            "WHERE id IN ('LOOK-001', 'LOOK-002', 'LOOK-003')"
        )
    )
    op.execute(
        sa.text(
            "UPDATE youtube_videos SET product_mapping_status = 'unreviewed' "
            "WHERE id IN ('VIDEO-001', 'VIDEO-002', 'VIDEO-003')"
        )
    )
