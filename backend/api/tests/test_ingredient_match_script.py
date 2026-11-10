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
        ("1,2-헥산디올^카카오씨드버터,코코아버터",
         {"1,2-헥산디올", "카카오씨드버터", "코코아버터"}),
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
