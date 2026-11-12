"""Fill missing YouTube product color/texture from human-confirmed Olive Young matches.

An option-level color requires a confirmed option match. A product-level match can
use color only when the research row has no option and the Olive Young product has
exactly one active option. Existing
YouTube research values are never overwritten. Preview is the default.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import getpass
import re
from collections import defaultdict
from pathlib import Path

import asyncpg

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
COLOR_METHODS = {"swatch", "color_chip", "pencil_tip"}
TEXTURES = {"matte", "velvet", "cream", "satin", "sheer", "glossy", "shimmer"}
REPORT_COLUMNS = (
    "yt_product_id",
    "oy_goods_no",
    "oy_option_id",
    "resolved_option_id",
    "current_hex",
    "proposed_hex",
    "color_method",
    "current_texture",
    "proposed_texture",
    "result",
)


async def run(args: argparse.Namespace) -> None:
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
        if not await conn.fetchval(
            "SELECT to_regclass('public.yt_oy_product_match') IS NOT NULL"
        ):
            raise ValueError("Apply Alembic revision 0015 before enrichment")
        matches = await conn.fetch(
            """SELECT m.yt_product_id, m.oy_goods_no, m.oy_option_id,
                      y.option_name AS yt_option_name,
                      y.hex_code AS current_hex, y.texture AS current_texture
               FROM public.yt_oy_product_match m
               JOIN public.raw_yt_product y ON y.yt_product_id = m.yt_product_id
               JOIN public.raw_oy_product p ON p.goods_no = m.oy_goods_no
               WHERE m.decision_status = 'confirmed' AND p.delisted_at IS NULL"""
        )
        options = await conn.fetch(
            "SELECT goods_no, option_id FROM public.raw_oy_product_option WHERE delisted_at IS NULL"
        )
        options_by_goods = defaultdict(list)
        goods_by_option = {}
        for option in options:
            options_by_goods[option["goods_no"]].append(option["option_id"])
            goods_by_option[option["option_id"]] = option["goods_no"]
        color_rows = await conn.fetch(
            """SELECT DISTINCT ON (option_id) option_id, hex_code, color_method
               FROM public.raw_oy_option_color
               ORDER BY option_id, collected_at DESC"""
        )
        colors = {row["option_id"]: row for row in color_rows}
        texture_rows = await conn.fetch(
            """SELECT DISTINCT ON (goods_no) goods_no, texture_code
               FROM public.raw_oy_product_texture
               ORDER BY goods_no, collected_at DESC"""
        )
        textures = {row["goods_no"]: row["texture_code"] for row in texture_rows}
        report: list[tuple] = []
        updates: list[tuple] = []
        for match in matches:
            goods_no = match["oy_goods_no"]
            option_id = match["oy_option_id"]
            if option_id and goods_by_option.get(option_id) != goods_no:
                raise ValueError(
                    f"Confirmed option belongs to another product: {option_id}"
                )
            resolved = option_id
            if (
                not resolved
                and not match["yt_option_name"]
                and len(options_by_goods[goods_no]) == 1
            ):
                resolved = options_by_goods[goods_no][0]
            color = colors.get(resolved)
            proposed_hex = None
            if (
                color
                and color["color_method"] in COLOR_METHODS
                and color["hex_code"]
                and HEX.fullmatch(color["hex_code"])
            ):
                proposed_hex = color["hex_code"].upper()
            proposed_texture = textures.get(goods_no)
            if proposed_texture not in TEXTURES:
                proposed_texture = None
            current_hex = match["current_hex"]
            current_texture = match["current_texture"]
            if (current_hex and proposed_hex and current_hex != proposed_hex) or (
                current_texture
                and proposed_texture
                and current_texture != proposed_texture
            ):
                result = "existing_value_conflict_preserved"
            elif (not current_hex and proposed_hex) or (
                not current_texture and proposed_texture
            ):
                result = "fill_missing"
                updates.append((match["yt_product_id"], proposed_hex, proposed_texture))
            else:
                result = "no_change"
            report.append(
                (
                    match["yt_product_id"],
                    goods_no,
                    option_id,
                    resolved,
                    current_hex,
                    proposed_hex,
                    color["color_method"] if color else None,
                    current_texture,
                    proposed_texture,
                    result,
                )
            )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(REPORT_COLUMNS)
            writer.writerows(report)
        print(
            f"Confirmed matches: {len(matches):,}; eligible to fill: {len(updates):,}"
        )
        print(f"Review file: {args.report}")
        if not args.apply:
            print("Preview complete; no database rows were written")
            return
        async with conn.transaction():
            for product_id, hex_code, texture in updates:
                await conn.execute(
                    """UPDATE public.raw_yt_product
                       SET hex_code = COALESCE(hex_code, $2),
                           texture = COALESCE(texture, $3), updated_at = now()
                       WHERE yt_product_id = $1""",
                    product_id,
                    hex_code,
                    texture,
                )
        print(f"Filled missing values for {len(updates):,} confirmed products")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15432)
    parser.add_argument("--database", default="vishue_db")
    parser.add_argument("--user", default="vishue")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
