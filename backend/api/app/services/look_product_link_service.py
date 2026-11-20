"""Link the products mentioned in each look video to serving catalog products.

A mention becomes a look product only through a reviewed path (a confirmed Olive Young match
or a YouTube-only catalog link). The zone comes from the serving product, so raw zone labels
are not trusted. No mention was checked against the video itself, so every row is unverified.

The job owns the rows it writes (source_type = youtube_product_mention): a run replaces them in
one transaction and leaves rows from any other source alone, so it can be re-run after matches
change. Videos with a linked product become mapped, the rest no_verified_products.
"""

import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, get_args

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_cache
from app.repositories.look_video_repository import LookVideoRepository
from app.schemas.catalog import MakeupZone

SOURCE_TYPE = "youtube_product_mention"
ZONES = frozenset(get_args(MakeupZone))


def shade_base(shade_code: str | None, option_id: str) -> str:
    """Same id the Olive Young catalog build gives a shade before de-duplication."""
    raw = (shade_code or option_id).lower()
    return (re.sub(r"[^a-z0-9]+", "-", raw).strip("-") or "shade")[:60]


def shade_lookup(
    options: Iterable[Mapping[str, Any]], shades: Iterable[tuple[str, str]]
) -> dict[str, str]:
    """Option id -> serving shade id, only when the id cannot belong to another option.

    The catalog build adds -2, -3 when two options of one product share an id, so an option
    whose base id is shared is left without a shade rather than risk the wrong colour.
    """
    existing = set(shades)
    rows = [
        (o["option_id"], o["goods_no"], shade_base(o["shade_code"], o["option_id"]))
        for o in options
        if o.get("goods_no")
    ]
    shared = Counter((goods, base) for _, goods, base in rows)
    lookup: dict[str, str] = {}
    for option_id, goods, base in rows:
        product_id = f"oy-{goods.lower()}"[:64]
        if shared[(goods, base)] == 1 and (product_id, base) in existing:
            lookup[option_id] = base
    return lookup


def row_id(look_id: str, product_id: str, shade_id: str | None) -> str:
    digest = hashlib.sha1(f"{product_id}|{shade_id or ''}".encode()).hexdigest()[:12]
    return f"{look_id}-{digest}"


@dataclass(frozen=True)
class LinkPlan:
    rows: list[dict[str, Any]]
    skipped_zone: Counter[str]
    merged: int


@dataclass(frozen=True)
class LinkReport:
    mentions: int
    plan: LinkPlan
    mapped: list[str]
    unmapped: list[str]


def plan_links(mentions: Iterable[Mapping[str, Any]], shades: Mapping[str, str]) -> LinkPlan:
    """One row per look, product and shade; the first mention in the video wins."""
    rows: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    skipped: Counter[str] = Counter()
    merged = 0
    for mention in mentions:
        zone = mention["makeup_zone"]
        if zone not in ZONES:
            skipped[zone or "(none)"] += 1
            continue
        option_id = mention["oy_option_id"]
        shade_id = shades.get(option_id) if option_id else None
        key = (mention["look_id"], mention["product_id"], shade_id)
        if key in rows:
            merged += 1
            continue
        rows[key] = {
            "id": row_id(*key),
            "look_id": key[0],
            "makeup_zone": zone,
            "status": "unverified",
            "product_id": key[1],
            "shade_id": shade_id,
            "source_type": SOURCE_TYPE,
            "source_url": mention["video_url"],
            "evidence_text": mention["video_use_evidence"],
            "verified": False,
            "similarity_score": mention["similarity"],
            "recommendation_reason": None,
        }
    return LinkPlan(list(rows.values()), skipped, merged)


async def link_look_products(session: AsyncSession, write: bool) -> LinkReport:
    repository = LookVideoRepository(session)
    mentions = await repository.reviewed_mentions()
    options, shades = await repository.shade_sources(
        {m["oy_goods_no"] for m in mentions if m["oy_goods_no"]},
        {m["product_id"] for m in mentions},
    )
    plan = plan_links(mentions, shade_lookup(options, shades))
    looks = await repository.look_videos()
    linked = {row["look_id"] for row in plan.rows}
    mapped = sorted(looks[look] for look in linked)
    unmapped = sorted(video for look, video in looks.items() if look not in linked)
    if write:
        await repository.replace_look_products(
            SOURCE_TYPE,
            looks,
            plan.rows,
            {"mapped": mapped, "no_verified_products": unmapped},
        )
        await get_cache().delete_prefix("idol-looks")
    return LinkReport(len(mentions), plan, mapped, unmapped)
