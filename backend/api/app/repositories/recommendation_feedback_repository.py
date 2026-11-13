"""Backend-only writes to migration 0020; replay-safe client event IDs."""

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import ApiError
from app.models.recommendation_feedback import (
    RecommendationCandidateRow as Candidate,
)
from app.models.recommendation_feedback import (
    RecommendationImpressionRow as Impression,
)
from app.models.recommendation_feedback import (
    RecommendationRequestRow as Request,
)
from app.models.recommendation_feedback import (
    UserBehaviorEventRow as Event,
)


class RecommendationFeedbackRepository:
    def __init__(self, session):
        self.session = session

    async def begin(self, values):
        self.session.add(Request(**values))
        await self.session.commit()

    async def finish(self, request_id, values, candidates):
        try:
            self.session.add_all(Candidate(**row) for row in candidates)
            await self.session.execute(
                update(Request).where(Request.request_id == request_id).values(**values)
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    async def candidate(self, candidate_id, member_id):
        row = (
            await self.session.execute(
                select(Candidate, Request.session_id)
                .join(Request, Candidate.request_id == Request.request_id)
                .where(
                    Candidate.candidate_id == candidate_id,
                    Request.member_id == member_id,
                    Request.status == "completed",
                    Candidate.final_rank.is_not(None),
                )
            )
        ).first()
        if not row:
            return None
        candidate, session_id = row
        return {
            "product_id": candidate.product_id,
            "option_id": candidate.option_id,
            "final_rank": candidate.final_rank,
            "session_id": session_id,
        }

    async def impression(self, impression_id, member_id):
        row = await self.session.get(Impression, impression_id)
        if row is None:
            return None
        return await self.candidate(row.candidate_id, member_id)

    async def insert_impression(self, values):
        await self._insert_once(Impression, values, "impression_id")

    async def insert_event(self, values):
        await self._insert_once(Event, values, "event_id")

    async def _insert_once(self, model, values, key):
        try:
            # Both the UUID and impression's (candidate, view, surface) key are unique.
            await self.session.execute(insert(model).values(**values).on_conflict_do_nothing())
            row = await self.session.get(model, values[key], populate_existing=True)
            if row is None or any(getattr(row, name) != value for name, value in values.items()):
                raise ApiError(409, "Event ID already used with different data", "event_conflict")
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
