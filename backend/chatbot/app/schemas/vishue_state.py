from typing import NotRequired, TypedDict
from uuid import UUID

from app.schemas.chat import ChatResponse, Locale
from app.schemas.supervisor import IntentDecision, TaskPlan


class VishueState(TypedDict):
    """Internal state for one turn; the existing session repository owns persistence."""

    turn_id: UUID
    request_id: UUID | None
    thread_id: UUID | None
    result_set_id: str | None
    state_version: int | None
    locale: Locale
    decision: IntentDecision
    plan: NotRequired[TaskPlan]
    response: NotRequired[ChatResponse]


class DurableVishueState(TypedDict):
    """Only these per-run references may be written to PostgreSQL checkpoints."""

    request_id: str
    execution_status: str
