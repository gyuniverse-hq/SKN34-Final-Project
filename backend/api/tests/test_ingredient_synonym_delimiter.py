"""Regression: MFDS aliases use ^, and commas can belong to chemical names."""

import pytest

from app.repositories.ingredient_identity_repository import (
    OFFICIAL_SYNONYM_SEPARATOR,
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
    assert OFFICIAL_SYNONYM_SEPARATOR == r"\s*\^\s*"
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
