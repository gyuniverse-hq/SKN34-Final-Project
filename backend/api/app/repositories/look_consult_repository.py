"""Read the approved troubleshooting view and the look video tags. Read-only; no caching, so
an approval or tag change in the database is visible on the next request."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idol_look import LOOK_TAG_SCORE_COLUMNS

SCORE_COLUMNS = LOOK_TAG_SCORE_COLUMNS

TROUBLESHOOTING_SQL = text(
    """
    SELECT dataset_version, situation_id, problem_id, category, question,
           clarifying_conditions, selection_condition, solution_draft,
           solution_evidence_scope, solution_evidence
    FROM makeup_troubleshooting_serving
    WHERE (CAST(:category AS text) IS NULL OR category = :category)
      AND (CAST(:problem_id AS text) IS NULL OR problem_id = :problem_id)
    ORDER BY problem_id, situation_id
    """
)

_SCORES = ", ".join(f"t.{name}" for name in LOOK_TAG_SCORE_COLUMNS)
LOOK_TAGS_SQL = text(
    f"""
    SELECT t.video_id, v.video_id AS youtube_id, l.id AS look_id, t.review_status,
           t.rubric_version, {_SCORES}, t.attributes, t.free_tags
    FROM look_video_tags t
    JOIN youtube_videos v ON v.id = t.video_id
    LEFT JOIN makeup_looks l ON l.video_id = v.id
    WHERE (:all_videos OR t.video_id IN :videos OR v.video_id IN :videos OR l.id IN :videos)
    ORDER BY t.video_id
    """
).bindparams(bindparam("videos", expanding=True))


class LookConsultRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def troubleshooting(
        self, category: str | None, problem_id: str | None
    ) -> list[dict[str, Any]]:
        result = await self._session.execute(
            TROUBLESHOOTING_SQL, {"category": category, "problem_id": problem_id}
        )
        return [dict(row) for row in result.mappings()]

    async def look_tags(self, ids: Sequence[str]) -> list[dict[str, Any]]:
        """Tags for the given VIDEO-xxx ids, YouTube ids or LOOK-xxx ids; every row when empty."""
        result = await self._session.execute(
            LOOK_TAGS_SQL, {"all_videos": not ids, "videos": list(ids) or [""]}
        )
        return [dict(row) for row in result.mappings()]
