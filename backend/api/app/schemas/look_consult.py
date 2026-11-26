"""Read contracts for look consultation data: approved makeup troubleshooting advice and the
per-video look tags. Both are read-only views of reviewed data; nothing here is generated."""

from typing import Any

from app.schemas.base import ApiModel, OmitNoneModel


class TroubleshootingSourceLink(OmitNoneModel):
    title: str | None = None
    url: str | None = None


class TroubleshootingEvidence(OmitNoneModel):
    source_id: str
    title: str
    links: list[TroubleshootingSourceLink]
    source_note: str | None = None
    evidence_summary: str
    applies_to: str
    limitation: str


class TroubleshootingAdvice(ApiModel):
    """One approved situation. `evidence_scope` tells how strongly the sources back it
    (직접 / 응용 / 조건부); the serving view already excludes safety and unreviewed rows."""

    dataset_version: str
    situation_id: str
    problem_id: str
    category: str
    question: str
    clarifying_conditions: str
    selection_condition: str
    solution: str
    evidence_scope: str
    evidence: list[TroubleshootingEvidence]


class TroubleshootingResponse(ApiModel):
    advice: list[TroubleshootingAdvice]


class LookVideoTag(OmitNoneModel):
    """Tags of one look video. Every attribute value is a list; a missing key is unknown,
    and a single-choice field may still hold more than one code."""

    video_id: str
    youtube_id: str
    look_id: str | None = None
    review_status: str
    rubric_version: str
    scores: dict[str, float | None]
    attributes: dict[str, list[str]]
    free_tags: list[dict[str, Any]]


class LookVideoTagsResponse(ApiModel):
    tags: list[LookVideoTag]
