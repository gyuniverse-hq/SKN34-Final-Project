"""Record skin recommendation decisions and explicit, owned user interactions."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.core.db import session_scope
from app.core.errors import ApiError
from app.repositories.member_repository import MemberRepository
from app.repositories.recommendation_feedback_repository import RecommendationFeedbackRepository
from app.schemas.recommendation_feedback import SKINCARE_HISTORY_CONTRACT
from app.schemas.skincare import HybridResponse, SkincareHistory


def feedback_service(session, settings):
    return RecommendationFeedbackService(
        RecommendationFeedbackRepository(session),
        MemberRepository(session),
        settings.env,
        settings.skin_recommendation_feedback_consented_members,
    )


async def skincare_funnel_report(start, end, as_of, settings):
    async with session_scope() as session:
        counts = await RecommendationFeedbackRepository(session).skincare_funnel(
            start, end, as_of, settings.env, settings.skin_recommendation_feedback_consented_members
        )
    exposed = counts["exposedSessions"]
    carts = counts["cartSessions"]
    carted_products = counts["cartedProducts"]
    return {
        **counts,
        "cartRate": carts / exposed if exposed else None,
        "cartedProductsPer100Sessions": 100 * carted_products / exposed if exposed else None,
        "cartToPurchaseRate": counts["purchaseSessions"] / carts if carts else None,
        "productCartToPurchaseRate": (
            counts["purchasedProducts"] / carted_products if carted_products else None
        ),
    }


class RecommendationFeedbackService:
    def __init__(self, repository, members, environment, consented_members=()):
        self.repository = repository
        self.members = members
        self.environment = environment
        self.consented_members = consented_members

    async def record_skincare(
        self, result: HybridResponse, member_id: str, session_id: UUID, requested_at: datetime
    ) -> None:
        ranked = result.overall_top10
        if not ranked or member_id not in self.consented_members:
            return
        if not await self.members.get(member_id):
            return
        request_id = uuid4()
        candidates = [
            {
                "candidate_id": uuid4(),
                "request_id": request_id,
                "product_id": match.product.id,
                "option_id": match.option_id,
                "final_rank": rank,
                "evidence_snapshot": {},
            }
            for rank, match in enumerate(ranked, start=1)
        ]
        await self.repository.record_completed(
            {
                "request_id": request_id,
                "member_id": member_id,
                "session_id": session_id,
                "requested_at": requested_at,
                "completed_at": datetime.now(UTC),
                "status": "completed",
                "environment": self.environment,
                "input_snapshot": {},
                "primary_concern": "profile",
                "contract_version": SKINCARE_HISTORY_CONTRACT,
                "feature_version": "profile-care-goals-v1",
                "ranking_policy_version": result.strategy_version,
                "policy_snapshot": {},
                "catalog_version": result.data_version,
            },
            candidates,
        )
        ids = {row["option_id"]: row["candidate_id"] for row in candidates}
        for match in [*ranked, *result.overall_top5]:
            match.candidate_id = ids[match.option_id]
        result.history = SkincareHistory(request_id=request_id, session_id=session_id)

    @staticmethod
    def check_time(occurred_at):
        if occurred_at > datetime.now(UTC) + timedelta(minutes=5):
            raise ApiError(422, "Event time is in the future", "invalid_event_time")

    def require_consent(self, member_id):
        if member_id not in self.consented_members:
            raise ApiError(403, "Skin recommendation feedback is disabled", "feedback_disabled")

    async def impression(self, body, member_id):
        self.require_consent(member_id)
        self.check_time(body.occurred_at)
        candidate = await self.repository.candidate(body.candidate_id, member_id)
        if not candidate:
            raise ApiError(404, "Recommendation candidate not found", "candidate_not_found")
        if candidate["final_rank"] != body.displayed_position:
            raise ApiError(422, "Displayed position does not match", "position_mismatch")
        await self.repository.insert_impression(body.model_dump(by_alias=False))
        return {"impressionId": str(body.impression_id)}

    async def event(self, body, member_id):
        self.require_consent(member_id)
        self.check_time(body.occurred_at)
        attribution = await self.repository.impression(body.impression_id, member_id)
        if not attribution:
            raise ApiError(404, "Recommendation impression not found", "impression_not_found")
        expected_option = None if body.event_type == "cart_add" else attribution["option_id"]
        if (
            body.session_id != attribution["session_id"]
            or body.product_id != attribution["product_id"]
            or body.option_id != expected_option
        ):
            raise ApiError(422, "Recommendation attribution does not match", "attribution_mismatch")
        await self.repository.insert_skincare_event(body)
        return {"eventId": str(body.event_id)}
