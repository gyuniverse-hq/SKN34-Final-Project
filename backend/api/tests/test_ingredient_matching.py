"""Guard conservative ingredient matching and concentration-suffix fallback."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/data/ingredients/match_oy_mfds.py"
SPEC = importlib.util.spec_from_file_location("match_oy_mfds", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
matching = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(matching)


def mfds_row(ingredient_id: int, name: str, synonym: str = "") -> dict:
    return {
        "ingredient_id": ingredient_id,
        "name_ko": name,
        "name_key": matching.name_key(name),
        "synonym_raw": synonym,
    }


def oy_row(ingredient_id: int, name: str) -> dict:
    return {"ingredient_id": ingredient_id, "ingredient_name": name}


def test_exact_and_unique_synonym_keep_their_existing_methods() -> None:
    matches, review = matching.build_candidates(
        [oy_row(1, "세라마이드엔피"), oy_row(2, "공식 동의어")],
        [mfds_row(10, "세라마이드엔피"), mfds_row(20, "공식명", "공식 동의어")],
    )

    assert [(row[0], row[2], row[4]) for row in matches] == [
        (1, 10, "exact_name"),
        (2, 20, "official_synonym"),
    ]
    assert review == []


def test_only_final_numeric_concentration_is_removed_for_fallback() -> None:
    matches, review = matching.build_candidates(
        [
            oy_row(1, "세라마이드엔피(1.215ppm)"),
            oy_row(2, "공식 동의어(0.1%)"),
            oy_row(3, "세라마이드엔피(1,000 ppm)"),
            oy_row(4, "세라마이드엔피（0.5％）"),
            oy_row(5, "세라마이드엔피(1ppm) 추가"),
            oy_row(6, "세라마이드엔피(1ppm)(2ppm)"),
        ],
        [mfds_row(10, "세라마이드엔피"), mfds_row(20, "공식명", "공식 동의어")],
    )

    assert [(row[0], row[2], row[4]) for row in matches] == [
        (1, 10, "amount_suffix_exact"),
        (2, 20, "amount_suffix_synonym"),
        (3, 10, "amount_suffix_exact"),
        (4, 10, "amount_suffix_exact"),
    ]
    assert [(row[0], row[2]) for row in review] == [(5, "no_match"), (6, "no_match")]


def test_ambiguous_synonym_stays_in_review_after_suffix_removal() -> None:
    mfds = [
        mfds_row(10, "천궁뿌리추출물", "천궁추출물"),
        mfds_row(20, "천궁뿌리줄기추출물", "천궁추출물"),
    ]
    matches, review = matching.build_candidates(
        [oy_row(1, "천궁추출물"), oy_row(2, "천궁추출물(10ppm)")], mfds
    )

    assert matches == []
    assert [(row[0], row[2], row[3]) for row in review] == [
        (1, "ambiguous_synonym", "10;20"),
        (2, "ambiguous_amount_synonym", "10;20"),
    ]
