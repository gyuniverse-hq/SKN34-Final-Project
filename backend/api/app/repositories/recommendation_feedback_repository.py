"""Backend-only feedback writes with replay-safe client event IDs."""

from sqlalchemy import distinct, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

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
from app.models.recommendation_feedback import SkincareRecommendationEventRow
from app.schemas.recommendation_feedback import SKINCARE_HISTORY_CONTRACT


class RecommendationFeedbackRepository:
    def __init__(self, session):
        self.session = session

    async def record_completed(self, values, candidates):
        try:
            self.session.add(Request(**values))
            await self.session.flush()
            self.session.add_all(Candidate(**row) for row in candidates)
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
                    Request.contract_version == SKINCARE_HISTORY_CONTRACT,
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

    async def insert_skincare_event(self, body):
        await self._insert_once(
            SkincareRecommendationEventRow,
            body.model_dump(
                by_alias=False, include={"event_id", "impression_id", "event_type", "occurred_at"}
            ),
            "event_id",
        )

    async def skincare_funnel(self, start, end, as_of, environment, members):
        session = (Request.member_id, Request.session_id)
        exposures = (
            select(
                *session,
                Candidate.product_id,
                Impression.impression_id,
                func.min(Impression.occurred_at).over(partition_by=session).label("first_exposure"),
            )
            .select_from(Request)
            .join(Candidate)
            .join(Impression)
            .where(
                Request.contract_version == SKINCARE_HISTORY_CONTRACT,
                Request.environment == environment,
                Request.member_id.in_(members),
                Impression.occurred_at <= as_of,
            )
            .cte("exposures")
        )
        cart = aliased(SkincareRecommendationEventRow)
        paid = aliased(SkincareRecommendationEventRow)
        product = (exposures.c.member_id, exposures.c.session_id, exposures.c.product_id)
        products = (
            select(
                *product,
                (func.count(cart.event_id) > 0).label("carted"),
                (func.count(paid.event_id) > 0).label("purchased"),
            )
            .outerjoin(
                cart,
                (cart.impression_id == exposures.c.impression_id)
                & (cart.event_type == "cart_add")
                & (cart.occurred_at <= as_of),
            )
            .outerjoin(
                paid,
                (paid.cart_event_id == cart.event_id)
                & (paid.event_type == "purchase_confirmed")
                & (paid.occurred_at <= as_of),
            )
            .where(exposures.c.first_exposure >= start, exposures.c.first_exposure < end)
            .group_by(*product)
            .cte("products")
        )
        sessions = func.count(distinct(tuple_(products.c.member_id, products.c.session_id)))
        totals = select(
            sessions.label("exposedSessions"),
            sessions.filter(products.c.carted).label("cartSessions"),
            sessions.filter(products.c.purchased).label("purchaseSessions"),
            func.count().filter(products.c.carted).label("cartedProducts"),
            func.count().filter(products.c.purchased).label("purchasedProducts"),
        )
        return dict((await self.session.execute(totals)).mappings().one())

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
