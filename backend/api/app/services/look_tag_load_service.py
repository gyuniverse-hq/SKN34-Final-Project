"""Turn the merged look tag file into look_video_tags rows (option B) and load them.

Scores are the merged values (Gemini/Claude average or the single source), rounded to two
places; no evidence means NULL. Attributes keep every merged value, including both values of a
single-choice field the sources disagreed on, and only codes from the codebook file. An
unresolved conflict is left out unless an override settles it. Evidence keeps each source's
score, note, short quote and time for review, never the transcript. Videos a person has marked
user_reviewed are skipped so a re-run cannot overwrite them.
"""

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.look_video_repository import LookVideoRepository

CODEBOOK_PATH = Path(__file__).resolve().parents[2] / "seed" / "look_tag_codebook_v3.json"
TEXT_LIMIT = 120


@dataclass(frozen=True)
class Codebook:
    rubric_version: str
    scores: tuple[str, ...]
    fields: dict[str, frozenset[str]]


@dataclass
class TagPlan:
    rows: list[dict[str, Any]] = field(default_factory=list)
    skipped: Counter[str] = field(default_factory=Counter)
    dropped_values: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    statuses: Counter[str] = field(default_factory=Counter)


def load_codebook(path: Path = CODEBOOK_PATH) -> Codebook:
    data = json.loads(path.read_text(encoding="utf-8"))
    fields = {row[0]: frozenset(row[2]) for _, group in data["groups"] for row in group}
    return Codebook(data["rubric_version"], tuple(data["scores"]), fields)


def _short(text: Any) -> str | None:
    return text.strip()[:TEXT_LIMIT] if isinstance(text, str) and text.strip() else None


def _evidence(candidates: Iterable[Mapping[str, Any]], value_key: str) -> list[dict[str, Any]]:
    """Each source's value, time and short note or quote for one merged field."""
    rows = []
    for candidate in candidates:
        for item in candidate.get("evidence", []):
            entry = {
                "source": item.get("source"),
                value_key: item.get(value_key, candidate.get("value")),
                "start_seconds": item.get("start_seconds"),
                "quote": _short(item.get("quote")),
                "note": _short(item.get("note")),
            }
            rows.append({key: value for key, value in entry.items() if value is not None})
    return rows


def _score(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(round(float(value), 2)))


def build_row(
    video_row_id: str,
    youtube_id: str,
    video: Mapping[str, Any],
    codebook: Codebook,
    overrides: Mapping[str, list[str]],
    plan: TagPlan,
) -> dict[str, Any] | None:
    """One look_video_tags row, or None when the video carries no tag at all."""
    row: dict[str, Any] = {"video_id": video_row_id, "review_status": "ai_merged"}
    evidence: dict[str, Any] = {"scores": {}, "attributes": {}, "status": {}}
    for axis in codebook.scores:
        merged = video["scores"].get(axis) or {}
        row[axis] = _score(merged.get("selected_value"))
        if merged.get("candidates"):
            evidence["scores"][axis] = _evidence(merged["candidates"], "score")
            evidence["status"][axis] = merged["status"]
        plan.statuses[merged.get("status", "missing")] += 1

    attributes: dict[str, list[str]] = {}
    for name, allowed in codebook.fields.items():
        merged = video["attributes"].get(name) or {}
        plan.statuses[merged.get("status", "missing")] += 1
        value = overrides.get(name, merged.get("selected_value"))
        if merged.get("status") == "conflict" and name not in overrides:
            plan.unresolved.append(f"{youtube_id}.{name}")
            value = None
        values = [value] if isinstance(value, str) else list(value or [])
        kept = [item for item in dict.fromkeys(values) if item in allowed]
        plan.dropped_values += [
            f"{youtube_id}.{name}={item}" for item in values if item not in allowed
        ]
        if kept:
            attributes[name] = kept
        if merged.get("candidates"):
            evidence["attributes"][name] = _evidence(merged["candidates"], "values")
            evidence["status"][name] = "user_override" if name in overrides else merged["status"]

    tags = list(
        dict.fromkeys(
            (tag["type"], tag["zone"], tag["label"])
            for tag in video.get("tags", [])
            if tag.get("type") and tag.get("zone") and tag.get("label")
        )
    )
    if all(row[axis] is None for axis in codebook.scores) and not attributes and not tags:
        return None
    row["rubric_version"] = codebook.rubric_version
    row["attributes"] = attributes
    row["free_tags"] = [{"type": t, "zone": z, "label": label} for t, z, label in tags]
    row["evidence"] = evidence
    return row


def plan_tag_rows(
    merged: Mapping[str, Any],
    video_row_ids: Mapping[str, str],
    codebook: Codebook,
    overrides: Mapping[str, Mapping[str, list[str]]],
    reviewed: Iterable[str] = (),
) -> TagPlan:
    if merged.get("rubric_version") != codebook.rubric_version:
        raise ValueError(
            f"merged file is {merged.get('rubric_version')}, codebook is {codebook.rubric_version}"
        )
    plan = TagPlan()
    reviewed = set(reviewed)
    for youtube_id, video in merged["videos"].items():
        video_row_id = video_row_ids.get(youtube_id)
        if video_row_id is None:
            plan.skipped["not_registered"] += 1
            continue
        if video_row_id in reviewed:
            plan.skipped["user_reviewed"] += 1
            continue
        row = build_row(
            video_row_id, youtube_id, video, codebook, overrides.get(youtube_id, {}), plan
        )
        if row is None:
            plan.skipped["no_tags"] += 1
            continue
        plan.rows.append(row)
    return plan


async def load_look_tags(
    session: AsyncSession,
    merged: Mapping[str, Any],
    overrides: Mapping[str, Mapping[str, list[str]]],
    write: bool,
) -> TagPlan:
    repository = LookVideoRepository(session)
    existing, _ = await repository.registered_ids()
    plan = plan_tag_rows(
        merged, existing, load_codebook(), overrides, await repository.reviewed_tag_video_ids()
    )
    if write:
        if plan.unresolved:
            raise ValueError(
                "Settle these conflicts with --overrides first: " + ", ".join(plan.unresolved)
            )
        await repository.replace_video_tags(plan.rows)
    return plan
