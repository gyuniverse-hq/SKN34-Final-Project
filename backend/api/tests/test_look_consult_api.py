from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import create_app
from app.repositories.look_consult_repository import SCORE_COLUMNS
from app.services.look_consult_service import LookConsultService, get_look_consult_service

ADVICE_ROW = {
    "dataset_version": "makeup-troubleshooting-review-20261124-v2",
    "situation_id": "PREP-01-S01",
    "problem_id": "PREP-01",
    "category": "피부 준비",
    "question": "스킨케어 위에 베이스를 올리니 때처럼 밀려요.",
    "clarifying_conditions": "베이스를 바르기 전에도 밀렸는지",
    "selection_condition": "스킨케어 직후에 밀릴 때",
    "solution_draft": "스킨케어가 흡수된 뒤 얇게 바른다.",
    "solution_evidence_scope": "직접",
    "solution_evidence": [
        {
            "source_id": "SRC-1",
            "title": "제조사 사용법",
            "links": [{"title": "사용법", "url": "https://example.com/guide"}],
            "source_note": None,
            "evidence_summary": "흡수 후 사용 권장",
            "applies_to": "스킨케어 직후 베이스",
            "limitation": "피부 상태에 따라 다름",
        }
    ],
}

TAG_ROW = {
    "video_id": "VIDEO-001",
    "youtube_id": "fDqBPI1SaWY",
    "look_id": "LOOK-001",
    "review_status": "user_reviewed",
    "rubric_version": "look-comparison-v3",
    **{name: None for name in SCORE_COLUMNS},
    "overall_sparkle": Decimal("1.50"),
    "attributes": {"lip_tone": ["mixed", "warm"], "main_color": "red"},
    "free_tags": [{"type": "technique", "zone": "lips", "label": "오버립"}],
}


class FakeStore:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def troubleshooting(self, category, problem_id):
        self.calls.append(("troubleshooting", category, problem_id))
        return [ADVICE_ROW]

    async def look_tags(self, ids):
        self.calls.append(("look_tags", tuple(ids)))
        return [TAG_ROW]


def client_with(store: FakeStore) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_look_consult_service] = lambda: LookConsultService(store)
    return TestClient(app)


def test_troubleshooting_endpoint_returns_approved_advice_with_evidence():
    store = FakeStore()
    with client_with(store) as client:
        response = client.get(
            "/api/look-consult/makeup-troubleshooting",
            params={"category": "피부 준비", "problemId": "PREP-01"},
        )
    assert response.status_code == 200
    advice = response.json()["advice"][0]
    assert advice["situationId"] == "PREP-01-S01"
    assert advice["solution"] == "스킨케어가 흡수된 뒤 얇게 바른다."
    assert advice["evidenceScope"] == "직접"
    evidence = advice["evidence"][0]
    assert evidence["appliesTo"] == "스킨케어 직후 베이스"
    assert evidence["links"] == [{"title": "사용법", "url": "https://example.com/guide"}]
    assert "sourceNote" not in evidence
    assert store.calls == [("troubleshooting", "피부 준비", "PREP-01")]


def test_look_tags_keep_every_attribute_as_a_list_and_scores_as_numbers():
    store = FakeStore()
    with client_with(store) as client:
        response = client.get("/api/look-consult/look-tags", params=[("id", "VIDEO-001")])
    assert response.status_code == 200
    tag = response.json()["tags"][0]
    assert tag["youtubeId"] == "fDqBPI1SaWY"
    assert tag["reviewStatus"] == "user_reviewed"
    assert tag["attributes"] == {"lip_tone": ["mixed", "warm"], "main_color": ["red"]}
    assert tag["scores"]["overall_sparkle"] == 1.5
    assert tag["scores"]["glamour"] is None
    assert tag["freeTags"][0]["label"] == "오버립"
    assert store.calls == [("look_tags", ("VIDEO-001",))]


def test_look_tags_without_ids_requests_all_videos():
    store = FakeStore()
    with client_with(store) as client:
        assert client.get("/api/look-consult/look-tags").status_code == 200
    assert store.calls == [("look_tags", ())]


def test_look_tags_reject_too_many_or_oversized_ids():
    store = FakeStore()
    with client_with(store) as client:
        too_many = client.get(
            "/api/look-consult/look-tags", params=[("id", f"VIDEO-{n}") for n in range(201)]
        )
        too_long = client.get("/api/look-consult/look-tags", params=[("id", "x" * 65)])
    assert too_many.status_code == 422
    assert too_long.status_code == 422
    assert store.calls == []
