from collections.abc import Sequence
from typing import Any, Protocol

from fastapi import Depends

from app.core.db import get_session
from app.repositories.look_consult_repository import SCORE_COLUMNS, LookConsultRepository
from app.schemas.look_consult import LookVideoTag, TroubleshootingAdvice


class LookConsultStore(Protocol):
    async def troubleshooting(
        self, category: str | None, problem_id: str | None
    ) -> list[dict[str, Any]]: ...
    async def look_tags(self, ids: Sequence[str]) -> list[dict[str, Any]]: ...


def to_advice(row: dict[str, Any]) -> TroubleshootingAdvice:
    return TroubleshootingAdvice(
        dataset_version=row["dataset_version"],
        situation_id=row["situation_id"],
        problem_id=row["problem_id"],
        category=row["category"],
        question=row["question"],
        clarifying_conditions=row["clarifying_conditions"],
        selection_condition=row["selection_condition"],
        solution=row["solution_draft"],
        evidence_scope=row["solution_evidence_scope"],
        evidence=row["solution_evidence"] or [],
    )


def to_tag(row: dict[str, Any]) -> LookVideoTag:
    attributes = {
        key: value if isinstance(value, list) else [value]
        for key, value in (row["attributes"] or {}).items()
    }
    return LookVideoTag(
        video_id=row["video_id"],
        youtube_id=row["youtube_id"],
        look_id=row["look_id"],
        review_status=row["review_status"],
        rubric_version=row["rubric_version"],
        scores={name: None if row[name] is None else float(row[name]) for name in SCORE_COLUMNS},
        attributes=attributes,
        free_tags=row["free_tags"] or [],
    )


class LookConsultService:
    def __init__(self, store: LookConsultStore) -> None:
        self._store = store

    async def troubleshooting(
        self, category: str | None = None, problem_id: str | None = None
    ) -> list[TroubleshootingAdvice]:
        return [to_advice(row) for row in await self._store.troubleshooting(category, problem_id)]

    async def look_tags(self, ids: Sequence[str] = ()) -> list[LookVideoTag]:
        return [to_tag(row) for row in await self._store.look_tags(ids)]


def get_look_consult_service(session=Depends(get_session)) -> LookConsultService:
    return LookConsultService(LookConsultRepository(session))
