"""Keep V1 and V2 independent and report snapshot mismatches explicitly."""

import asyncio
import hashlib
import json

from fastapi.concurrency import run_in_threadpool

from app.clients.recommendation_v1_client import fetch_v1
from app.core.config import Settings
from app.repositories.recommendation_comparison_repository import ComparisonRepository
from app.schemas.recommendation_comparison import ComparisonInput
from app.services.recommendation_v2_service import recommend_v2, target_goal

SKIN_TYPES = {"건성": "dry", "중성": "balanced", "지성": "oily", "복합성": "unknown"}


def comparison_service(session, settings):
    return ComparisonService(ComparisonRepository(session), settings)


class ComparisonService:
    def __init__(self, repository: ComparisonRepository, settings: Settings):
        self.repository = repository
        self.settings = settings

    async def compare(self, body: ComparisonInput, *, audit: dict | None = None) -> dict:
        goal = target_goal(body)
        request = {
            "primaryGoal": goal,
            "secondaryGoals": [],
            "skinType": SKIN_TYPES[body.skin_type],
            "irritationSignal": body.irritation_signal,
            "goalPolicyVersion": "care-goals-v1",
            "limit": 5,
            "includeTrace": True,
        }
        v1, catalog = await asyncio.gather(
            fetch_v1(self.settings.recommendation_v1_url, request),
            self.repository.read(),
            return_exceptions=True,
        )
        v1_result = {"status": "v1_unavailable", "matches": []}
        if not isinstance(v1, BaseException):
            selected = {m["optionId"] for m in v1["matches"]}
            trace = v1.get("trace") or {}
            v1_result = {
                "status": "ok",
                "request": request,
                "strategyVersion": v1.get("strategyVersion"),
                "dataVersion": v1.get("dataVersion"),
                "coverage": v1.get("coverage", []),
                "matches": v1["matches"],
                "selectedTrace": [o for o in trace.get("options", []) if o["optionId"] in selected],
                "reviewPrior": trace.get("reviewPrior"),
                "reviewBaseline": trace.get("reviewBaseline"),
            }
        v2_result = {"status": "catalog_unavailable", "matches": []}
        versions = {"v1Runtime": self.settings.recommendation_v1_revision}
        if not isinstance(catalog, BaseException):
            versions.update(
                {
                    "catalogVersion": catalog.version,
                    "catalogDigest": catalog.digest,
                    "sourceManifest": catalog.source_manifest,
                }
            )
            try:
                v2_result = await run_in_threadpool(
                    recommend_v2,
                    body,
                    goal,
                    catalog,
                    self.settings.recommendation_v2_bundle or "",
                    **({"audit": audit} if audit is not None else {}),
                )
            except Exception as error:
                # A visible per-branch failure preserves the other result; no fake fallback.
                v2_result = {
                    "status": "v2_failed",
                    "errorType": type(error).__name__,
                    "matches": [],
                }
        ids1 = {r["product"]["id"] for r in v1_result["matches"]}
        ids2 = {r["productId"] for r in v2_result["matches"]}
        serialized = body.model_dump(mode="json")
        return {
            "input": serialized,
            "inputHash": hashlib.sha256(
                json.dumps(serialized, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest(),
            "targetConcern": goal,
            "goalPolicy": "max-caution-score-v1; ties: pores,pigmentation,wrinkles",
            "v1": v1_result,
            "v2": v2_result,
            "versions": versions,
            "sameSnapshot": bool(versions.get("catalogVersion"))
            and v1_result.get("dataVersion") == versions.get("catalogVersion"),
            "overlapProductIds": sorted(ids1 & ids2),
            "limitations": [
                "experimental_not_product_accuracy",
                "product_usage_screening_uses_explicit_titles_not_verified_instructions",
                "ranking_weights_are_initial_policy_not_optimized",
                "survey_respondent_count_equals_reviews_user_confirmed",
                "survey_priors_fitted_on_940_products_not_recommendation_accuracy",
                "rating_counts_reconstructed_from_rounded_percentages",
                "rating_lower10_is_a_conservative_policy_not_optimized_accuracy",
                "suitability_geometric_mean_is_not_joint_personal_effect_probability",
                "suitability_lambda_020_is_user_selected_not_optimized",
                "secondary_threshold_050_and_primary_weight_075_are_initial_policy",
                "cross_indicator_score_calibration_not_validated",
                "pigmentation_and_wrinkles_share_brightening_firming_survey",
                "v1_basic_endpoint_uses_ratings_v2_ports_v1_survey_component",
                "training_roi_and_mobile_preprocessing_differ",
                "automatic_goal_differs_from_training_source_target",
                "v1_receives_supported_fields_only",
            ],
        }
