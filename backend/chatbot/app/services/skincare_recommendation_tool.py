"""Independent candidate lookup; no Catalog condition or current-price verification."""

from app.clients.skincare_recommendation_client import SkincareRecommendationClient
from app.core.errors import UpstreamError
from app.schemas.skincare_recommendation import SkincareRecommendation, SkincareToolInput


class SkincareRecommendationTool:
    def __init__(self, client: SkincareRecommendationClient) -> None:
        self._client = client

    async def recommend(self, request: SkincareToolInput) -> SkincareRecommendation:
        body = {
            "detectedConcerns": [
                {"goal": goal, "sources": ["conversation"]} for goal in request.goals
            ]
        }
        if request.skin_type is not None:
            body["skinType"] = request.skin_type
        if request.irritation_signal is not None:
            body["irritationSignal"] = request.irritation_signal
        result = await self._client.recommend(body)
        coverage = {item.goal: item.status for item in result.coverage}
        if set(coverage) != set(result.by_concern) or not set(request.goals).issubset(coverage):
            raise UpstreamError("Skincare recommendation coverage is incomplete")
        matches = [(match, True) for match in result.overall_top10]
        for goal in result.by_concern:
            if (coverage[goal] == "ok") != bool(result.by_concern[goal]):
                raise UpstreamError("Skincare recommendation coverage is inconsistent")
            for match in result.by_concern[goal]:
                if not any(reason.goal == goal for reason in match.reasons):
                    raise UpstreamError("Skincare recommendation concern is inconsistent")
                matches.append((match, False))
        matches.extend((match, False) for match in result.balance_matches or [])
        profile_goals = set()
        if request.skin_type == "dry":
            profile_goals.add("dryness")
        elif request.skin_type == "oily":
            profile_goals.add("oiliness")
        if request.irritation_signal == "caution":
            profile_goals.add("sensitivity")
        for match, is_overall in matches:
            for reason in match.reasons:
                expected = set()
                if reason.goal in request.goals:
                    expected.add("conversation")
                if reason.goal in profile_goals:
                    expected.add("skinProfile")
                if not expected and not is_overall:
                    expected.add("concern")
                if (
                    not expected
                    or set(reason.sources) != expected
                    or len(reason.sources) != len(expected)
                ):
                    raise UpstreamError("Skincare recommendation source is inconsistent")
        return result
