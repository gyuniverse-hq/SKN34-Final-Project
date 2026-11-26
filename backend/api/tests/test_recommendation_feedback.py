import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.db import get_session
from app.core.errors import ApiError
from app.repositories.recommendation_feedback_repository import RecommendationFeedbackRepository
from app.schemas.recommendation_feedback import SkincareEventInput, SkincareImpressionInput
from app.schemas.skincare import SkincareProfileRequest
from app.services.recommendation_feedback_service import RecommendationFeedbackService
from app.services.skincare_service import get_skincare_service, recommend_hybrid

PATH = "/api/recommendations/skincare/v4"


def service():
    repo = SimpleNamespace(
        candidate=AsyncMock(return_value=None),
        impression=AsyncMock(return_value=None),
        insert_impression=AsyncMock(),
        insert_skincare_event=AsyncMock(),
    )
    members = SimpleNamespace(get=AsyncMock(return_value=True))
    return RecommendationFeedbackService(repo, members, "test", {"owner"})


def impression(**changes):
    return SkincareImpressionInput.model_validate(
        {
            "impressionId": str(uuid4()),
            "candidateId": str(uuid4()),
            "viewInstanceId": str(uuid4()),
            "displayedPosition": 1,
            "surface": "skin_recommendations",
            "occurredAt": datetime.now(UTC),
            "visibilityPolicyVersion": "half-visible-500ms-v1",
            **changes,
        }
    )


def event(**changes):
    return SkincareEventInput.model_validate(
        {
            "eventId": str(uuid4()),
            "impressionId": str(uuid4()),
            "sessionId": str(uuid4()),
            "productId": "p",
            "optionId": "p-1",
            "eventType": "product_view",
            "occurredAt": datetime.now(UTC),
            **changes,
        }
    )


def test_impression_requires_consent_owned_candidate_and_original_rank():
    flow = service()
    payload = impression(displayedPosition=10)
    with pytest.raises(ApiError) as error:
        asyncio.run(flow.impression(payload, "other-member"))
    assert error.value.code == "feedback_disabled"
    flow.repository.candidate.assert_not_awaited()
    with pytest.raises(ApiError) as error:
        asyncio.run(flow.impression(payload, "owner"))
    assert error.value.code == "candidate_not_found"
    flow.repository.candidate.return_value = {"final_rank": 2}
    with pytest.raises(ApiError) as error:
        asyncio.run(flow.impression(payload, "owner"))
    assert error.value.code == "position_mismatch"
    flow.repository.insert_impression.assert_not_awaited()
    flow.repository.candidate.return_value["final_rank"] = 10
    assert asyncio.run(flow.impression(payload, "owner")) == {
        "impressionId": str(payload.impression_id),
    }
    flow.repository.candidate.assert_awaited_with(payload.candidate_id, "owner")


@pytest.mark.parametrize("field", ["session_id", "product_id", "option_id"])
def test_event_rejects_missing_or_mismatched_attribution(field):
    flow = service()
    payload = event()
    with pytest.raises(ApiError) as error:
        asyncio.run(flow.event(payload, "owner"))
    assert error.value.code == "impression_not_found"
    row = {key: getattr(payload, key) for key in ("session_id", "product_id", "option_id")}
    row[field] = uuid4() if field == "session_id" else "other"
    flow.repository.impression.return_value = row
    with pytest.raises(ApiError) as error:
        asyncio.run(flow.event(payload, "owner"))
    assert error.value.code == "attribution_mismatch"
    flow.repository.insert_skincare_event.assert_not_awaited()


def test_cart_is_product_level_and_client_cannot_claim_purchase_or_context():
    flow = service()
    payload = event(eventType="cart_add", optionId=None)
    flow.repository.impression.return_value = {
        "session_id": payload.session_id,
        "product_id": payload.product_id,
        "option_id": "p-1",
    }
    assert asyncio.run(flow.event(payload, "owner")) == {"eventId": str(payload.event_id)}
    flow.repository.insert_skincare_event.assert_awaited_once_with(payload)
    with pytest.raises(ApiError) as error:
        asyncio.run(flow.event(payload.model_copy(update={"option_id": "p-1"}), "owner"))
    assert error.value.code == "attribution_mismatch"
    for changes in (
        {"eventType": "purchase_confirmed"},
        {"eventType": "outbound_click"},
        {"memberId": "other"},
        {"contextSnapshot": {"image": "private"}},
        {"eventSource": "server"},
        {"occurredAt": "2026-11-13T01:00:00"},
    ):
        with pytest.raises(ValidationError):
            event(**changes)
    with pytest.raises(ApiError) as error:
        asyncio.run(
            flow.impression(impression(occurredAt=datetime.now(UTC) + timedelta(days=1)), "owner")
        )
    assert error.value.code == "invalid_event_time"


def test_legacy_recommendation_routes_are_retired(client):
    for path in (
        "/api/recommendations/skincare",
        "/api/recommendations/skincare/v2",
        "/api/recommendations/skin-v2",
        "/api/recommendations/skin-v2/recorded",
        "/api/recommendations/skin-v2/events",
        "/api/dev/recommendations/compare",
    ):
        assert client.post(path, json={}).status_code == 404


def test_recorded_route_requires_token_and_passes_only_verified_member(client):
    verifier = SimpleNamespace(
        verify=AsyncMock(
            return_value={
                "sub": "verified-member",
                "role": "authenticated",
                "email": "member@example.test",
            }
        )
    )
    result = recommend_hybrid(None, SkincareProfileRequest())
    flow = SimpleNamespace(recommend_recorded=AsyncMock(return_value=result))
    client.app.dependency_overrides[get_session] = lambda: None
    client.app.dependency_overrides[get_skincare_service] = lambda: flow
    payload = {"sessionId": str(uuid4()), "input": {"skinType": "dry"}}
    url = f"{PATH}/recorded"
    with patch("app.core.auth.get_verifier", return_value=verifier):
        assert client.post(url, json=payload).status_code == 401
        response = client.post(url, json=payload, headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert flow.recommend_recorded.await_args.args[1] == "verified-member"
        assert (
            client.post(
                url,
                json={**payload, "memberId": "fake"},
                headers={"Authorization": "Bearer test-token"},
            ).status_code
            == 400
        )
        flow.recommend_recorded.assert_awaited_once()


def test_repository_duplicate_payload_is_idempotent_and_conflicts_roll_back():
    payload = impression().model_dump(by_alias=False)
    session = SimpleNamespace(
        execute=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
        get=AsyncMock(return_value=SimpleNamespace(**deepcopy(payload))),
    )
    repo = RecommendationFeedbackRepository(session)
    asyncio.run(repo.insert_impression(payload))
    session.commit.assert_awaited_once()
    session.get.return_value.displayed_position = 2
    with pytest.raises(ApiError):
        asyncio.run(repo.insert_impression(payload))
    session.rollback.assert_awaited_once()
    session.commit.assert_awaited_once()


def test_recorded_route_accepts_conversation_without_relabeling(client):
    from tests.test_skincare_concern_fit import product, rule, snapshot

    verifier = SimpleNamespace(
        verify=AsyncMock(return_value={"sub": "verified-member", "role": "authenticated"})
    )
    request = {
        "detectedConcerns": [{"goal": "pores", "sources": ["conversation"]}],
    }
    data = snapshot([product("p", "p")], [rule("p", "pores", "ASTRINGENT")])
    result = recommend_hybrid(data, SkincareProfileRequest.model_validate(request))
    flow = SimpleNamespace(recommend_recorded=AsyncMock(return_value=result))
    client.app.dependency_overrides[get_session] = lambda: None
    client.app.dependency_overrides[get_skincare_service] = lambda: flow
    with patch("app.core.auth.get_verifier", return_value=verifier):
        response = client.post(
            f"{PATH}/recorded",
            json={"sessionId": str(uuid4()), "input": request},
            headers={"Authorization": "Bearer test-token"},
        )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    stored_request = flow.recommend_recorded.await_args.args[0].input
    assert stored_request.detected_concerns[0].sources == ["conversation"]
    assert stored_request.analysis_scores == {}
    assert stored_request.skin_type == stored_request.irritation_signal == "unknown"
    assert response.json()["overallTop10"][0]["reasons"][0]["sources"] == ["conversation"]


def test_recorded_conversation_keeps_existing_private_snapshot_policy():
    from app.schemas.recommendation_feedback import RecordedSkincareInput
    from app.services.skincare_service import SkincareService
    from tests.test_skincare_concern_fit import product, rule, snapshot

    data = snapshot([product("p", "p")], [rule("p", "pores", "ASTRINGENT")])
    repo = SimpleNamespace(read=AsyncMock(return_value=data))
    feedback = service()
    feedback.repository.record_completed = AsyncMock()
    req = RecordedSkincareInput.model_validate(
        {
            "sessionId": str(uuid4()),
            "input": {"detectedConcerns": [{"goal": "pores", "sources": ["conversation"]}]},
        }
    )
    result = asyncio.run(SkincareService(repo).recommend_recorded(req, "owner", feedback))
    request_record, candidates = feedback.repository.record_completed.await_args.args
    assert request_record["input_snapshot"] == {}
    assert request_record["policy_snapshot"] == {}
    assert all(candidate["evidence_snapshot"] == {} for candidate in candidates)
    assert result.history is not None
    assert result.overall_top10[0].reasons[0].sources == ["conversation"]
