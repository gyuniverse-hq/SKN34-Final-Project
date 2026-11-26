"""Needs a migrated PostgreSQL: CI sets TEST_DATABASE_URL after `alembic upgrade head`."""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL not set"),
]

VIDEO = (
    "INSERT INTO youtube_videos (id, video_id, youtube_url, start_seconds, title, channel_name,"
    " thumbnail_url, analysis_status, product_mapping_status)"
    " VALUES ('VIDEO-T01', 'catalogtest', 'https://youtu.be/x', 0, 't', '', '',"
    " 'registered', 'unreviewed')"
)
LOOK = (
    "INSERT INTO makeup_looks (id, video_id, display_name, style_description, is_published,"
    " look_type, style_group, style_tag, celebrity_id, catalog_title, catalog_position,"
    " catalog_start_seconds, catalog_link_status, is_catalog_published)"
    " VALUES ('LOOK-T01', 'VIDEO-T01', 'd', 's', false, :look_type, :style_group, :style_tag,"
    " :celebrity_id, :title, :position, :start, :link, :published)"
)
BASE = {
    "look_type": None,
    "style_group": None,
    "style_tag": None,
    "celebrity_id": None,
    "title": None,
    "position": None,
    "start": None,
    "link": None,
    "published": False,
}
VALID = [
    {},
    {
        "look_type": "style",
        "style_group": "G",
        "style_tag": "#t",
        "title": "T",
        "position": 1,
        "published": True,
    },
    {
        "look_type": "celebrity",
        "celebrity_id": "karina",
        "title": "T",
        "position": 0,
        "start": 5,
        "link": "needs_review",
        "published": True,
    },
    {"look_type": "celebrity", "celebrity_id": "goyounjung", "title": "T"},
]
INVALID = [
    {"look_type": "idol"},
    {"style_group": "G"},
    {"look_type": "style", "style_group": "G", "style_tag": " "},
    {"look_type": "style", "style_group": "G", "style_tag": "#t", "celebrity_id": "karina"},
    {"look_type": "celebrity", "celebrity_id": ""},
    {"look_type": "celebrity", "celebrity_id": "k", "style_tag": "#t"},
    {"look_type": "celebrity", "celebrity_id": "k", "link": "broken"},
    {"position": -1},
    {"start": -1},
    {"published": True},
    {
        "look_type": "style",
        "style_group": "G",
        "style_tag": "#t",
        "title": " ",
        "position": 1,
        "published": True,
    },
    {"look_type": "style", "style_group": "G", "style_tag": "#t", "title": "T", "published": True},
    {"look_type": "celebrity", "celebrity_id": "k", "title": "T", "position": 1, "published": True},
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _insert(conn, values: dict) -> None:
    await conn.execute(text(VIDEO))
    await conn.execute(text(LOOK), {**BASE, **values})


@pytest.mark.anyio
@pytest.mark.parametrize("values", VALID)
async def test_valid_catalog_rows_are_accepted(values):
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            await _insert(conn, values)
            await trans.rollback()
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("values", INVALID)
async def test_invalid_catalog_rows_are_rejected(values):
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            with pytest.raises(IntegrityError):
                await _insert(conn, values)
            await trans.rollback()
    finally:
        await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("payload", "accepted"), [(None, True), ('{"name": "P"}', True), ("[1]", False)]
)
async def test_source_payload_must_be_an_object_or_null(payload, accepted):
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            await conn.execute(
                text(
                    "INSERT INTO raw_yt_product (yt_product_id, brand_name, product_name)"
                    " VALUES ('yt-catalogtest', 'B', 'P')"
                )
            )
            insert = text(
                "INSERT INTO raw_yt_product_mention (source_row_id, yt_product_id,"
                " source_product_record_id, source, video_id, mention_number, video_url,"
                " source_payload) VALUES ('t|v|1', 'yt-catalogtest', 'VISHUE-YT-TEST', 'style',"
                " 'v', 1, 'u', CAST(:payload AS jsonb))"
            )
            if accepted:
                await conn.execute(insert, {"payload": payload})
            else:
                with pytest.raises(IntegrityError):
                    await conn.execute(insert, {"payload": payload})
            await trans.rollback()
    finally:
        await engine.dispose()
