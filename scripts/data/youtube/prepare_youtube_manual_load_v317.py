"""Prepare an idempotent catalog load for the nine reviewed rows and ETUDE split.

Glowpick product pages are read-only inputs. The script writes review artifacts
only; database changes are performed later by load_youtube_v32_incremental.py.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API_ROOT = ROOT.parents[2] / "backend" / "api"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(API_ROOT))

from app.schemas.catalog import CatalogBundle
from app.services.catalog_service import validate_catalog
from enrich_glowpick import DetailParser, GlowpickClient, _parse_detail


MANUAL = {
    "yt-0c7c92b95aa0f6231cb4": {"price": 22000, "volume": "6g"},
    "yt-1128cbb6ad6543e3d4f8": {"price": 11310, "volume": "2ea"},
    "yt-2dd5da88c2d0e5c26032": {"price": 39000, "volume": "125ml"},
    "yt-31a050db79f6b8f32eb2": {"price": 34000, "volume": "8.6g"},
    "yt-346e3a43cd8003a43909": {
        "price": 35000,
        "volume": "4g",
        "image": "https://dn5hzapyfrpio.cloudfront.net/home/glowmee/upload/product/20200830/1598751118480.jpg",
    },
    "yt-3c912a73038563d22b9b": {"price": 24000, "volume": "20.5g"},
    "yt-aa4dd1d5123c9a04ecdb": {"price": 20000, "volume": "40g"},
    "yt-d8e243c1fc6a55438b67": {"price": 30000, "volume": "10ml"},
    # The selected product is the 80-sheet pad. User supplied the 26,000 KRW
    # price; the product size is corroborated by product listings and reporting.
    "yt-e60230a930d440537fc6": {"price": 26000, "volume": "80매"},
    # The user supplied these exact Glowpick product pages for two prior errors.
    "yt-caae314b21945b64878e": {
        "price": 27000, "volume": "1ea", "page_id": 179937,
        "brand": "피카소", "name": "799 엣지 아이라이너", "page_name_check": "799 엣지 아이라이너", "is_tool": True,
    },
    "yt-fe9530e3409511b10f02": {
        "price": 36000, "volume": "3.5g", "page_id": 6340,
        "brand": "크리니크", "name": "치크 팝 - 누드 팝", "page_name_check": "치크 팝",
    },
}
NOT_FOUND_ID = "yt-f4a0bb331656cfdde416"
BRUSH_SOURCE_ID = "yt-fbd4a53196118adaa7c0"
BRUSH_MANIFEST = ROOT / "youtube-etude-contour-brush-split.csv"


def read_brush_manifest() -> list[dict[str, str]]:
    with BRUSH_MANIFEST.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {
            "source_yt_product_id", "serving_product_id", "brand", "name",
            "category", "price_krw", "volume", "product_url",
        }
        if set(reader.fieldnames or ()) != required:
            raise ValueError(f"Unexpected ETUDE split manifest columns: {BRUSH_MANIFEST}")
        rows = list(reader)
    if len(rows) != 3 or any(row["source_yt_product_id"] != BRUSH_SOURCE_ID for row in rows):
        raise ValueError("ETUDE split manifest must contain exactly three rows for the approved source ID")
    ids = {row["serving_product_id"] for row in rows}
    suffixes = {"-01", "-02", "-03"}
    if any(not any(value.endswith(suffix) for suffix in suffixes) for value in ids) or len(ids) != 3:
        raise ValueError("ETUDE split serving IDs must end in -01, -02, and -03")
    for row in rows:
        if row["brand"] != "에뛰드" or row["category"] != "tool" or row["volume"] != "1ea":
            raise ValueError("ETUDE split manifest has unexpected brand, category, or unit")
        if not row["product_url"].startswith("https://www.glowpick.com/products/"):
            raise ValueError("ETUDE split URLs must be Glowpick product pages")
        if int(row["price_krw"]) <= 0:
            raise ValueError("ETUDE split prices must be positive")
    return rows


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not {"yt_product_id", "lookup_status", "selected_product_url", "tags"}.issubset(fields):
        raise ValueError("Source enrichment report has unexpected columns")
    if len({row["yt_product_id"] for row in rows}) != len(rows):
        raise ValueError("Source enrichment report contains duplicate YouTube IDs")
    return fields, rows


def page_details(client: GlowpickClient, product_id: int) -> dict[str, str | int]:
    url = f"https://www.glowpick.com/products/{product_id}"
    response = None
    for attempt, pause in enumerate((0, 5, 15, 30)):
        if pause:
            print(f"Glowpick detail {product_id}: {pause}초 후 재시도 ({attempt}/3)", flush=True)
            time.sleep(pause)
        response = client._request("GET", url)
        if response.status_code < 500:
            response.raise_for_status()
            break
        if attempt == 3:
            response.raise_for_status()
    assert response is not None
    parsed = _parse_detail(response.text, product_id)
    parser = DetailParser()
    parser.feed(response.text)
    image = parser.meta.get("og:image", "").strip()
    title = parsed.get("name", "").strip()
    if not title or not image.startswith("https://") or not parsed.get("price"):
        raise ValueError(f"Glowpick page lacks name, price, or image: {url}")
    volume_match = re.search(r"class=\"[^\"]*volume[^\"]*\"[^>]*>\s*([^<]+)", response.text, re.I)
    volume = re.sub(r"\s+", " ", volume_match.group(1)).strip() if volume_match else "1ea"
    return {
        "brand": parsed.get("brand") or "에뛰드",
        "name": title,
        "price": int(parsed["price"]),
        "volume": volume,
        "image": image,
        "url": url,
    }


def enrich_row(row: dict[str, str], update: dict) -> dict[str, str]:
    result = dict(row)
    result.update({key: str(value) for key, value in update.items() if key in result})
    result["lookup_status"] = "complete"
    result["review_reason"] = "사용자 확인 정보 및 지정 상품 페이지로 보강 완료"
    result["error"] = ""
    return result


def catalog_product(row: dict[str, str]) -> dict:
    tags = json.loads(row["tags"])
    category = tags[1]
    name = row["selected_product_name"].strip()
    return {
        "id": row["yt_product_id"],
        "brand": row["selected_brand"].strip(),
        "name": name,
        "nameKo": name,
        "category": category,
        "makeupZone": None,
        "texture": None,
        "priceKRW": int(row["price_krw"]),
        "volume": "" if row.get("is_tool") == "yes" else row.get("volume", "").strip(),
        "shades": [],
        "description": "",
        "keyIngredients": [],
        "tags": tags,
        "imageUrl": row["image_url"].strip(),
        "searchKeyword": f"{row['selected_brand'].strip()} {name}",
    }


def make_outputs(args: argparse.Namespace) -> None:
    fields, original = read_rows(args.enrichment)
    by_id = {row["yt_product_id"]: row for row in original}
    brushes = read_brush_manifest()
    missing = sorted((set(MANUAL) | {NOT_FOUND_ID, BRUSH_SOURCE_ID}) - by_id.keys())
    if missing:
        raise ValueError(f"Expected reviewed source rows are missing: {missing}")

    output_rows: dict[str, dict[str, str]] = {}
    client = GlowpickClient(1.0)
    fetched_pages: dict[int, dict[str, str | int]] = {}
    try:
        for facts in MANUAL.values():
            if facts.get("page_id"):
                page_id = int(facts["page_id"])
                if page_id not in fetched_pages:
                    fetched_pages[page_id] = page_details(client, page_id)
                detail = fetched_pages[page_id]
                if int(detail["price"]) != int(facts["price"]):
                    raise ValueError(f"Unexpected price on reviewed Glowpick page {page_id}: {detail['price']}")
                expected_name = str(facts["page_name_check"])
                if expected_name not in str(detail["name"]):
                    raise ValueError(f"Unexpected product on reviewed Glowpick page {page_id}: {detail['name']}")
    finally:
        client.close()

    for product_id, facts in MANUAL.items():
        row = dict(by_id[product_id])
        row["price_krw"] = str(facts["price"])
        row["price_source"] = row.get("price_source") or "사용자 승인"
        row["volume"] = facts["volume"]
        row["volume_source"] = row.get("volume_source") or "사용자 승인"
        if facts.get("page_id"):
            detail = fetched_pages[int(facts["page_id"])]
            row["selected_site"] = "glowpick"
            row["selected_brand"] = str(facts.get("brand") or detail["brand"])
            row["selected_product_name"] = str(facts.get("name") or detail["name"])
            row["selected_product_url"] = str(detail["url"])
            row["price_source"] = str(detail["url"])
            row["volume_source"] = str(detail["url"])
            row["image_url"] = str(detail["image"])
            row["image_source"] = str(detail["url"])
            row["match_basis"] = "user_reviewed_product_page"
        if facts.get("is_tool"):
            row["is_tool"] = "yes"
            row["tags"] = '["youtube", "tool"]'
        if facts.get("image"):
            row["image_url"] = facts["image"]
            row["image_source"] = row.get("image_source") or row.get("selected_product_url", "")
        row["lookup_status"] = "complete"
        row["review_reason"] = "사용자 확인 정보로 필수 필드 보강 완료"
        row["error"] = ""
        if not row.get("selected_product_url") or not row.get("selected_brand") or not row.get("selected_product_name"):
            raise ValueError(f"Reviewed product identity is incomplete: {product_id}")
        if not row.get("image_url"):
            raise ValueError(f"Reviewed product still has no image: {product_id}")
        output_rows[product_id] = row

    not_found = dict(by_id[NOT_FOUND_ID])
    not_found["lookup_status"] = "not_found"
    not_found["selected_site"] = ""
    not_found["selected_brand"] = ""
    not_found["selected_product_name"] = ""
    not_found["selected_product_url"] = ""
    not_found["price_krw"] = ""
    not_found["price_source"] = ""
    not_found["volume"] = ""
    not_found["volume_source"] = ""
    not_found["image_url"] = ""
    not_found["image_source"] = ""
    not_found["review_reason"] = "사용자 확인: 지정한 글로우픽·화해 검색에서도 상품을 찾지 못함"
    not_found["error"] = ""
    output_rows[NOT_FOUND_ID] = not_found

    source = by_id[BRUSH_SOURCE_ID]
    client = GlowpickClient(1.0)
    split_rows = []
    try:
        for split in brushes:
            page_id_match = re.search(r"/products/(\d+)$", split["product_url"])
            if not page_id_match:
                raise ValueError(f"Invalid Glowpick URL in split manifest: {split['product_url']}")
            page_id = int(page_id_match.group(1))
            expected_kind = split["name"].split("[", 1)[-1].rstrip("]")
            expected_price = int(split["price_krw"])
            detail = page_details(client, page_id)
            if expected_kind not in str(detail["name"]):
                raise ValueError(f"Unexpected Glowpick identity for {page_id}: {detail['name']}")
            if int(detail["price"]) != expected_price:
                raise ValueError(f"Unexpected Glowpick price for {page_id}: {detail['price']}")
            split_id = split["serving_product_id"]
            row = {field: "" for field in fields}
            row.update(source)
            row.update({
                "yt_product_id": split_id,
                "source_brand": "에뛰드",
                "source_product_name": split["name"],
                "source_option_name": "",
                "is_tool": "yes",
                "tags": '["youtube", "tool"]',
                "lookup_status": "complete",
                "selected_site": "glowpick",
                "selected_brand": "에뛰드",
                "selected_product_name": str(detail["name"]),
                "selected_product_url": str(detail["url"]),
                "match_basis": "user_reviewed_split",
                "price_krw": str(detail["price"]),
                "price_source": str(detail["url"]),
                "volume": str(detail["volume"]),
                "volume_source": str(detail["url"]),
                "image_url": str(detail["image"]),
                "image_source": str(detail["url"]),
                "review_reason": "사용자 승인 분리 상품; 지정 글로우픽 페이지에서 확인",
                "error": "",
            })
            output_rows[split_id] = row
            split_rows.append({
                "source_yt_product_id": BRUSH_SOURCE_ID,
                "serving_product_id": split_id,
                "brand": split["brand"],
                "name": str(detail["name"]),
                "category": split["category"],
                "price_krw": str(detail["price"]),
                "volume": split["volume"],
                "image_url": str(detail["image"]),
                "product_url": str(detail["url"]),
            })
    finally:
        client.close()

    # A single-source clip can be eligible for nine links; we load the three new
    # split records separately and leave the original raw product untouched.
    args.output_enrichment.parent.mkdir(parents=True, exist_ok=True)
    with args.output_enrichment.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output_rows[key] for key in sorted(output_rows))
    with args.output_split_review.open("w", encoding="utf-8-sig", newline="") as stream:
        cols = list(split_rows[0])
        writer = csv.DictWriter(stream, fieldnames=cols)
        writer.writeheader()
        writer.writerows(split_rows)

    catalog = json.loads(args.base_catalog.read_text(encoding="utf-8"))
    products = {item["id"]: item for item in catalog["products"]}
    for row in output_rows.values():
        if row.get("lookup_status") != "complete":
            continue
        item = catalog_product(row)
        old = products.get(item["id"])
        if old is None:
            catalog["products"].append(item)
            products[item["id"]] = item
        else:
            old.update(item)
    bundle = CatalogBundle.model_validate(catalog)
    validate_catalog(bundle)
    args.output_catalog.parent.mkdir(parents=True, exist_ok=True)
    args.output_catalog.write_text(
        json.dumps(bundle.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    complete_count = sum(row.get("lookup_status") == "complete" for row in output_rows.values())
    print(f"Reviewed manual complete rows: {len(MANUAL)}; ETUDE split rows: {len(brushes)}; not_found decisions: 1; output rows: {len(output_rows)}")
    print(f"Complete rows in loader CSV: {complete_count}; not_found rows are excluded from catalog JSON")
    print(f"Enrichment CSV: {args.output_enrichment}")
    print(f"Catalog JSON: {args.output_catalog}")
    print(f"Split review CSV: {args.output_split_review}")
    print("No database rows were written")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enrichment", type=Path, required=True)
    parser.add_argument("--base-catalog", type=Path, required=True)
    parser.add_argument("--output-enrichment", type=Path, required=True)
    parser.add_argument("--output-catalog", type=Path, required=True)
    parser.add_argument("--output-split-review", type=Path, required=True)
    make_outputs(parser.parse_args())


if __name__ == "__main__":
    main()
