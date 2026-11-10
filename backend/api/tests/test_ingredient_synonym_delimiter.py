"""Regression: MFDS aliases mix delimiters; chemical commas remain part of names."""

import pytest

from app.repositories.ingredient_identity_repository import (
    _current_link,
    _official_synonyms,
)


def mapped_row(raw_name: str, method: str = "official_synonym"):
    return (
        82,
        "표준화된 성분",
        "a" * 64,
        100,
        method,
        "test-rule",
        None,
        None,
        raw_name,
        "INCI name",
        "1,2-헥산다이올^둘째동의어",
    )


def test_caret_synonyms_preserve_embedded_commas():
    assert _official_synonyms("1,2-헥산다이올^둘째동의어") == {
        "1,2-헥산다이올",
        "둘째동의어",
    }
    assert "1" not in _official_synonyms("1,2-헥산다이올")
    assert "2-헥산다이올" not in _official_synonyms("1,2-헥산다이올")


@pytest.mark.parametrize(
    ("raw_name", "expected"),
    [
        ("1,2-헥산다이올", True),
        ("둘째동의어", True),
        ("1", False),
        ("2-헥산다이올", False),
    ],
)
def test_comma_fragments_are_not_validated_aliases(raw_name, expected):
    assert _current_link(mapped_row(raw_name)) is expected


def test_amount_suffix_does_not_promote_broken_alias_fragments():
    assert _current_link(mapped_row("1,2-헥산다이올(10ppm)", "amount_suffix_synonym"))
    assert not _current_link(mapped_row("2-헥산다이올(10ppm)", "amount_suffix_synonym"))


@pytest.mark.parametrize(
    ("synonym_raw", "aliases"),
    [
        ("카카오씨드버터,코코아버터", {"카카오씨드버터", "코코아버터"}),
        ("1,2-헥산디올", {"1,2-헥산디올"}),
        (
            "4,4-디메칠-1,3-옥사졸리딘,다이메틸옥사졸리딘",
            {"4,4-디메칠-1,3-옥사졸리딘", "다이메틸옥사졸리딘"},
        ),
        ("N,N-디메틸아민,폴리머", {"N,N-디메틸아민", "폴리머"}),
        ("Water,Aqua", {"Water", "Aqua"}),
        (
            "1,2-헥산디올^카카오씨드버터,코코아버터",
            {"1,2-헥산디올", "카카오씨드버터", "코코아버터"},
        ),
    ],
)
def test_mixed_delimiters_keep_whole_chemical_names(synonym_raw, aliases):
    assert _official_synonyms(synonym_raw) == aliases


def test_real_existing_fragment_mapping_is_not_reissued():
    current = list(mapped_row("2-헥산다이올"))
    current[10] = "1,2-헥산다이올"
    assert not _current_link(tuple(current))
    current[8] = "1,2-헥산다이올"
    assert _current_link(tuple(current))


def test_fullwidth_numeric_locant_is_not_split():
    assert _official_synonyms("１,２-헥산디올") == {"1,2-헥산디올"}


def test_legacy_comma_alias_still_validates():
    current = list(mapped_row("코코아버터"))
    current[10] = "카카오씨드버터,코코아버터"
    assert _current_link(tuple(current))
