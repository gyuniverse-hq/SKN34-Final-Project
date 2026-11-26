"""The reviewed eyeshadow finish CSV matches the codes seeded by migration 0026."""

import ast
import csv
from collections import Counter
from datetime import datetime
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
REVIEW_CSV = (
    API_ROOT.parents[1]
    / "scripts"
    / "data"
    / "oliveyoung"
    / "eyeshadow_finish_review_20261118"
    / "option_finishes.csv"
)


def _finish_codes() -> dict[str, bool]:
    path = API_ROOT / "alembic" / "versions" / "0026_eyeshadow_option_finish.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "FINISH_CODES":
            return {code: is_finish for code, _, is_finish in ast.literal_eval(node.value)}
    raise AssertionError("FINISH_CODES not found in migration 0026")


def _rows() -> list[dict[str, str]]:
    with REVIEW_CSV.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def test_finish_codes_cover_six_finishes_and_four_exclusions():
    codes = _finish_codes()
    assert sorted(c for c, is_finish in codes.items() if is_finish) == [
        "glitter",
        "glossy",
        "matte",
        "metallic",
        "satin",
        "shimmer",
    ]
    assert sorted(c for c, is_finish in codes.items() if not is_finish) == [
        "accessory",
        "other_category",
        "palette",
        "unknown",
    ]


def test_review_csv_uses_only_known_codes_and_steps():
    rows = _rows()
    codes = _finish_codes()
    assert len(rows) == 1079
    assert not [r for r in rows if r["finish_code"] not in codes]
    assert {r["judge_step"] for r in rows} <= {
        "manual_image",
        "manual_detail_page",
        "manual_bulk",
    }
    assert max(Counter(r["option_id"] for r in rows).values()) == 1
    for row in rows:
        assert row["option_id"].startswith(row["goods_no"] + "-")
        datetime.strptime(row["collected_at"], "%Y-%m-%d %H:%M:%S.%f")
