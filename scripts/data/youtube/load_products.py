"""Load the reviewed YouTube research workbook into raw product and mention tables.

Only the `전체 제품` sheet is imported. Existing match decisions and enriched colors are
not touched. Run from backend/api with `uv run python .../load_products.py`.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path

import asyncpg

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
CELL = f"{{{MAIN}}}c"
TEXT = f"{{{MAIN}}}t"
VALUE = f"{{{MAIN}}}v"
ROW = f"{{{MAIN}}}row"
SHEET = f"{{{MAIN}}}sheetData"
NO_OPTION = {"원본에 별도 옵션 없음", "원문에 명시 정보 없음", "", "확인 필요"}
FIELDS = {
    "source": "A",
    "video_id": "B",
    "mention_number": "C",
    "source_row_id": "U",
    "video_url": "V",
    "source_product_record_id": "W",
    "brand_name": "Z",
    "product_name": "AA",
    "category": "AB",
    "makeup_zone": "AC",
    "option_name": "AD",
    "price_krw": "AF",
    "price_type": "AG",
    "volume": "AK",
    "texture": "AL",
    "image_url": "AM",
    "image_source_url": "AN",
    "hex_code": "AP",
    "description": "AQ",
    "product_url": "AS",
    "checked_at": "AU",
    "video_playback_status": "AW",
    "video_use_evidence": "AX",
    "research_status": "AZ",
    "review_reason": "BA",
}
PRODUCT_COLUMNS = (
    "yt_product_id",
    "brand_name",
    "product_name",
    "option_name",
    "category",
    "makeup_zone",
    "price_krw",
    "price_type",
    "volume",
    "texture",
    "hex_code",
    "image_url",
    "image_source_url",
    "product_url",
    "description",
    "checked_at",
)
MENTION_COLUMNS = (
    "source_row_id",
    "yt_product_id",
    "source_product_record_id",
    "source",
    "video_id",
    "mention_number",
    "video_url",
    "video_playback_status",
    "video_use_evidence",
    "research_status",
    "review_reason",
)


class _PreflightRollback(Exception):
    """Roll back staged rows after all database constraints have been checked."""


def _key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _cells(row: ET.Element) -> dict[str, str]:
    result = {}
    for cell in row.findall(CELL):
        column = re.match(r"[A-Z]+", cell.attrib["r"]).group()
        inline = "".join(node.text or "" for node in cell.iter(TEXT))
        numeric = cell.find(VALUE)
        result[column] = inline or (numeric.text if numeric is not None else "") or ""
    return result


def read_workbook(path: Path) -> tuple[list[tuple], list[tuple], Counter]:
    if not path.is_file():
        raise ValueError(f"Workbook is missing: {path}")
    with zipfile.ZipFile(path) as book:
        # The supplied workbook places `전체 제품` in sheet1; check headers before use.
        root = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))
        sheet = root.find(SHEET)
        if sheet is None:
            raise ValueError("Workbook has no product rows")
        rows = sheet.findall(ROW)
        headers = _cells(rows[1])
        expected = {
            "U": "원본 행 식별자",
            "W": "신규 상품 레코드 ID",
            "Z": "조사 브랜드",
            "AA": "조사 제품명",
            "AD": "조사 호수·옵션",
        }
        if any(headers.get(column) != label for column, label in expected.items()):
            raise ValueError(
                "The first sheet does not match the expected research workbook"
            )
        grouped: dict[str, dict] = {}
        mentions: list[tuple] = []
        seen_rows: set[str] = set()
        seen_source_ids: set[str] = set()
        conflicts: Counter = Counter()
        for row in rows[2:]:
            cells = _cells(row)
            data = {
                field: cells.get(column, "").strip() for field, column in FIELDS.items()
            }
            if not data["source_row_id"]:
                continue
            if data["source_row_id"] in seen_rows:
                raise ValueError(f"Duplicate source row: {data['source_row_id']}")
            if data["source_product_record_id"] in seen_source_ids:
                raise ValueError(
                    f"Duplicate source product record: {data['source_product_record_id']}"
                )
            seen_rows.add(data["source_row_id"])
            seen_source_ids.add(data["source_product_record_id"])
            if not data["brand_name"] or not data["product_name"]:
                raise ValueError(
                    f"Missing researched brand or product name: {data['source_row_id']}"
                )
            data["option_name"] = (
                data["option_name"] if data["option_name"] not in NO_OPTION else ""
            )
            identity = "\x1f".join(
                _key(data[field])
                for field in ("brand_name", "product_name", "option_name")
            )
            product_id = "yt-" + hashlib.sha256(identity.encode()).hexdigest()[:20]
            data["yt_product_id"] = product_id
            data["price_krw"] = int(data["price_krw"]) if data["price_krw"] else None
            data["checked_at"] = (
                date.fromisoformat(data["checked_at"]) if data["checked_at"] else None
            )
            if data["hex_code"] and not re.fullmatch(
                r"#[0-9A-Fa-f]{6}", data["hex_code"]
            ):
                raise ValueError(f"Invalid HEX: {data['source_row_id']}")
            data["hex_code"] = data["hex_code"].upper() if data["hex_code"] else None
            data["option_name"] = data["option_name"] or None
            for field in (
                "category",
                "makeup_zone",
                "price_type",
                "volume",
                "texture",
                "image_url",
                "image_source_url",
                "product_url",
                "description",
            ):
                data[field] = data[field] or None
            prior = grouped.get(product_id)
            if prior is None:
                grouped[product_id] = data
            else:
                for field in PRODUCT_COLUMNS[1:]:
                    if prior[field] is None and data[field] is not None:
                        prior[field] = data[field]
                    elif data[field] is not None and prior[field] != data[field]:
                        conflicts[field] += 1
            try:
                data["mention_number"] = int(data["mention_number"])
            except ValueError as exc:
                raise ValueError(
                    f"Invalid mention number: {data['source_row_id']}"
                ) from exc
            if not data["source"] or not data["video_id"] or not data["video_url"]:
                raise ValueError(f"Incomplete video reference: {data['source_row_id']}")
            mentions.append(tuple(data.get(field) or None for field in MENTION_COLUMNS))
    if not grouped or not mentions:
        raise ValueError("Workbook has no valid product mentions")
    if any(
        conflicts[field]
        for field in ("price_krw", "volume", "texture", "hex_code", "image_url")
    ):
        raise ValueError(f"Conflicting product values need review: {dict(conflicts)}")
    products = [
        tuple(item.get(field) for field in PRODUCT_COLUMNS) for item in grouped.values()
    ]
    return products, mentions, conflicts


async def load(args: argparse.Namespace) -> None:
    products, mentions, conflicts = read_workbook(args.input)
    print(
        f"Validated {len(mentions):,} mentions and {len(products):,} product-option records"
    )
    if conflicts:
        print(
            f"Non-critical duplicate details kept from the first row: {dict(conflicts)}"
        )
    if args.host not in ("127.0.0.1", "localhost"):
        raise ValueError("Only a local PostgreSQL host is supported")
    password = getpass.getpass("Local PostgreSQL password: ")
    conn = await asyncpg.connect(
        host=args.host,
        port=args.port,
        database=args.database,
        user=args.user,
        password=password,
        ssl=False,
    )
    try:
        removed_placeholder_rows = 0
        async with conn.transaction():
            if not await conn.fetchval(
                "SELECT to_regclass('public.raw_yt_product') IS NOT NULL"
            ):
                raise ValueError("Apply Alembic revision 0015 before importing")
            print(f"Connected to {args.host}:{args.port}/{args.database}")
            pcols = ", ".join(PRODUCT_COLUMNS)
            pholders = ", ".join(f"${i}" for i in range(1, len(PRODUCT_COLUMNS) + 1))
            updates = ", ".join(
                f"{col}=COALESCE(EXCLUDED.{col}, raw_yt_product.{col})"
                for col in PRODUCT_COLUMNS[1:]
            )
            await conn.executemany(
                f"INSERT INTO raw_yt_product ({pcols}) VALUES ({pholders}) ON CONFLICT (yt_product_id) DO UPDATE SET {updates}, updated_at=now()",
                products,
            )
            mcols = ", ".join(MENTION_COLUMNS)
            mholders = ", ".join(f"${i}" for i in range(1, len(MENTION_COLUMNS) + 1))
            mupdates = ", ".join(f"{col}=EXCLUDED.{col}" for col in MENTION_COLUMNS[1:])
            await conn.executemany(
                f"INSERT INTO raw_yt_product_mention ({mcols}) VALUES ({mholders}) ON CONFLICT (source_row_id) DO UPDATE SET {mupdates}",
                mentions,
            )
            mapped_placeholder_rows = await conn.fetchval(
                """SELECT COUNT(*) FROM public.raw_yt_product p
                   WHERE p.option_name = '원문에 명시 정보 없음'
                     AND EXISTS (SELECT 1 FROM public.yt_oy_product_match m
                                 WHERE m.yt_product_id = p.yt_product_id)"""
            )
            if mapped_placeholder_rows:
                raise ValueError(
                    f"Old placeholder products have {mapped_placeholder_rows} match rows; review before cleanup"
                )
            status = await conn.execute(
                """DELETE FROM public.raw_yt_product p
                   WHERE p.option_name = '원문에 명시 정보 없음'
                     AND NOT EXISTS (SELECT 1 FROM public.raw_yt_product_mention m
                                     WHERE m.yt_product_id = p.yt_product_id)"""
            )
            removed_placeholder_rows = int(status.rsplit(" ", 1)[-1])
            if not args.apply:
                raise _PreflightRollback
        print(
            f"Committed {len(products):,} products and {len(mentions):,} mentions; "
            f"removed {removed_placeholder_rows:,} obsolete placeholder products; match decisions unchanged"
        )
    except _PreflightRollback:
        print(
            "Preflight passed; product and mention writes rolled back; "
            f"would remove {removed_placeholder_rows:,} obsolete placeholder products"
        )
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15432)
    parser.add_argument("--database", default="vishue_db")
    parser.add_argument("--user", default="vishue")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.validate_only:
        products, mentions, conflicts = read_workbook(args.input)
        print(
            f"Validated {len(mentions):,} mentions and {len(products):,} product-option records"
        )
        if conflicts:
            print(f"Duplicate detail differences: {dict(conflicts)}")
        print("Validation complete; no database connection or write")
        return
    asyncio.run(load(args))


if __name__ == "__main__":
    main()
