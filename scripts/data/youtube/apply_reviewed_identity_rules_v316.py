"""Apply only the user's exact, reviewed source-to-candidate identity decisions.

This is a post-collection decision pass, not a web crawler. URL+source-ID pairs
are allowlisted; it never promotes a different candidate by fuzzy similarity.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OVERRIDE_FILE = ROOT / "reviewed_identity_overrides_v316.csv"
IDENTITY_REASONS = (
    "제품명 근거 확인 필요",
    "글로우픽 리뷰 태그 후보로 확인 필요",
    "브랜드 표기 유사 후보 확인 필요",
    "브랜드 표기 차이 확인 필요",
)


def read_overrides() -> dict[str, dict[str, str]]:
    with OVERRIDE_FILE.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    result = {row["yt_product_id"]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError("Duplicate source IDs in reviewed identity overrides")
    return result


def missing_fields(row: dict[str, str]) -> list[str]:
    required = [("price_krw", "가격"), ("image_url", "이미지")]
    if row.get("is_tool") != "yes":
        required.append(("volume", "용량"))
    return [label for key, label in required if not (row.get(key) or "").strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.input.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not {"yt_product_id", "selected_product_url", "lookup_status", "review_reason"}.issubset(fields):
        raise ValueError("Input report is missing identity/status columns")
    overrides = read_overrides()
    seen: set[str] = set()
    applied = 0
    for row in rows:
        override = overrides.get(row["yt_product_id"])
        if not override or row.get("selected_product_url", "").strip() != override["selected_product_url"]:
            continue
        seen.add(row["yt_product_id"])
        reasons = [
            part.strip()
            for part in (row.get("review_reason") or "").split(";")
            if part.strip() and not any(reason in part for reason in IDENTITY_REASONS)
        ]
        reasons.insert(0, "사용자 승인 제품 동일성 규칙 적용")
        missing = missing_fields(row)
        if missing:
            row["lookup_status"] = "incomplete_data"
            reasons.append("미수집 정보: " + ", ".join(missing))
        else:
            row["lookup_status"] = "complete"
        row["review_reason"] = "; ".join(dict.fromkeys(reasons))
        if "error" in row:
            row["error"] = ""
        applied += 1
    absent = sorted(set(overrides) - seen)
    if absent:
        raise ValueError(f"Approved ID+URL pairs were not found exactly in input report: {absent}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["lookup_status"]] = counts.get(row["lookup_status"], 0) + 1
    print(f"Applied exact reviewed identities: {applied}; status counts: {counts}")
    print(f"Output report: {args.output}; no database rows were written")


if __name__ == "__main__":
    main()
