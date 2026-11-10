"""Offline regression for the read-only MFDS matching script; never opens a DB."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts/data/ingredients/match_oy_mfds.py"
spec = importlib.util.spec_from_file_location("ingredient_match_script", SCRIPT_PATH)
assert spec and spec.loader
matcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(matcher)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,2-헥산디올", {"1,2-헥산디올"}),
        ("카카오씨드버터,코코아버터", {"카카오씨드버터", "코코아버터"}),
        (
            "1,2-헥산디올^카카오씨드버터,코코아버터",
            {"1,2-헥산디올", "카카오씨드버터", "코코아버터"},
        ),
        ("N,N-디메틸아민,폴리머", {"N,N-디메틸아민", "폴리머"}),
    ],
)
def test_script_uses_safe_mixed_delimiters(raw, expected):
    assert matcher.official_synonyms(raw) == expected


def test_script_never_emits_chemical_name_fragment():
    mfds = [
        dict(
            ingredient_id=4840,
            name_ko="1,2-헥산다이올",
            name_key="1,2-헥산다이올",
            synonym_raw="1,2-헥산디올",
            source_hash="a" * 64,
        )
    ]
    oy = [
        dict(ingredient_id=2974, ingredient_name="2-헥산디올"),
        dict(ingredient_id=2975, ingredient_name="1,2-헥산디올"),
    ]
    matches, review = matcher.build_candidates(oy, mfds)
    assert [(row[0], row[2]) for row in matches] == [(2975, 4840)]
    assert [(row[0], row[2]) for row in review] == [(2974, "no_match")]


def test_review_queue_retains_raw_hash_and_detects_collisions():
    mfds = [
        dict(
            ingredient_id=100,
            name_ko="울금뿌리오일",
            name_key="울금뿌리오일",
            synonym_raw="강황뿌리오일,울금오일",
            source_hash="a" * 64,
        ),
        dict(
            ingredient_id=101,
            name_ko="온울금뿌리오일",
            name_key="온울금뿌리오일",
            synonym_raw="강황뿌리오일,온울금오일",
            source_hash="b" * 64,
        ),
        dict(
            ingredient_id=102,
            name_ko="1,2-헥산다이올",
            name_key="1,2-헥산다이올",
            synonym_raw="1,2-헥산디올",
            source_hash="c" * 64,
        ),
    ]
    rows = matcher.build_alias_review_rows(mfds)
    assert rows == matcher.build_alias_review_rows(list(reversed(mfds)))
    colliding = [row for row in rows if row[4] == "강황뿌리오일"]
    assert len(colliding) == 2
    assert {row[6] for row in colliding} == {"ambiguous"}
    assert {row[5] for row in colliding} == {"100", "101"}
    assert any(row[2] == "c" * 64 and row[4] == "1,2-헥산디올" for row in rows)
    assert not any(row[4] == "2-헥산디올" for row in rows)
    assert all(row[6] != "verified" for row in rows)


def test_review_queue_lists_single_official_alias_without_requiring_approval():
    mfds = [
        dict(
            ingredient_id=200,
            name_ko="판테놀",
            name_key="판테놀",
            synonym_raw="덱스판테놀",
            source_hash="a" * 64,
        )
    ]
    rows = matcher.build_alias_review_rows(mfds)
    assert len(rows) == 1
    assert rows[0][4] == "덱스판테놀" and rows[0][6] == "source_backed"
    candidates = [(1, "덱스판테놀", 200, "판테놀", "official_synonym")]
    assert matcher.select_approved_matches(candidates, mfds, set()) == (candidates, [])


def test_unapproved_synonym_cannot_be_promoted_to_database():
    mfds = [
        dict(
            ingredient_id=200,
            name_ko="카카오씨버터",
            name_key="카카오씨버터",
            synonym_raw="카카오씨드버터,코코아버터",
            source_hash="a" * 64,
        )
    ]
    candidates = [(1, "코코아버터", 200, "카카오씨버터", "official_synonym")]
    approved, withheld = matcher.select_approved_matches(candidates, mfds, set())
    assert approved == [] and withheld == candidates


def test_approval_is_bound_to_current_source_hash_and_exact_identity(tmp_path):
    import csv

    mfds = [
        dict(
            ingredient_id=200,
            name_ko="카카오씨버터",
            name_key="카카오씨버터",
            synonym_raw="카카오씨드버터,코코아버터",
            source_hash="a" * 64,
        )
    ]
    path = tmp_path / "approved.csv"
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(matcher.APPROVAL_COLUMNS)
        writer.writerow((200, "코코아버터", "a" * 64, "reviewer", "2026-11-10"))
    approved = matcher.load_approved_synonyms(path, mfds)
    candidates = [(1, "코코아버터", 200, "카카오씨버터", "official_synonym")]
    assert matcher.select_approved_matches(candidates, mfds, approved) == (candidates, [])
    mfds[0]["source_hash"] = "b" * 64
    with pytest.raises(ValueError, match="Unverified"):
        matcher.load_approved_synonyms(path, mfds)


def test_conflicting_alias_cannot_be_approved(tmp_path):
    import csv

    mfds = [
        dict(
            ingredient_id=200,
            name_ko="카카오씨버터",
            name_key="카카오씨버터",
            synonym_raw="공통별칭",
            source_hash="a" * 64,
        ),
        dict(
            ingredient_id=201,
            name_ko="다른성분",
            name_key="다른성분",
            synonym_raw="공통별칭",
            source_hash="b" * 64,
        ),
    ]
    path = tmp_path / "approved.csv"
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(matcher.APPROVAL_COLUMNS)
        writer.writerow((200, "공통별칭", "a" * 64, "reviewer", "2026-11-10"))
    with pytest.raises(ValueError, match="Unverified"):
        matcher.load_approved_synonyms(path, mfds)


def test_unicode_normalization_before_delimiter_split():
    assert matcher.official_synonyms("１,２-헥산디올") == {"1,2-헥산디올"}
    assert matcher.official_synonyms("Ｎ,Ｎ-성분,나머지") == {"N,N-성분", "나머지"}


def test_runtime_approval_file_is_versioned_and_immutable_to_source_changes(tmp_path):
    import csv

    from app.core.ingredient_alias_approval import (
        approved_synonym,
        load_approved_aliases,
    )

    source = tmp_path / "approved.csv"
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(matcher.APPROVAL_COLUMNS)
        writer.writerow((200, "코코아버터", "a" * 64, "human-review", "2026-11-10"))
    approved = load_approved_aliases(str(source))
    assert approved_synonym(
        "카카오씨드버터,코코아버터", "코코아버터", 200, "a" * 64, approved
    )
    assert not approved_synonym(
        "카카오씨드버터,코코아버터", "코코아버터", 200, "b" * 64, approved
    )
    assert not approved_synonym(
        "카카오씨드버터,코코아버터", "다른별칭", 200, "a" * 64, approved
    )
    assert not approved_synonym(
        "카카오씨드버터,코코아버터", "코코아버터", 201, "a" * 64, approved
    )


def test_missing_approval_file_does_not_trust_split_aliases():
    from app.core.ingredient_alias_approval import approved_synonym, load_approved_aliases

    approved = load_approved_aliases(None)
    assert not approved_synonym(
        "카카오씨드버터,코코아버터", "코코아버터", 200, "a" * 64, approved
    )
    assert approved_synonym(
        "1,2-헥산디올", "1,2-헥산디올", 200, "a" * 64, approved
    )
