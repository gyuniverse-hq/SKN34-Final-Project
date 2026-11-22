"""Serve V2 recommendations without running the comparison branch."""

import logging
from datetime import UTC, datetime

from fastapi import Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.repositories.recommendation_comparison_repository import ComparisonRepository
from app.schemas.recommendation_comparison import ComparisonInput
from app.services.recommendation_feedback_service import feedback_service
from app.services.recommendation_v2_service import recommend_v2, target_goal

logger = logging.getLogger(__name__)


class SkinV2Service:
    def __init__(self, repository, settings, feedback=None):
        self.repository = repository
        self.settings = settings
        self.feedback = feedback

    async def recommend(self, body: ComparisonInput, *, member_id=None, session_id=None) -> dict:
        requested_at = datetime.now(UTC)
        if body.analysis_version != "skin-analysis-v4.1" or body.scores.acne is None:
            raise ApiError(422, "New skin analysis required", "acne_score_required")
        if self.settings.recommendation_model != "recommend-cat-v4":
            raise ApiError(503, "Recommendation model unavailable", "recommendation_unavailable")
        try:
            catalog = await self.repository.read(include_products=True)
            goal = target_goal(body)
            result = await run_in_threadpool(
                recommend_v2,
                body,
                goal,
                catalog,
                str(self.settings.recommendation_bundle_path),
                model_name="recommend-cat-v4",
            )
            options = {option.option_id: option for option in catalog.options}
            matches = []
            for row in result["matches"]:
                option = options.get(row["optionId"])
                if (
                    option is None
                    or option.product is None
                    or option.product.id != row["productId"]
                ):
                    raise ValueError("Recommendation product does not match catalog")
                matches.append(
                    {
                        "product": option.product.model_dump(mode="json", by_alias=True),
                        "optionId": option.option_id,
                        "optionName": option.option_name,
                        "priceKRW": option.price_krw,
                    }
                )
        except Exception:
            logger.exception("V2 skin recommendation unavailable")
            raise ApiError(
                503, "Recommendation unavailable", "recommendation_unavailable"
            ) from None
        response = {"targetConcern": goal, "matches": matches}
        if self.feedback is not None and member_id is not None and session_id is not None:
            try:
                recorded = await self.feedback.record_serving(
                    body, member_id, session_id, goal, catalog, result, requested_at
                )
            except SQLAlchemyError:
                logger.warning("Skin recommendation history write failed", exc_info=False)
            else:
                if recorded is not None:
                    response["history"], candidates = recorded
                    for match in matches:
                        match["candidateId"] = candidates[match["optionId"]]
        return response


def get_skin_v2_service(session: AsyncSession = Depends(get_session)) -> SkinV2Service:
    settings = get_settings()
    return SkinV2Service(
        ComparisonRepository(session), settings, feedback_service(session, settings)
    )
