from decimal import Decimal

import pytest

from app.services.look_tag_load_service import Codebook, load_codebook, plan_tag_rows

CODEBOOK = Codebook(
    "look-comparison-v3",
    ("glamour", "spring_mood"),
    {
        "lip_tone": frozenset({"warm", "cool", "mixed"}),
        "sparkle_locations": frozenset({"none", "eyelid", "aegyo_sal"}),
    },
)


def field(status: str, value, *evidence) -> dict:
    return {"status": status, "selected_value": value, "candidates": list(evidence)}


def video(**extra) -> dict:
    return {
        "scores": {
            "glamour": field(
                "averaged",
                1.5,
                {"value": 2, "evidence": [{"source": "gemini", "score": 2, "note": "선명한 눈매"}]},
                {
                    "value": 1,
                    "evidence": [{"source": "claude", "score": 1, "quote": "진하지 않지만"}],
                },
            ),
            "spring_mood": field("unknown", None),
        },
        "attributes": {
            "lip_tone": field(
                "both_accepted", ["warm", "mixed"], {"value": "warm", "evidence": []}
            ),
            "sparkle_locations": field("single_source", "eyelid"),
        },
        "tags": [
            {"type": "technique", "zone": "lips", "label": "오버립"},
            {"type": "technique", "zone": "lips", "label": "오버립"},
        ],
        **extra,
    }


def merged(**videos) -> dict:
    return {"rubric_version": "look-comparison-v3", "videos": videos}


def test_row_keeps_scores_attributes_tags_and_short_evidence() -> None:
    plan = plan_tag_rows(merged(yt1=video()), {"yt1": "VIDEO-004"}, CODEBOOK, {})
    (row,) = plan.rows
    assert row["video_id"] == "VIDEO-004" and row["review_status"] == "ai_merged"
    assert row["glamour"] == Decimal("1.5") and row["spring_mood"] is None
    assert row["attributes"] == {"lip_tone": ["warm", "mixed"], "sparkle_locations": ["eyelid"]}
    assert row["free_tags"] == [{"type": "technique", "zone": "lips", "label": "오버립"}]
    assert row["evidence"]["scores"]["glamour"] == [
        {"source": "gemini", "score": 2, "note": "선명한 눈매"},
        {"source": "claude", "score": 1, "quote": "진하지 않지만"},
    ]
    assert row["evidence"]["status"]["glamour"] == "averaged"
    assert "transcript" not in str(row["evidence"])


def test_conflict_needs_an_override_and_unknown_codes_are_dropped() -> None:
    conflicted = video(
        attributes={
            "lip_tone": field("single_source", "rosy"),
            "sparkle_locations": field("conflict", None),
        }
    )
    plan = plan_tag_rows(merged(yt1=conflicted), {"yt1": "VIDEO-004"}, CODEBOOK, {})
    assert plan.unresolved == ["yt1.sparkle_locations"]
    assert plan.dropped_values == ["yt1.lip_tone=rosy"]
    assert plan.rows[0]["attributes"] == {}

    settled = plan_tag_rows(
        merged(yt1=conflicted),
        {"yt1": "VIDEO-004"},
        CODEBOOK,
        {"yt1": {"sparkle_locations": ["aegyo_sal"]}},
    )
    assert settled.unresolved == []
    assert settled.rows[0]["attributes"] == {"sparkle_locations": ["aegyo_sal"]}


def test_skips_unregistered_empty_and_human_reviewed_videos() -> None:
    empty = video(scores={"glamour": field("unknown", None)}, attributes={}, tags=[])
    plan = plan_tag_rows(
        merged(a=video(), b=empty, c=video(), d=video()),
        {"a": "VIDEO-004", "b": "VIDEO-005", "c": "VIDEO-006"},
        CODEBOOK,
        {},
        reviewed={"VIDEO-006"},
    )
    assert [row["video_id"] for row in plan.rows] == ["VIDEO-004"]
    assert plan.skipped == {"no_tags": 1, "user_reviewed": 1, "not_registered": 1}


def test_rubric_mismatch_is_refused() -> None:
    with pytest.raises(ValueError):
        plan_tag_rows({"rubric_version": "v2", "videos": {}}, {}, CODEBOOK, {})


def test_codebook_file_has_all_scores_and_fields() -> None:
    codebook = load_codebook()
    assert len(codebook.scores) == 9
    assert len(codebook.fields) == 23
    assert "widened_lip" in codebook.fields["lip_techniques"]
