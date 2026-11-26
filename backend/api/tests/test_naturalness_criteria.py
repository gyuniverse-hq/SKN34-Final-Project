from app.clients.vision_llm_client import NATURALNESS_VERSION, SCORE_KEYS
from app.services.naturalness_criteria_service import (
    get_naturalness_criteria,
    load_naturalness_criteria,
)


def test_naturalness_criteria_matches_scoring_contract():
    load_naturalness_criteria.cache_clear()
    payload = get_naturalness_criteria()
    assert payload["version"] == NATURALNESS_VERSION
    assert tuple(item["id"] for item in payload["items"]) == SCORE_KEYS
    for item in payload["items"]:
        assert set(item["likert"]) == {"1", "2", "3", "4", "5"}
