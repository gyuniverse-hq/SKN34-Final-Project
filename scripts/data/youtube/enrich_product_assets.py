"""Preview and fill missing YouTube product image, option color and texture data.

The script prefers confirmed Olive Young product/option matches already stored in
the local database. For other products it reads metadata from their recorded source
page. It never selects an arbitrary Google image, overwrites existing values, or
infers a shade from a general product thumbnail. Preview is the default.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import getpass
import html
import json
import re
import unicodedata
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse

import asyncpg
import httpx

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
TEXTURES = {"matte", "velvet", "cream", "satin", "sheer", "glossy", "shimmer"}
COLOR_METHODS = {"swatch", "color_chip", "pencil_tip"}
TEXTURE_LABELS = {
    "matte": "matte",
    "매트": "matte",
    "무광": "matte",
    "velvet": "velvet",
    "벨벳": "velvet",
    "세미매트": "velvet",
    "cream": "cream",
    "크림": "cream",
    "크리미": "cream",
    "satin": "satin",
    "새틴": "satin",
    "sheer": "sheer",
    "시어": "sheer",
    "쉬어": "sheer",
    "워터리": "sheer",
    "glossy": "glossy",
    "글로시": "glossy",
    "글로스": "glossy",
    "물광": "glossy",
    "shimmer": "shimmer",
    "쉬머": "shimmer",
    "글리터": "shimmer",
    "펄": "shimmer",
}
REPORT_COLUMNS = (
    "yt_product_id",
    "brand_name",
    "product_name",
    "option_name",
    "source_page_url",
    "proposed_image_url",
    "proposed_hex_code",
    "proposed_texture",
    "image_evidence",
    "color_evidence",
    "texture_evidence",
    "source_search_url",
    "approved",
    "result",
)


def _key(value: str | None) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def _absolute_http_url(value: str | None, base: str) -> str | None:
    if not value:
        return None
    candidate = urljoin(base, html.unescape(value.strip()))
    return candidate if urlparse(candidate).scheme in {"http", "https"} else None


def _as_images(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for part in value for item in _as_images(part)]
    if isinstance(value, dict):
        return _as_images(value.get("url") or value.get("contentUrl"))
    return []


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.jsonld: list[str] = []
        self._in_jsonld = False
        self._script_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag.lower() == "meta":
            name = (values.get("property") or values.get("name") or "").lower()
            content = values.get("content")
            if name and content:
                self.meta[name] = content
        elif tag.lower() == "script" and "ld+json" in values.get("type", "").lower():
            self._in_jsonld = True
            self._script_parts = []

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self._in_jsonld:
            self.jsonld.append("".join(self._script_parts))
            self._in_jsonld = False
            self._script_parts = []

    def handle_data(self, data):
        if self._in_jsonld:
            self._script_parts.append(data)


def _walk_products(value):
    if isinstance(value, list):
        for item in value:
            yield from _walk_products(item)
    elif isinstance(value, dict):
        types = value.get("@type", [])
        if isinstance(types, str):
            types = [types]
        if any("product" in str(item).lower() for item in types):
            yield value
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from _walk_products(child)


def _parse_texture(value: str | None) -> str | None:
    text = _key(value)
    if not text:
        return None
    # Use only explicit structured properties; avoid classifying from arbitrary copy.
    for label, code in sorted(TEXTURE_LABELS.items(), key=lambda item: -len(item[0])):
        if _key(label) == text:
            return code
    return None


def parse_page(body: str, page_url: str, option_name: str | None) -> dict:
    parser = PageParser()
    parser.feed(body)
    image = parser.meta.get("og:image") or parser.meta.get("twitter:image")
    image = _absolute_http_url(image, page_url)
    texture = None
    texture_evidence = None
    hex_code = None
    color_evidence = None
    option_key = _key(option_name)

    for raw in parser.jsonld:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for product in _walk_products(data):
            if image is None:
                images = _as_images(product.get("image"))
                if images:
                    image = _absolute_http_url(images[0], page_url)
            properties = product.get("additionalProperty", [])
            if isinstance(properties, dict):
                properties = [properties]
            for prop in properties:
                if not isinstance(prop, dict):
                    continue
                label = _key(str(prop.get("name") or ""))
                value = str(prop.get("value") or "").strip()
                if label in {"texture", "finish", "제형", "텍스처", "마무리감"} and texture is None:
                    texture = _parse_texture(value)
                    if texture:
                        texture_evidence = f"JSON-LD {label}={value}"
                if (
                    label in {"hex", "hex code", "색상코드", "컬러코드"}
                    and HEX.fullmatch(value)
                    and not option_key
                ):
                    hex_code = value.upper()
                    color_evidence = f"JSON-LD {label}={value}; product has no recorded option"
            if texture is None:
                for label in ("texture", "finish"):
                    texture = _parse_texture(str(product.get(label) or ""))
                    if texture:
                        texture_evidence = f"JSON-LD {label}={product.get(label)}"
                        break
            variants = product.get("hasVariant", [])
            if isinstance(variants, dict):
                variants = [variants]
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                variant_name = _key(str(variant.get("name") or variant.get("color") or ""))
                color = str(variant.get("color") or "").strip()
                if option_key and variant_name == option_key and HEX.fullmatch(color):
                    hex_code = color.upper()
                    color_evidence = f"JSON-LD variant {variant.get('name')} color={color}"
                    break
    return {
        "image_url": image,
        "hex_code": hex_code,
        "texture": texture,
        "image_evidence": "og:image/twitter:image or JSON-LD Product.image" if image else None,
        "color_evidence": color_evidence,
        "texture_evidence": texture_evidence,
    }


async def fetch_page(client: httpx.AsyncClient, url: str) -> tuple[str | None, str | None]:
    try:
        response = await client.get(url, follow_redirects=True, timeout=20)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "html" not in content_type:
            return None, f"not_html:{content_type}"
        return response.text, None
    except (httpx.HTTPError, ValueError) as exc:
        return None, f"fetch_error:{type(exc).__name__}:{str(exc)[:180]}"


async def run(args: argparse.Namespace) -> None:
    if args.host not in {"127.0.0.1", "localhost"}:
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
        old_rows: dict[str, dict] = {}
        if args.report.is_file():
            with args.report.open(encoding="utf-8-sig", newline="") as handle:
                old_reader = csv.DictReader(handle)
                if tuple(old_reader.fieldnames or ()) != REPORT_COLUMNS:
                    raise ValueError(
                        "Review CSV columns changed; move it aside and create a fresh preview"
                    )
                old_rows = {row["yt_product_id"]: row for row in old_reader}

        products = await conn.fetch(
            """SELECT yt_product_id, brand_name, product_name, option_name,
                      image_url, image_source_url, product_url, hex_code, texture
               FROM public.raw_yt_product ORDER BY yt_product_id"""
        )
        confirmed = await conn.fetch(
            """SELECT DISTINCT ON (m.yt_product_id)
                      m.yt_product_id, m.oy_goods_no, m.oy_option_id,
                      p.goods_name, p.delisted_at
               FROM public.yt_oy_product_match m
               JOIN public.raw_oy_product p ON p.goods_no=m.oy_goods_no
               WHERE m.decision_status='confirmed'
               ORDER BY m.yt_product_id, m.decided_at DESC NULLS LAST"""
        )
        confirmed_by_id = {row["yt_product_id"]: row for row in confirmed}
        oy_options = await conn.fetch(
            """SELECT goods_no, option_id, option_name, shade_name
               FROM public.raw_oy_product_option WHERE delisted_at IS NULL"""
        )
        options_by_goods: dict[str, list] = defaultdict(list)
        for row in oy_options:
            options_by_goods[row["goods_no"]].append(row)
        latest_colors = await conn.fetch(
            """SELECT DISTINCT ON (option_id) option_id, hex_code, color_method
               FROM public.raw_oy_option_color
               ORDER BY option_id, collected_at DESC NULLS LAST"""
        )
        color_by_option = {row["option_id"]: row for row in latest_colors}
        textures = await conn.fetch(
            """SELECT DISTINCT ON (goods_no) goods_no, texture_code
               FROM public.raw_oy_product_texture
               ORDER BY goods_no, collected_at DESC NULLS LAST"""
        )
        texture_by_goods = {row["goods_no"]: row["texture_code"] for row in textures}
        oy_images = await conn.fetch(
            """SELECT DISTINCT ON (goods_no) goods_no, image_url
               FROM public.raw_oy_image
               WHERE image_type='thumbnail' AND option_id IS NULL
                 AND NULLIF(BTRIM(image_url),'') IS NOT NULL
               ORDER BY goods_no, collected_at DESC NULLS LAST, sort_seq NULLS LAST"""
        )
        image_by_goods = {row["goods_no"]: row["image_url"] for row in oy_images}

        # Fetch each source page once, even where multiple YT option rows share it.
        pages: dict[str, dict] = {}
        source_for_product = {
            row["yt_product_id"]: old_rows.get(row["yt_product_id"], {}).get("source_page_url")
            or row["product_url"]
            or row["image_source_url"]
            or (
                f"https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo="
                f"{confirmed_by_id[row['yt_product_id']]['oy_goods_no']}"
                if row["yt_product_id"] in confirmed_by_id
                and not confirmed_by_id[row["yt_product_id"]]["delisted_at"]
                else None
            )
            for row in products
        }
        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0 (compatible; VISHUEResearch/1.0)"},
            limits=httpx.Limits(max_connections=1),
        ) as client:
            source_urls = {
                source_for_product[row["yt_product_id"]]
                for row in products
                if (not row["image_url"] or not row["hex_code"] or not row["texture"])
                and source_for_product[row["yt_product_id"]]
            }
            ordered_urls = sorted(source_urls)
            total_pages = len(ordered_urls)
            page_errors = 0
            print(f"페이지 수집 시작: {total_pages:,}개 주소", flush=True)
            for index, url in enumerate(ordered_urls, start=1):
                parsed = urlparse(url)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    pages[url] = {"error": "invalid_source_url"}
                    page_errors += 1
                else:
                    body, error = await fetch_page(client, url)
                    if body is None:
                        pages[url] = {"error": error}
                        page_errors += 1
                    else:
                        pages[url] = {"body": body}
                    if index < total_pages:
                        await asyncio.sleep(args.delay)
                if index % 10 == 0 or index == total_pages:
                    print(
                        f"페이지 수집 {index:,}/{total_pages:,} "
                        f"(남음 {total_pages - index:,}, 오류 {page_errors:,})",
                        flush=True,
                    )
            if total_pages == 0:
                print("페이지 수집 0/0 (확인할 주소 없음)", flush=True)

        report = []
        updates = []
        fillable_images = fillable_colors = fillable_textures = 0
        total_products = len(products)
        print(f"상품별 정보 분석 시작: {total_products:,}개", flush=True)
        for index, row in enumerate(products, start=1):
            match = confirmed_by_id.get(row["yt_product_id"])
            source_url = source_for_product[row["yt_product_id"]]
            proposed_image = None
            proposed_hex = None
            proposed_texture = None
            image_evidence = color_evidence = texture_evidence = None
            errors = []

            if match and not match["delisted_at"]:
                goods_no = match["oy_goods_no"]
                source_url = (
                    source_url
                    or f"https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo={goods_no}"
                )
                proposed_image = image_by_goods.get(goods_no)
                if proposed_image:
                    image_evidence = "confirmed Olive Young product; raw_oy_image thumbnail"
                option_id = match["oy_option_id"]
                if not option_id and not row["option_name"]:
                    active = options_by_goods.get(goods_no, [])
                    if len(active) == 1:
                        option_id = active[0]["option_id"]
                elif not option_id and row["option_name"]:
                    matches = [
                        option
                        for option in options_by_goods.get(goods_no, [])
                        if _key(option["option_name"]) == _key(row["option_name"])
                        or _key(option["shade_name"]) == _key(row["option_name"])
                    ]
                    if len(matches) == 1:
                        option_id = matches[0]["option_id"]
                color = color_by_option.get(option_id) if option_id else None
                if (
                    color
                    and color["color_method"] in COLOR_METHODS
                    and color["hex_code"]
                    and HEX.fullmatch(color["hex_code"])
                ):
                    proposed_hex = color["hex_code"].upper()
                    color_evidence = f"confirmed OY option {option_id}; {color['color_method']}"
                oy_texture = texture_by_goods.get(goods_no)
                if oy_texture in TEXTURES:
                    proposed_texture = oy_texture
                    texture_evidence = f"confirmed OY product {goods_no}; raw_oy_product_texture"

            if source_url and (
                not proposed_image
                or (not proposed_hex and row["option_name"])
                or not proposed_texture
            ):
                page = pages.get(source_url)
                if page and page.get("body"):
                    parsed = parse_page(page["body"], source_url, row["option_name"])
                    proposed_image = proposed_image or parsed["image_url"]
                    proposed_hex = proposed_hex or parsed["hex_code"]
                    proposed_texture = proposed_texture or parsed["texture"]
                    image_evidence = image_evidence or parsed["image_evidence"]
                    color_evidence = color_evidence or parsed["color_evidence"]
                    texture_evidence = texture_evidence or parsed["texture_evidence"]
                elif page and page.get("error"):
                    errors.append(page["error"])
            elif (
                source_url
                and source_url not in pages
                and (not proposed_image or not proposed_texture)
            ):
                # A URL can be shared by rows but omitted from the initial fetch set
                # when the row already had an image. Do not refetch it here.
                pass

            fill_image = not row["image_url"] and bool(proposed_image)
            fill_hex = not row["hex_code"] and bool(proposed_hex)
            fill_texture = not row["texture"] and bool(proposed_texture)
            new_image = proposed_image if fill_image else None
            new_hex = proposed_hex if fill_hex else None
            new_texture = proposed_texture if fill_texture else None
            fillable_images += int(bool(new_image))
            fillable_colors += int(bool(new_hex))
            fillable_textures += int(bool(new_texture))
            result = (
                "fill_missing"
                if any((fill_image, fill_hex, fill_texture))
                else "needs_source_review"
                if not source_url
                else "no_supported_value_found"
            )
            if errors:
                result = errors[0]
            if any((fill_image, fill_hex, fill_texture)):
                updates.append(
                    (
                        row["yt_product_id"],
                        new_image,
                        source_url if fill_image and not row["image_source_url"] else None,
                        new_hex,
                        new_texture,
                    )
                )
            search_terms = " ".join(
                part
                for part in (row["brand_name"], row["product_name"], row["option_name"])
                if part
            )
            search_url = (
                f"https://www.google.com/search?q={quote_plus(search_terms)}"
                if not source_url
                else ""
            )
            old_approval = old_rows.get(row["yt_product_id"], {})
            approved = ""
            if old_approval and old_approval.get("approved", "").strip().lower() in {
                "yes",
                "y",
                "true",
                "1",
            }:
                current_proposal = (
                    source_url or "",
                    new_image or "",
                    new_hex or "",
                    new_texture or "",
                )
                reviewed_proposal = (
                    old_approval.get("source_page_url", ""),
                    old_approval.get("proposed_image_url", ""),
                    old_approval.get("proposed_hex_code", ""),
                    old_approval.get("proposed_texture", ""),
                )
                if current_proposal == reviewed_proposal:
                    approved = "yes"
            report.append(
                (
                    row["yt_product_id"],
                    row["brand_name"],
                    row["product_name"],
                    row["option_name"],
                    source_url,
                    new_image or "",
                    new_hex or "",
                    new_texture or "",
                    image_evidence,
                    color_evidence,
                    texture_evidence,
                    search_url,
                    approved,
                    result,
                )
            )
            if index % 10 == 0 or index == total_products:
                print(
                    f"상품 분석 {index:,}/{total_products:,} "
                    f"(남음 {total_products - index:,}, "
                    f"이미지 {fillable_images:,}, 색상 {fillable_colors:,}, "
                    f"제형 {fillable_textures:,})",
                    flush=True,
                )
        if total_products == 0:
            print("상품 분석 0/0 (대상 상품 없음)", flush=True)

        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(REPORT_COLUMNS)
            writer.writerows(report)
        print(f"Products reviewed: {len(products):,}; unique source pages fetched: {len(pages):,}")
        print(
            "Fillable proposals: "
            f"image URL {sum(bool(row[5]) for row in report):,}; "
            f"option color {sum(bool(row[6]) for row in report):,}; "
            f"texture {sum(bool(row[7]) for row in report):,}; "
            f"no source page {sum(row[-1] == 'needs_source_review' for row in report):,}"
        )
        print(f"Report: {args.report}")
        if not args.apply:
            print(
                "Preview only; no database rows were written. "
                "Set approved=yes for verified rows before --apply."
            )
            return
        approved_ids = {row[0] for row in report if row[-2] == "yes"}
        updates = [update for update in updates if update[0] in approved_ids]
        if not updates:
            raise ValueError("No approved, unchanged suggestions found in the existing review CSV")
        async with conn.transaction():
            await conn.executemany(
                """UPDATE public.raw_yt_product
                   SET image_url=COALESCE(image_url,$2),
                       image_source_url=COALESCE(image_source_url,$3),
                       hex_code=COALESCE(hex_code,$4),
                       texture=COALESCE(texture,$5), updated_at=now()
                   WHERE yt_product_id=$1""",
                updates,
            )
        print(f"Applied {len(updates):,} rows; existing values were preserved")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15432)
    parser.add_argument("--database", default="vishue_db")
    parser.add_argument("--user", default="vishue")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path.home() / "Downloads" / "youtube-product-assets-review.csv",
    )
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.delay < 0:
        parser.error("--delay must be non-negative")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
