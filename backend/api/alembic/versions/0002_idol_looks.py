"""youtube-backed idol looks

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


VIDEOS = (
    (
        'VIDEO-001',
        'fDqBPI1SaWY',
        'https://www.youtube.com/watch?v=fDqBPI1SaWY&t=1576s',
        1576,
        'LOOK-001',
    ),
    ('VIDEO-002', 'S2nXySh1WuU', 'https://www.youtube.com/watch?v=S2nXySh1WuU', 0, 'LOOK-002'),
    ('VIDEO-003', 'mXUMB45414A', 'https://www.youtube.com/watch?v=mXUMB45414A', 0, 'LOOK-003'),
)


def upgrade() -> None:
    op.create_table(
        'youtube_videos',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('video_id', sa.String(32), nullable=False, unique=True),
        sa.Column('youtube_url', sa.Text(), nullable=False),
        sa.Column('start_seconds', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('title', sa.String(300), nullable=False),
        sa.Column('channel_name', sa.String(200), nullable=False, server_default=''),
        sa.Column('thumbnail_url', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('published_at', sa.String(40), nullable=True),
        sa.Column('analysis_status', sa.String(32), nullable=False),
        sa.Column('product_mapping_status', sa.String(32), nullable=False),
    )
    op.create_index('ix_youtube_videos_video_id', 'youtube_videos', ['video_id'])
    op.create_table(
        'makeup_looks',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column(
            'video_id',
            sa.String(32),
            sa.ForeignKey('youtube_videos.id'),
            nullable=False,
            unique=True,
        ),
        sa.Column('display_name', sa.String(300), nullable=False),
        sa.Column('style_description', sa.Text(), nullable=False),
        sa.Column('is_published', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index('ix_makeup_looks_is_published', 'makeup_looks', ['is_published'])
    op.create_table(
        'look_products',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column(
            'look_id',
            sa.String(32),
            sa.ForeignKey('makeup_looks.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('makeup_zone', sa.String(20), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('product_id', sa.String(64), sa.ForeignKey('products.id'), nullable=True),
        sa.Column('shade_id', sa.String(64), nullable=True),
        sa.Column('source_type', sa.String(64), nullable=True),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('evidence_text', sa.Text(), nullable=True),
        sa.Column('verified', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('similarity_score', sa.Float(), nullable=True),
        sa.Column('recommendation_reason', sa.Text(), nullable=True),
        sa.UniqueConstraint('look_id', 'id', name='uq_look_products_look_id_id'),
    )
    op.create_index('ix_look_products_look_id', 'look_products', ['look_id'])
    op.create_index('ix_look_products_product_id', 'look_products', ['product_id'])
    op.create_table(
        'look_ar_settings',
        sa.Column(
            'look_id',
            sa.String(32),
            sa.ForeignKey('makeup_looks.id', ondelete='CASCADE'),
            primary_key=True,
        ),
        sa.Column('makeup_zone', sa.String(20), primary_key=True),
        sa.Column('hex', sa.String(7), nullable=False),
        sa.Column('intensity', sa.Float(), nullable=False),
        sa.Column('texture', sa.String(20), nullable=False),
    )
    videos = sa.table(
        'youtube_videos',
        sa.column('id', sa.String),
        sa.column('video_id', sa.String),
        sa.column('youtube_url', sa.Text),
        sa.column('start_seconds', sa.Integer),
        sa.column('title', sa.String),
        sa.column('channel_name', sa.String),
        sa.column('thumbnail_url', sa.Text),
        sa.column('analysis_status', sa.String),
        sa.column('product_mapping_status', sa.String),
    )
    looks = sa.table(
        'makeup_looks',
        sa.column('id', sa.String),
        sa.column('video_id', sa.String),
        sa.column('display_name', sa.String),
        sa.column('style_description', sa.Text),
        sa.column('is_published', sa.Boolean),
    )
    op.bulk_insert(videos, [
        {
            'id': row_id, 'video_id': video_id, 'youtube_url': url,
            'start_seconds': start, 'title': f'YouTube video {video_id}',
            'channel_name': '', 'thumbnail_url': f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg',
            'analysis_status': 'metadata_unavailable', 'product_mapping_status': 'unreviewed',
        }
        for row_id, video_id, url, start, _ in VIDEOS
    ])
    op.bulk_insert(looks, [
        {
            'id': look_id, 'video_id': row_id, 'display_name': f'YouTube video {video_id}',
            'style_description': 'Video is registered. Makeup style has not been verified.',
            'is_published': True,
        }
        for row_id, video_id, _, _, look_id in VIDEOS
    ])


def downgrade() -> None:
    op.drop_table('look_ar_settings')
    op.drop_index('ix_look_products_product_id', table_name='look_products')
    op.drop_index('ix_look_products_look_id', table_name='look_products')
    op.drop_table('look_products')
    op.drop_index('ix_makeup_looks_is_published', table_name='makeup_looks')
    op.drop_table('makeup_looks')
    op.drop_index('ix_youtube_videos_video_id', table_name='youtube_videos')
    op.drop_table('youtube_videos')
