"""Record V2 decisions and explicit, owned attribution; never infer a purchase."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.errors import ApiError
from app.repositories.member_repository import MemberRepository
from app.repositories.recommendation_feedback_repository import RecommendationFeedbackRepository
from app.services.recommendation_comparison_service import comparison_service
from app.services.recommendation_v2_service import POLICY, secondary_goal, target_goal


def feedback_service(session, settings):
    return RecommendationFeedbackService(
        RecommendationFeedbackRepository(session),
        MemberRepository(session),
        comparison_service(session, settings),
        settings.env,
    )


class RecommendationFeedbackService:
    def __init__(self, repository, members, comparison, environment):
        self.repository = repository
        self.members = members
        self.comparison = comparison
        self.environment = environment

    async def compare(self, body, member_id):
        if not await self.members.get(member_id):
            raise ApiError(403, "Member registration required", "member_required")
        request_id = uuid4()
        now = datetime.now(UTC)
        goal = target_goal(body.input)
        await self.repository.begin(
            {
                "request_id": request_id,
                "member_id": member_id,
                "session_id": body.session_id,
                "requested_at": now,
                "status": "running",
                "environment": self.environment,
                "input_snapshot": body.input.model_dump(mode="json"),
                "primary_concern": goal,
                "secondary_concern": secondary_goal(body.input, goal),
                "contract_version": "v2-comparison-history-v1",
                "feature_version": "age-gender-skin-primary-pore-wrinkle-tone-v1",
                "ranking_policy_version": POLICY["version"],
                "policy_snapshot": deepcopy(POLICY),
            }
        )
        audit = {}
        try:
            result = await self.comparison.compare(body.input, audit=audit)
        except Exception:
            await self.repository.finish(
                request_id,
                {
                    "status": "failed",
                    "completed_at": datetime.now(UTC),
                    "failure_code": "comparison_failed",
                },
                [],
            )
            raise
        v2 = result["v2"]
        success = v2["status"] == "ok"
        candidates = []
        ids = {}
        for row in audit.get("candidates", []) if success else []:
            candidate_id = uuid4()
            ids[row["optionId"]] = str(candidate_id)
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "request_id": request_id,
                    "product_id": row["productId"],
                    "option_id": row["optionId"],
                    "primary_ingredient_score": row.get(
                        "primaryIngredientScore", row["ingredientScore"]
                    ),
                    "secondary_ingredient_score": row.get("secondaryIngredientScore"),
                    "ingredient_score": row["ingredientScore"],
                    "review_score": row["review"]["normalizedScore"],
                    "v2_score": row["score"],
                    "final_rank": row.get("rank"),
                    "diversity_penalty": row.get("diversityPenalty") if "rank" in row else None,
                    "selection_score": row.get("selectionScore") if "rank" in row else None,
                    "evidence_snapshot": row,
                }
            )
        model = v2.get("model")
        await self.repository.finish(
            request_id,
            {
                "status": "completed" if success else "failed",
                "completed_at": datetime.now(UTC),
                "failure_code": None
                if success
                else (
                    "catalog_unavailable" if v2["status"] == "catalog_unavailable" else "v2_failed"
                ),
                "v2_model_version": model.get("version") if model else None,
                "model_manifest": model,
                "catalog_version": result["versions"].get("catalogVersion"),
                "catalog_digest": result["versions"].get("catalogDigest"),
                "recommendation_evidence": {
                    "catalog": audit.get("catalog"),
                    "ranking": {k: v for k, v in v2.items() if k != "matches"},
                },
            },
            candidates,
        )
        for match in v2["matches"]:
            match["candidateId"] = ids[match["optionId"]]
        result["history"] = {"requestId": str(request_id), "sessionId": str(body.session_id)}
        return result

    @staticmethod
    def check_time(occurred_at):
        if occurred_at > datetime.now(UTC) + timedelta(minutes=5):
            raise ApiError(422, "Event time is in the future", "invalid_event_time")

    async def impression(self, body, member_id):
        self.check_time(body.occurred_at)
        candidate = await self.repository.candidate(body.candidate_id, member_id)
        if not candidate:
            raise ApiError(404, "Recommendation candidate not found", "candidate_not_found")
        if candidate["final_rank"] != body.displayed_position:
            raise ApiError(422, "Displayed position does not match", "position_mismatch")
        await self.repository.insert_impression(body.model_dump(by_alias=False))
        return {"impressionId": str(body.impression_id)}

    async def event(self, body, member_id):
        self.check_time(body.occurred_at)
        attribution = await self.repository.impression(body.impression_id, member_id)
        if not attribution:
            raise ApiError(404, "Recommendation impression not found", "impression_not_found")
        if any(attribution[key] != getattr(body, key) for key in ("session_id", "product_id")):
            raise ApiError(422, "Recommendation attribution does not match", "attribution_mismatch")
        if body.option_id != attribution["option_id"] and not (
            body.option_id is None and body.event_type == "cart_add"
        ):
            raise ApiError(422, "Recommendation option does not match", "attribution_mismatch")
        await self.repository.insert_event(
            {
                **body.model_dump(by_alias=False),
                "member_id": member_id,
                "event_source": "client",
                "event_schema_version": "v2-feedback-v1",
                "attribution_policy_version": "explicit-impression-v1",
                "context_snapshot": {"scope": "product" if body.option_id is None else "option"},
            }
        )
        return {"eventId": str(body.event_id)}
