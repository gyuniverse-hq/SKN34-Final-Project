import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.errors import ApiError
from app.schemas.recommendation_comparison import SkinV2Response
from app.services.recommendation_feedback_service import (
    SERVING_CONTRACT,
    RecommendationFeedbackService,
)
from app.services.recommendation_v2_service import predict_seeds
from app.services.skin_v2_service import SkinV2Service
from tests.conftest import make_product
from tests.test_recommendation_comparison import body, catalog, option


def test_serving_runs_v4_and_returns_the_ranked_catalog_products():
    settings = Settings(_env_file=None, recommendation_model="recommend-cat-v4")
    request = body(
        analysisVersion="skin-analysis-v4.1",
        scores={
            "pores": 0.8,
            "pigmentation": 0.2,
            "wrinkles": 0.4,
            "acne": 0.7,
        },
    )
    seeds, _ = predict_seeds(request, "pores", str(settings.recommendation_bundle_path))
    options = [
        option(f"p{i}", [seed["id"]]).model_copy(
            update={
                "product": make_product(f"p{i}", "skincare", []),
                "option_name": f"Option {i}",
                "price_krw": 10000 + i,
            }
        )
        for i, seed in enumerate(seeds)
    ]
    repository = type("Repository", (), {"read": AsyncMock(return_value=catalog(options))})()
    feedback_repo = SimpleNamespace(record_completed=AsyncMock())
    members = SimpleNamespace(get=AsyncMock(return_value=True))
    feedback = RecommendationFeedbackService(feedback_repo, members, None, "test", {"member"})
    service = SkinV2Service(repository, settings, feedback)
    session_id = uuid4()
    result = asyncio.run(service.recommend(request, member_id="member", session_id=session_id))
    assert result["targetConcern"] == "pores"
    assert len(result["matches"]) == 5
    assert {m["product"]["id"] for m in result["matches"]} == {o.product_id for o in options}
    assert all(m["priceKRW"] >= 10000 and m["optionName"] for m in result["matches"])
    repository.read.assert_awaited_once_with(include_products=True)
    values, candidates = feedback_repo.record_completed.call_args.args
    public_result = SkinV2Response.model_validate(result).model_dump(mode="json", by_alias=True)
    assert public_result["history"] == {
        "requestId": str(values["request_id"]),
        "sessionId": str(session_id),
    }
    assert values["contract_version"] == SERVING_CONTRACT
    assert values["v2_model_version"] == "recommend-cat-v4"
    assert values["input_snapshot"] == {"analysis_version": "skin-analysis-v4.1"}
    assert [(m["candidateId"], m["product"]["id"]) for m in public_result["matches"]] == [
        (str(row["candidate_id"]), row["product_id"]) for row in candidates
    ]
    assert [row["final_rank"] for row in candidates] == list(range(1, 6))
    unrecorded = asyncio.run(service.recommend(request, member_id="other", session_id=session_id))
    assert "history" not in unrecorded
    assert [m["product"] for m in unrecorded["matches"]] == [
        m["product"] for m in result["matches"]
    ]
    feedback_repo.record_completed.assert_awaited_once()


def test_older_analysis_and_wrong_model_are_not_silently_substituted():
    repository = type("Repository", (), {"read": AsyncMock()})()
    service = SkinV2Service(
        repository, Settings(_env_file=None, recommendation_model="recommend-cat-v4")
    )
    with pytest.raises(ApiError) as error:
        asyncio.run(service.recommend(body()))
    assert error.value.code == "acne_score_required"
    service.settings = Settings(_env_file=None, recommendation_model="recommend-cat-v3")
    with pytest.raises(ApiError) as error:
        asyncio.run(
            service.recommend(
                body(
                    analysisVersion="skin-analysis-v4.1",
                    scores={
                        "pores": 0.8,
                        "pigmentation": 0.2,
                        "wrinkles": 0.4,
                        "acne": 0.7,
                    },
                )
            )
        )
    assert error.value.code == "recommendation_unavailable"
    repository.read.assert_not_awaited()
