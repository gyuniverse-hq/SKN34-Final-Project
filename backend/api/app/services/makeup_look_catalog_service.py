"""Load the style and celebrity curation into makeup_looks and mention payloads.

The style screen (style_looks.json, 73 videos) and the celebrity screen
(celebrity_videos.json, 34 videos) show videos that are already makeup_looks rows. This
classifies each of those looks, copies the curated title, order, start time and link status,
and keeps every curated product entry as source_payload on its raw mention, so the screens
can later read the database without changing what they show. Research columns are never
rewritten.

A run only fills looks that are still unclassified and payloads that are still empty. When
the database already holds a different value the plan reports a conflict and nothing is
written, so a re-run cannot overwrite a value that was edited in the database.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.makeup_look_catalog_repository import (
    CATALOG_FIELDS,
    MakeupLookCatalogRepository,
)

# Looks that have no curated JSON entry but are classified by a reviewed decision.
# S2nXySh1WuU (LOOK-002): actor Go Youn-jung's cover makeup, kept off the catalog until
# the app has her profile.
EXTRA_LOOKS: dict[str, dict[str, Any]] = {
    "S2nXySh1WuU": {"look_type": "celebrity", "celebrity_id": "goyounjung"},
}


@dataclass
class CatalogPlan:
    looks: dict[str, dict[str, Any]] = field(default_factory=dict)
    payloads: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    unchanged_looks: int = 0
    unchanged_payloads: int = 0
    conflicts: list[str] = field(default_factory=list)
    unclassified: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.conflicts


def _values(**kwargs: Any) -> dict[str, Any]:
    base = dict.fromkeys(CATALOG_FIELDS)
    base["is_catalog_published"] = False
    base.update(kwargs)
    return base


def desired_looks(
    style: Sequence[Mapping[str, Any]],
    celebrity: Sequence[Mapping[str, Any]],
    video_titles: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    """YouTube id -> catalog values the curation and reviewed decisions call for."""
    desired: dict[str, dict[str, Any]] = {}
    for position, look in enumerate(style, start=1):
        desired[look["id"]] = _values(
            look_type="style",
            style_group=look["group"],
            style_tag=look["tag"],
            catalog_title=look["title"],
            catalog_position=position,
            is_catalog_published=True,
        )
    for video in celebrity:
        # One curated entry has an empty title; the video's verified title is shown instead
        # while its link status stays needs_review.
        title = video["title"] or video_titles.get(video["id"], "")
        desired[video["id"]] = _values(
            look_type="celebrity",
            celebrity_id=video["celebrityId"],
            catalog_title=title,
            catalog_position=video["number"],
            catalog_start_seconds=video["startSeconds"],
            catalog_link_status=video["linkStatus"],
            is_catalog_published=True,
        )
    for youtube_id, values in EXTRA_LOOKS.items():
        if youtube_id in video_titles:
            desired[youtube_id] = _values(catalog_title=video_titles[youtube_id], **values)
    return desired


def plan_catalog(
    style: Sequence[Mapping[str, Any]],
    celebrity: Sequence[Mapping[str, Any]],
    looks: Sequence[Mapping[str, Any]],
    mentions: Mapping[tuple[str, str, int], Mapping[str, Any]],
) -> CatalogPlan:
    plan = CatalogPlan()
    by_video = {look["youtube_id"]: look for look in looks}
    titles = {look["youtube_id"]: look["video_title"] for look in looks}
    desired = desired_looks(style, celebrity, titles)

    for youtube_id in desired.keys() - by_video.keys():
        plan.conflicts.append(f"curated video without a makeup look: {youtube_id}")
    for youtube_id, look in by_video.items():
        values = desired.get(youtube_id)
        if values is None:
            plan.unclassified.append(look["look_id"])
            continue
        current = {name: look[name] for name in CATALOG_FIELDS}
        if current == values:
            plan.unchanged_looks += 1
        elif current["look_type"] is None:
            plan.looks[look["look_id"]] = values
        else:
            changed = sorted(k for k in CATALOG_FIELDS if current[k] != values[k])
            plan.conflicts.append(f"{look['look_id']} already differs in the database: {changed}")

    curated = [("style", look) for look in style] + [("celebrity", video) for video in celebrity]
    for source, entry in curated:
        for product in entry["products"]:
            key = (source, entry["id"], product["number"])
            mention = mentions.get(key)
            if mention is None:
                plan.conflicts.append(f"curated product without a raw mention: {key}")
            elif mention["source_payload"] == dict(product):
                plan.unchanged_payloads += 1
            elif mention["source_payload"] is None:
                plan.payloads.append((mention["source_row_id"], dict(product)))
            else:
                plan.conflicts.append(f"{mention['source_row_id']} payload differs in the database")
    return plan


async def load_makeup_look_catalog(
    session: AsyncSession,
    style: Sequence[Mapping[str, Any]],
    celebrity: Sequence[Mapping[str, Any]],
    write: bool,
) -> CatalogPlan:
    repository = MakeupLookCatalogRepository(session)
    plan = plan_catalog(
        style, celebrity, await repository.looks(), await repository.curated_mentions()
    )
    if write and plan.ok and (plan.looks or plan.payloads):
        await repository.apply(plan.looks, plan.payloads)
    return plan
