"""The style/celebrity screens read the database: their responses must equal the old JSON.

Needs a migrated PostgreSQL (CI sets TEST_DATABASE_URL after `alembic upgrade head`).
- Empty database (CI): videos, looks and mentions are inserted from the JSON and classified
  with the load job inside a transaction that is rolled back.
- Database that already holds the curated looks (a local copy): it is compared as it is.
"""

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.repositories.celebrity_video_repository import CelebrityVideoRepository
from app.repositories.style_look_repository import StyleLookRepository
from app.repositories.verified_video_product_repository import VerifiedVideoProductLink
from app.schemas.celebrity_video import CelebrityVideo
from app.schemas.style_look import StyleLook
from app.services.makeup_look_catalog_service import EXTRA_LOOKS, load_makeup_look_catalog
from app.services.product_video_service import ProductVideoService

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
DATA = Path(__file__).resolve().parents[1] / "app" / "catalog_data"
# Empty title and channel in the JSON; the database shows the confirmed video values.
EMPTY_IN_JSON = "uWWWVR1rBx4"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL not set"),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _json(name: str) -> list[dict]:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


async def _insert_from_json(conn, style: list[dict], celebrity: list[dict]) -> None:
    videos = [(item["id"], "style title", "") for item in style]
    videos += [
        (item["id"], item["title"] or "confirmed video title", item["channelName"])
        for item in celebrity
    ]
    videos += [(video_id, "extra title", "") for video_id in EXTRA_LOOKS]
    await conn.execute(
        text(
            "INSERT INTO raw_yt_product (yt_product_id, brand_name, product_name)"
            " VALUES ('yt-curatedtest', 'B', 'P')"
        )
    )
    for index, (video_id, title, channel) in enumerate(videos):
        await conn.execute(
            text(
                "INSERT INTO youtube_videos (id, video_id, youtube_url, start_seconds, title,"
                " channel_name, thumbnail_url, analysis_status, product_mapping_status)"
                " VALUES (:id, :video_id, 'u', 0, :title, :channel, '', 'registered',"
                " 'unreviewed')"
            ),
            {"id": f"VIDEO-T{index:03}", "video_id": video_id, "title": title, "channel": channel},
        )
        await conn.execute(
            text(
                "INSERT INTO makeup_looks (id, video_id, display_name, style_description,"
                " is_published) VALUES (:id, :video, 'd', 's', false)"
            ),
            {"id": f"LOOK-T{index:03}", "video": f"VIDEO-T{index:03}"},
        )
    for source, items in (("style", style), ("celebrity", celebrity)):
        for item in items:
            for product in item["products"]:
                key = f"{source}|{item['id']}|{product['number']}"
                await conn.execute(
                    text(
                        "INSERT INTO raw_yt_product_mention (source_row_id, yt_product_id,"
                        " source_product_record_id, source, video_id, mention_number,"
                        " video_url) VALUES (:key, 'yt-curatedtest', :key, :source, :video,"
                        " :number, 'u')"
                    ),
                    {
                        "key": key,
                        "source": source,
                        "video": item["id"],
                        "number": product["number"],
                    },
                )


class EveryMention:
    """Links every listed product, so related videos cover every video and source."""

    def __init__(self, style: list[dict], celebrity: list[dict]) -> None:
        self._links = [
            VerifiedVideoProductLink(source, item["id"], product["number"], f"p{index % 7}", None)
            for source, items in (("style", style), ("celebrity", celebrity))
            for item in items
            for index, product in enumerate(item["products"])
        ]

    async def links(self, *, source=None, product_id=None):
        return [
            link
            for link in self._links
            if source in (None, link.source) and product_id in (None, link.product_id)
        ]


class JsonRepository:
    def __init__(self, style: list[dict], celebrity: list[dict]) -> None:
        self._style = [StyleLook.model_validate(item) for item in style]
        self._celebrity = [CelebrityVideo.model_validate(item) for item in celebrity]

    async def list_looks(self):
        return self._style

    async def list_videos(self):
        return self._celebrity


def _dump(items) -> list[dict]:
    return [item.model_dump(mode="json", by_alias=True) for item in items]


@pytest.mark.anyio
async def test_database_responses_equal_the_json():
    style, celebrity = _json("style_looks.json"), _json("celebrity_videos.json")
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            async with AsyncSession(conn, join_transaction_mode="create_savepoint") as session:
                loaded = (
                    await session.execute(
                        text("SELECT count(*) FROM makeup_looks WHERE look_type IS NOT NULL")
                    )
                ).scalar_one()
                if not loaded:
                    await _insert_from_json(conn, style, celebrity)
                    plan = await load_makeup_look_catalog(session, style, celebrity, write=True)
                    assert plan.ok, plan.conflicts

                db_style = await StyleLookRepository(session).list_looks()
                db_celebrity = await CelebrityVideoRepository(session).list_videos()
                assert _dump(db_style) == _dump(StyleLook.model_validate(i) for i in style)

                expected = _dump(CelebrityVideo.model_validate(i) for i in celebrity)
                actual = _dump(db_celebrity)
                assert [v["id"] for v in actual] == [v["id"] for v in expected]
                for got, want in zip(actual, expected, strict=True):
                    if got["id"] == EMPTY_IN_JSON:
                        assert got["title"] and want["title"] == ""
                        got = {**got, "title": "", "channelName": want["channelName"]}
                    assert got == want

                matches = EveryMention(style, celebrity)
                from_db = ProductVideoService(
                    CelebrityVideoRepository(session), StyleLookRepository(session), matches
                )
                json_repo = JsonRepository(style, celebrity)
                from_json = ProductVideoService(json_repo, json_repo, matches)
                for product_id in (f"p{i}" for i in range(7)):
                    got = _dump(await from_db.videos_for_product(product_id))
                    want = _dump(await from_json.videos_for_product(product_id))
                    assert got, product_id
                    for item in got:
                        if item["id"] == EMPTY_IN_JSON:
                            item.update(title="", channelName="")
                    assert got == want, product_id
            await trans.rollback()
    finally:
        await engine.dispose()
