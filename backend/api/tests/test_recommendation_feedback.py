import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import ApiError
from app.schemas.recommendation_feedback import (
    RecommendationEventInput,
    RecommendationImpressionInput,
    RecordedComparisonInput,
)
from app.services.recommendation_feedback_service import RecommendationFeedbackService
from app.services.recommendation_v2_service import rank_products
from tests.test_recommendation_comparison import body, catalog, option


def service():
    repo = SimpleNamespace(
        **{
            key: AsyncMock()
            for key in (
                "begin",
                "finish",
                "candidate",
                "impression",
                "insert_impression",
                "insert_event",
            )
        }
    )
    members = SimpleNamespace(get=AsyncMock(return_value=True))
    comparison = SimpleNamespace(compare=AsyncMock())
    return RecommendationFeedbackService(repo, members, comparison, "test")


def impression(**changes):
    return RecommendationImpressionInput.model_validate(
        {
            "impressionId": str(uuid4()),
            "candidateId": str(uuid4()),
            "viewInstanceId": str(uuid4()),
            "displayedPosition": 1,
            "occurredAt": datetime.now(UTC),
            "visibilityPolicyVersion": "half-visible-500ms-v1",
            **changes,
        }
    )


def event(**changes):
    return RecommendationEventInput.model_validate(
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


def test_audit_preserves_all_options_and_does_not_change_rankings():
    duplicate = option("p0", [1]).model_copy(update={"option_id": "p0-other"})
    data = catalog(
        [option(f"p{i}", [1]) for i in range(7)] + [duplicate, option("irrelevant", [9])]
    )
    seeds = [{"id": 1, "score": 0.8}]
    original = rank_products(seeds, [], data, "pores")
    audit = {}
    assert rank_products(seeds, [], data, "pores", audit=audit) == original
    assert len(audit["candidates"]) == 8
    assert sum("rank" in row for row in audit["candidates"]) == 5
    for row in audit["candidates"]:
        assert row["catalogOption"]["ingredientIds"] == [1]
        assert "surveyRatios" in row["catalogOption"]["review"]
        if "rank" not in row:
            assert "selectionScore" not in row and "diversityPenalty" not in row


def test_recorded_run_saves_all_candidates_versions_and_server_owned_member():
    flow = service()
    source = catalog([option(f"p{i}", [1]) for i in range(6)])

    async def compare(_body, *, audit):
        result = rank_products([{"id": 1, "score": 0.8}], [], source, "pores", audit=audit)
        return {
            "v2": {"status": "ok", "model": {"version": "model-v1", "sha256": "hash"}, **result},
            "versions": {"catalogVersion": "catalog-v1", "catalogDigest": "digest"},
        }

    flow.comparison.compare.side_effect = compare
    request = RecordedComparisonInput(session_id=uuid4(), input=body())
    result = asyncio.run(flow.compare(request, "member-a"))
    start = flow.repository.begin.call_args.args[0]
    assert start["member_id"] == "member-a" and start["environment"] == "test"
    assert start["input_snapshot"]["scoreKind"] == "binary_caution_probability"
    assert start["input_snapshot"]["aggregation"] == request.input.aggregation
    request_id, finish, candidates = flow.repository.finish.call_args.args
    assert str(request_id) == result["history"]["requestId"]
    assert finish["status"] == "completed" and finish["catalog_digest"] == "digest"
    assert finish["completed_at"] >= start["requested_at"]
    assert len(candidates) == 6
    assert {str(c["candidate_id"]) for c in candidates if c["final_rank"]} == {
        r["candidateId"] for r in result["v2"]["matches"]
    }
    unused = next(c for c in candidates if c["final_rank"] is None)
    assert unused["selection_score"] is None and unused["diversity_penalty"] is None


@pytest.mark.parametrize("status", ["catalog_unavailable", "v2_failed"])
def test_failed_branch_is_recorded_without_fake_candidates(status):
    flow = service()
    flow.comparison.compare.return_value = {"v2": {"status": status, "matches": []}, "versions": {}}
    asyncio.run(flow.compare(RecordedComparisonInput(session_id=uuid4(), input=body()), "member"))
    _, values, rows = flow.repository.finish.call_args.args
    assert values["status"] == "failed" and values["failure_code"] == status and rows == []


def test_exception_records_bounded_failure_and_missing_member_never_starts():
    flow = service()
    request = RecordedComparisonInput(session_id=uuid4(), input=body())
    flow.members.get.return_value = None
    with pytest.raises(ApiError):
        asyncio.run(flow.compare(request, "unknown"))
    flow.repository.begin.assert_not_called()
    flow.members.get.return_value = True
    flow.comparison.compare.side_effect = RuntimeError("sensitive details")
    with pytest.raises(RuntimeError):
        asyncio.run(flow.compare(request, "member"))
    values = flow.repository.finish.call_args.args[1]
    assert values["failure_code"] == "comparison_failed"
    assert "sensitive" not in str(values)


def test_impression_requires_owned_selected_candidate_and_original_rank():
    flow = service()
    payload = impression()
    flow.repository.candidate.return_value = None
    with pytest.raises(ApiError):
        asyncio.run(flow.impression(payload, "other-member"))
    flow.repository.insert_impression.assert_not_called()
    flow.repository.candidate.return_value = {"final_rank": 2}
    with pytest.raises(ApiError):
        asyncio.run(flow.impression(payload, "owner"))
    flow.repository.candidate.return_value = {"final_rank": 1}
    asyncio.run(flow.impression(payload, "owner"))
    flow.repository.candidate.assert_awaited_with(payload.candidate_id, "owner")
    assert (
        flow.repository.insert_impression.call_args.args[0]["impression_id"]
        == payload.impression_id
    )


@pytest.mark.parametrize("field", ["session_id", "product_id", "option_id"])
def test_event_rejects_missing_or_mismatched_attribution(field):
    flow = service()
    payload = event()
    flow.repository.impression.return_value = None
    with pytest.raises(ApiError):
        asyncio.run(flow.event(payload, "other-member"))
    row = {key: getattr(payload, key) for key in ("session_id", "product_id", "option_id")}
    row[field] = uuid4() if field == "session_id" else "other"
    flow.repository.impression.return_value = row
    with pytest.raises(ApiError):
        asyncio.run(flow.event(payload, "member"))
    flow.repository.insert_event.assert_not_called()


def test_cart_is_product_level_and_client_cannot_claim_purchase_or_context():
    flow = service()
    payload = event(eventType="cart_add", optionId=None)
    flow.repository.impression.return_value = {
        "session_id": payload.session_id,
        "product_id": "p",
        "option_id": "p-1",
    }
    asyncio.run(flow.event(payload, "owner"))
    values = flow.repository.insert_event.call_args.args[0]
    assert values["member_id"] == "owner" and values["event_source"] == "client"
    assert values["option_id"] is None and values["context_snapshot"] == {"scope": "product"}
    for changes in (
        {"eventType": "purchase_confirmed"},
        {"memberId": "other"},
        {"contextSnapshot": {"image": "private"}},
        {"eventSource": "server"},
        {"occurredAt": "2026-11-13T01:00:00"},
    ):
        with pytest.raises(ValidationError):
            event(**changes)
    with pytest.raises(ApiError):
        asyncio.run(
            flow.impression(impression(occurredAt=datetime.now(UTC) + timedelta(days=1)), "owner")
        )


def test_recording_routes_keep_production_gate(client):
    with patch(
        "app.routers.recommendation_comparison.get_settings",
        return_value=Settings(
            env="production",
            recommendation_comparison_enabled=True,
        ),
    ):
        for route in ("compare/recorded", "impressions", "events"):
            assert client.post(f"/api/dev/recommendations/{route}", json={}).status_code == 404


def test_recorded_route_requires_token_and_passes_only_verified_member(client):
    from app.core.db import get_session

    verifier = SimpleNamespace(
        verify=AsyncMock(
            return_value={
                "sub": "verified-member",
                "role": "authenticated",
                "email": "member@example.test",
            }
        )
    )
    flow = SimpleNamespace(compare=AsyncMock(return_value={"history": {"requestId": "test"}}))
    client.app.dependency_overrides[get_session] = lambda: None
    payload = RecordedComparisonInput(session_id=uuid4(), input=body()).model_dump(mode="json")
    with (
        patch(
            "app.routers.recommendation_comparison.get_settings",
            return_value=Settings(
                env="test",
                recommendation_comparison_enabled=True,
            ),
        ),
        patch("app.core.auth.get_verifier", return_value=verifier),
        patch("app.routers.recommendation_comparison.feedback_service", return_value=flow),
    ):
        assert (
            client.post("/api/dev/recommendations/compare/recorded", json=payload).status_code
            == 401
        )
        response = client.post(
            "/api/dev/recommendations/compare/recorded",
            json=payload,
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert flow.compare.call_args.args[1] == "verified-member"
        assert (
            client.post(
                "/api/dev/recommendations/compare/recorded",
                json={**payload, "memberId": "fake"},
                headers={"Authorization": "Bearer test-token"},
            ).status_code
            == 400
        )


def test_repository_duplicate_payload_is_idempotent_and_conflicts_roll_back():
    from app.repositories.recommendation_feedback_repository import RecommendationFeedbackRepository

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
