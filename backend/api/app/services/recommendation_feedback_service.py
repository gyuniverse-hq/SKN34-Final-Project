"""Record V2 decisions and explicit, owned attribution; never infer a purchase."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.errors import ApiError
from app.repositories.member_repository import MemberRepository
from app.repositories.recommendation_feedback_repository import RecommendationFeedbackRepository
from app.services.recommendation_comparison_service import comparison_service
from app.services.recommendation_v2_service import POLICY, secondary_goal, target_goal

SERVING_CONTRACT = "recommend-v2-serving-history-v1"


def feedback_service(session, settings):
    return RecommendationFeedbackService(
        RecommendationFeedbackRepository(session),
        MemberRepository(session),
        comparison_service(session, settings),
        settings.env,
        settings.skin_recommendation_feedback_consented_members,
    )


def candidate_values(request_id, row):
    return {
        "candidate_id": uuid4(),
        "request_id": request_id,
        "product_id": row["productId"],
        "option_id": row["optionId"],
        "primary_ingredient_score": row.get("primaryIngredientScore", row["ingredientScore"]),
        "secondary_ingredient_score": row.get("secondaryIngredientScore"),
        "ingredient_score": row["ingredientScore"],
        "review_score": row["review"]["normalizedScore"],
        "v2_score": row["score"],
        "final_rank": row.get("rank"),
        "diversity_penalty": row.get("diversityPenalty") if "rank" in row else None,
        "selection_score": row.get("selectionScore") if "rank" in row else None,
        "evidence_snapshot": row,
    }


class RecommendationFeedbackService:
    def __init__(self, repository, members, comparison, environment, consented_members=()):
        self.repository = repository
        self.members = members
        self.comparison = comparison
        self.environment = environment
        self.consented_members = consented_members

    async def record_serving(
        self, body, member_id, session_id, goal, catalog, result, requested_at
    ):
        if member_id not in self.consented_members or not await self.members.get(member_id):
            return None
        request_id = uuid4()
        candidates = [candidate_values(request_id, row) for row in result["matches"]]
        await self.repository.record_completed(
            {
                "request_id": request_id,
                "member_id": member_id,
                "session_id": session_id,
                "requested_at": requested_at,
                "completed_at": datetime.now(UTC),
                "status": "completed",
                "environment": self.environment,
                "input_snapshot": {"analysis_version": body.analysis_version},
                "primary_concern": goal,
                "secondary_concern": result["secondaryConcern"],
                "contract_version": SERVING_CONTRACT,
                "feature_version": "age-gender-skin-primary-pore-wrinkle-tone-acne-v2",
                "ranking_policy_version": POLICY["version"],
                "policy_snapshot": deepcopy(POLICY),
                "v2_model_version": result["model"]["version"],
                "model_manifest": result["model"],
                "catalog_version": catalog.version,
                "catalog_digest": catalog.digest,
            },
            candidates,
        )
        return (
            {"requestId": str(request_id), "sessionId": str(session_id)},
            {row["option_id"]: str(row["candidate_id"]) for row in candidates},
        )

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
                "input_snapshot": body.input.model_dump(mode="json", exclude_none=True),
                "primary_concern": goal,
                "secondary_concern": secondary_goal(body.input, goal),
                "contract_version": "v2-comparison-history-v1",
                "feature_version": "age-gender-skin-primary-pore-wrinkle-tone-acne-v2"
                if body.input.analysis_version == "skin-analysis-v4.1"
                else "age-gender-skin-primary-pore-wrinkle-tone-v1",
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
            candidate = candidate_values(request_id, row)
            ids[row["optionId"]] = str(candidate["candidate_id"])
            candidates.append(candidate)
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

    def require_serving_consent(self, member_id, serving):
        if serving and member_id not in self.consented_members:
            raise ApiError(403, "Skin recommendation feedback is disabled", "feedback_disabled")

    async def impression(self, body, member_id, *, serving=False):
        self.require_serving_consent(member_id, serving)
        self.check_time(body.occurred_at)
        candidate = await self.repository.candidate(body.candidate_id, member_id)
        if not candidate or (candidate.get("contract_version") == SERVING_CONTRACT) != serving:
            raise ApiError(404, "Recommendation candidate not found", "candidate_not_found")
        if body.surface != ("skin_recommendations" if serving else "v2_comparison"):
            raise ApiError(422, "Recommendation surface does not match", "surface_mismatch")
        if candidate["final_rank"] != body.displayed_position:
            raise ApiError(422, "Displayed position does not match", "position_mismatch")
        await self.repository.insert_impression(body.model_dump(by_alias=False))
        return {"impressionId": str(body.impression_id)}

    async def event(self, body, member_id, *, serving=False):
        self.require_serving_consent(member_id, serving)
        if serving and body.event_type not in ("product_view", "cart_add"):
            raise ApiError(422, "Unsupported skin recommendation event", "unsupported_event_type")
        self.check_time(body.occurred_at)
        attribution = await self.repository.impression(body.impression_id, member_id)
        if not attribution or (attribution.get("contract_version") == SERVING_CONTRACT) != serving:
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
