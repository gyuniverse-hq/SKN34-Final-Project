"""Collect Glowpick price/category candidates for YouTube products missing a price.

The default collect phase only writes a review CSV. Review one candidate per
YouTube product, mark it approved=yes, run the verify phase to read the selected
Glowpick product page, then run apply to fill only still-empty database fields.
This script is restricted to a local PostgreSQL database.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import difflib
import getpass
import json
import threading
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode

import asyncpg
import httpx

BASE_URL = "https://www.glowpick.com"
# Glowpick's web client exposes this public web API key in its JavaScript bundle.
GLOWPICK_API_KEY = "b9d54cc0-5ea5-11ea-b7f9-41b4f2de8659"
REPORT_COLUMNS = (
    "yt_product_id",
    "source_brand",
    "source_product_name",
    "source_category_current",
    "candidate_rank",
    "similarity_score",
    "brand_match",
    "candidate_source",
    "glowpick_product_id",
    "glowpick_brand",
    "glowpick_product_name",
    "search_price_krw",
    "glowpick_product_url",
    "detail_price_krw",
    "glowpick_category",
    "detail_status",
    "detail_error",
    "approved",
    "source_status",
)
APPROVED = {"yes", "y", "true", "1"}
MAX_CANDIDATES = 5


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise ValueError("Truncated protobuf varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
        if shift > 70:
            raise ValueError("Invalid protobuf varint")


def _fields(data: bytes) -> list[tuple[int, int, int | bytes]]:
    fields = []
    offset = 0
    while offset < len(data):
        tag, offset = _read_varint(data, offset)
        number, wire_type = tag >> 3, tag & 7
        if wire_type == 0:
            value, offset = _read_varint(data, offset)
        elif wire_type == 2:
            length, offset = _read_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise ValueError("Truncated protobuf field")
            value = data[offset:end]
            offset = end
        elif wire_type == 1:
            value = data[offset : offset + 8]
            offset += 8
        elif wire_type == 5:
            value = data[offset : offset + 4]
            offset += 4
        else:
            raise ValueError(f"Unsupported protobuf wire type: {wire_type}")
        fields.append((number, wire_type, value))
    return fields


def _encode_varint(value: int) -> bytes:
    output = bytearray()
    while value > 0x7F:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _encode_search_all(query: str) -> str:
    encoded = query.encode("utf-8")
    payload = _encode_varint((1 << 3) | 2) + _encode_varint(len(encoded)) + encoded
    return base64.b64encode(payload).decode("ascii")


def _decode_string(value: bytes) -> str:
    for encoding in ("utf-8", "cp949", "euc-kr"):
        try:
            return value.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return value.decode("utf-8", errors="replace").strip()


def _first(fields: list[tuple[int, int, int | bytes]], number: int, default=None):
    return next((value for field, _, value in fields if field == number), default)


def _parse_products(response: dict) -> list[dict]:
    if response.get("type") != "api_j.SearchAllRes" or not response.get("data"):
        raise ValueError(f"Unexpected Glowpick search response: {response.get('type')}")
    root = _fields(base64.b64decode(response["data"]))

    def parse_product(raw_product: bytes, source: str) -> dict | None:
        product_fields = _fields(raw_product)
        product_id = _first(product_fields, 1)
        title = _first(product_fields, 3, b"")
        price = _first(product_fields, 5)
        brand_raw = _first(product_fields, 201, b"")
        if not product_id or not isinstance(title, bytes):
            return None
        brand = ""
        if brand_raw:
            brand_fields = _fields(brand_raw)
            brand = _decode_string(_first(brand_fields, 5, b"")) or _decode_string(
                _first(brand_fields, 4, b"")
            )
        return {
            "product_id": int(product_id),
            "name": _decode_string(title),
            "brand": brand,
            "price": int(price) if isinstance(price, int) and price > 0 else None,
            "candidate_source": source,
        }

    result_by_id: dict[int, dict] = {}

    def add(raw_product: bytes, source: str) -> None:
        candidate = parse_product(raw_product, source)
        if not candidate:
            return
        previous = result_by_id.get(candidate["product_id"])
        if previous:
            sources = set(previous["candidate_source"].split("+"))
            sources.add(source)
            previous["candidate_source"] = "+".join(
                item for item in ("product_search", "review_tag") if item in sources
            )
            # Prefer available metadata regardless of which result type appeared first.
            for key in ("name", "brand", "price"):
                if not previous.get(key) and candidate.get(key):
                    previous[key] = candidate[key]
        else:
            result_by_id[candidate["product_id"]] = candidate

    # SearchAllRes.searchProduct (field 1) contains direct product results.
    search_products = _first(root, 1, b"")
    if isinstance(search_products, bytes):
        for _, _, raw_product in _fields(search_products):
            add(raw_product, "product_search")

    # SearchAllRes.searchReview (field 3) contains reviews; each review can
    # carry its tagged common.Product in field 201.
    search_reviews = _first(root, 3, b"")

    def tagged_products(message: bytes, depth: int = 0):
        if depth > 6:
            return
        try:
            fields = _fields(message)
        except ValueError:
            return
        for field_number, wire_type, value in fields:
            if wire_type != 2 or not isinstance(value, bytes):
                continue
            if field_number == 201:
                candidate = parse_product(value, "review_tag")
                if candidate:
                    yield value
            # Review results may wrap common.Review in a search-result message.
            # Walk the wrappers so tagged products are found at either level.
            if field_number != 201:
                yield from tagged_products(value, depth + 1)

    if isinstance(search_reviews, bytes):
        for _, _, raw_review_result in _fields(search_reviews):
            for raw_product in tagged_products(raw_review_result):
                add(raw_product, "review_tag")

    return list(result_by_id.values())


def _normalize(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(char for char in text if char.isalnum())


def _similarity(source: str, candidate: str) -> float:
    return round(
        difflib.SequenceMatcher(
            None, _normalize(source), _normalize(candidate)
        ).ratio(),
        4,
    )


class DetailParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.jsonld: list[str] = []
        self.meta: dict[str, str] = {}
        self.in_jsonld = False
        self.script_data: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag.lower() == "meta":
            name = (values.get("property") or values.get("name") or "").lower()
            if name and values.get("content"):
                self.meta[name] = values["content"]
        if tag.lower() == "script" and "ld+json" in values.get("type", "").lower():
            self.in_jsonld = True
            self.script_data = []

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self.in_jsonld:
            self.jsonld.append("".join(self.script_data))
            self.in_jsonld = False
            self.script_data = []

    def handle_data(self, data):
        if self.in_jsonld:
            self.script_data.append(data)


def _walk(value):
    if isinstance(value, list):
        for item in value:
            yield from _walk(item)
    elif isinstance(value, dict):
        yield value
        for item in value.values():
            if isinstance(item, (dict, list)):
                yield from _walk(item)


def _parse_detail(body: str, expected_id: int) -> dict:
    parser = DetailParser()
    parser.feed(body)
    price = None
    detail_name = parser.meta.get("og:title", "")
    detail_brand = ""
    categories: list[str] = []
    canonical = parser.meta.get("og:url", "")

    for raw in parser.jsonld:
        try:
            document = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for item in _walk(document):
            kind = item.get("@type", [])
            if isinstance(kind, str):
                kind = [kind]
            if "Product" in kind and f"/products/{expected_id}" in str(
                item.get("url") or item.get("@id") or canonical
            ):
                detail_name = str(item.get("name") or detail_name).strip()
                brand = item.get("brand")
                if isinstance(brand, dict):
                    detail_brand = str(brand.get("name") or "").strip()
                offers = item.get("offers")
                if isinstance(offers, list):
                    offers = offers[0] if offers else None
                if isinstance(offers, dict):
                    try:
                        parsed_price = int(float(offers.get("price")))
                        if parsed_price > 0:
                            price = parsed_price
                    except (TypeError, ValueError):
                        pass
            if item.get("@type") == "BreadcrumbList":
                for entry in item.get("itemListElement", []):
                    name = entry.get("name") if isinstance(entry, dict) else None
                    if name and str(name).strip() not in {"글로우픽", "홈"}:
                        categories.append(str(name).strip())

    categories = list(dict.fromkeys(categories))
    return {
        "price": price,
        "name": detail_name,
        "brand": detail_brand,
        "category": " > ".join(categories),
        "canonical_url": canonical,
        "has_product_schema": price is not None or bool(detail_name),
    }


class RateLimitStopped(RuntimeError):
    """Glowpick remained blocked after the configured shared cooldowns."""


class RequestGate:
    """Share request pacing and 403/429 cooldowns across all workers."""

    waits = (60, 180, 600)

    def __init__(self, delay: float):
        self.delay = delay
        self.condition = threading.Condition()
        self.next_request_at = 0.0
        self.blocked_until = 0.0
        self.block_round = 0
        self.stopped = False

    def wait_for_slot(self) -> None:
        with self.condition:
            while True:
                if self.stopped:
                    raise RateLimitStopped("수집기가 차단 대기 한도를 초과해 중단됨")
                now = time.monotonic()
                delay = max(self.next_request_at - now, self.blocked_until - now)
                if delay <= 0:
                    self.next_request_at = now + self.delay
                    return
                self.condition.wait(timeout=min(delay, 5.0))

    def wait_after_limit(self, status: int, url: str, retry_after: str | None) -> None:
        with self.condition:
            now = time.monotonic()
            if now >= self.blocked_until:
                if self.block_round >= len(self.waits):
                    self.stopped = True
                    self.condition.notify_all()
                    raise RateLimitStopped(
                        f"HTTP {status} 차단이 계속되어 1·3·10분 재시도 후 중단: {url}"
                    )
                seconds = self.waits[self.block_round]
                try:
                    seconds = max(seconds, int(retry_after or 0))
                except ValueError:
                    pass
                self.block_round += 1
                self.blocked_until = now + seconds
                print(
                    f"\nGlowpick HTTP {status}; 전체 작업자 {seconds // 60}분 "
                    f"{seconds % 60}초 대기 후 재시도 "
                    f"({self.block_round}/{len(self.waits)}): {url}",
                    flush=True,
                )
            self.condition.notify_all()
            while not self.stopped:
                remain = self.blocked_until - time.monotonic()
                if remain <= 0:
                    return
                self.condition.wait(timeout=min(remain, 5.0))
            raise RateLimitStopped("수집기가 차단 대기 한도를 초과해 중단됨")

    def note_success(self) -> None:
        with self.condition:
            if not self.stopped and time.monotonic() >= self.blocked_until:
                self.block_round = 0
                self.condition.notify_all()

    def stop(self) -> None:
        with self.condition:
            self.stopped = True
            self.condition.notify_all()


class GlowpickClient:
    def __init__(self, delay: float):
        self.gate = RequestGate(delay)
        self._token_lock = threading.Lock()
        self.token: str | None = None
        self.client = httpx.Client(
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                    "Mobile/15E148 Safari/604.1"
                ),
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
                "Origin": BASE_URL,
                "Referer": f"{BASE_URL}/",
                "Content-Type": "application/json",
                "x-api-key": GLOWPICK_API_KEY,
                # The endpoint is Glowpick's web API behind the web proxy.
                "glowpick-os": "web",
                "x-api-type": "proto",
            },
            timeout=25,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=10),
        )

    def close(self):
        self.client.close()

    def stop(self):
        self.gate.stop()

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        while True:
            self.gate.wait_for_slot()
            response = self.client.request(method, url, **kwargs)
            if response.status_code in {403, 429}:
                self.gate.wait_after_limit(
                    response.status_code,
                    url.split("?", maxsplit=1)[0],
                    response.headers.get("Retry-After"),
                )
                continue
            if response.status_code < 400:
                self.gate.note_success()
            return response

    def ensure_token(self) -> str:
        if self.token:
            return self.token
        with self._token_lock:
            if not self.token:
                self._get_token()
        return self.token or ""

    def _get_token(self) -> str:
        response = self._request(
            "POST",
            f"{BASE_URL}/api/proxy/authJs/public/auth/token",
            json={"device_uuid": str(uuid.uuid4())},
        )
        response.raise_for_status()
        body = response.json()
        if body.get("type") != "auth_js.PostAuthTokenRes":
            raise ValueError("Could not obtain a public Glowpick web token")
        fields = _fields(base64.b64decode(body["data"]))
        token = _first(fields, 1, b"")
        if not isinstance(token, bytes) or not token:
            raise ValueError("Glowpick did not return an access token")
        self.token = _decode_string(token)
        return self.token

    def _refresh_token(self, rejected_token: str) -> str:
        with self._token_lock:
            if self.token == rejected_token:
                self._get_token()
            return self.token or self._get_token()

    def search(self, query: str) -> list[dict]:
        token = self.ensure_token()
        params = urlencode(
            {"data": _encode_search_all(query), "type": "api_j.SearchAllReq"}
        )
        url = f"{BASE_URL}/api/proxy/apiJ/v4/api/search/all?{params}"
        response = self._request(
            "GET", url, headers={"Authorization": f"Bearer {token}"}
        )
        if response.status_code == 401:
            token = self._refresh_token(token)
            response = self._request(
                "GET", url, headers={"Authorization": f"Bearer {token}"}
            )
        response.raise_for_status()
        return _parse_products(response.json())

    def search_page(self, query: str) -> str:
        """Fetch Glowpick's browser-facing keyword results page as API fallback."""
        response = self._request(
            "GET",
            f"{BASE_URL}/searches/keywords?{urlencode({'search': query})}",
        )
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text

    def detail(self, product_id: int) -> dict:
        response = self._request("GET", f"{BASE_URL}/products/{product_id}")
        response.raise_for_status()
        result = _parse_detail(response.text, product_id)
        if not result["has_product_schema"]:
            raise ValueError("Glowpick product detail has no structured product data")
        return result


def _search_source(source: dict, glowpick: GlowpickClient) -> list[dict]:
    queries = [source["product_name"]]
    if _is_known_brand(source["brand_name"]) and _normalize(
        source["brand_name"]
    ) not in _normalize(source["product_name"]):
        queries.insert(0, f"{source['brand_name']} {source['product_name']}")
    combined: dict[int, dict] = {}
    for query in queries:
        for candidate in glowpick.search(query):
            product_id = candidate["product_id"]
            previous = combined.get(product_id)
            if previous:
                sources = set(previous["candidate_source"].split("+"))
                sources.update(candidate["candidate_source"].split("+"))
                previous["candidate_source"] = "+".join(
                    item for item in ("product_search", "review_tag") if item in sources
                )
                for key in ("name", "brand", "price"):
                    if not previous.get(key) and candidate.get(key):
                        previous[key] = candidate[key]
            else:
                combined[product_id] = candidate
    return _rank_candidates(source, list(combined.values()))


def _verify_candidate(row: dict[str, str], glowpick: GlowpickClient) -> dict:
    product_id = int(row["glowpick_product_id"])
    detail = glowpick.detail(product_id)
    if not detail["price"]:
        raise ValueError("Product page did not provide a structured price")
    if row["source_category_current"].strip() == "" and not detail["category"]:
        raise ValueError("Product page did not provide a category breadcrumb")
    return detail


def _load_report(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        current_columns = tuple(reader.fieldnames or ())
        legacy_columns = tuple(
            column for column in REPORT_COLUMNS if column != "candidate_source"
        )
        if current_columns not in {REPORT_COLUMNS, legacy_columns}:
            raise ValueError("Review CSV columns do not match; use a new --report path")
        rows = list(reader)
        if "candidate_source" not in current_columns:
            for row in rows:
                row["candidate_source"] = "previous_search"
        return rows


def _write_report(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=REPORT_COLUMNS, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)


def _save_report(path: Path, rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        _write_report(temporary, rows)
        for attempt in range(3):
            try:
                temporary.replace(path)
                return path
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(1)
    except PermissionError:
        recovery = path.with_name(
            f"{path.stem}.recovery-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}{path.suffix}"
        )
        _write_report(recovery, rows)
        print(
            f"\nReport is locked or inaccessible: {path}\n"
            f"Latest progress saved separately to: {recovery}\n"
            "Close the report in Excel before using the original path again.",
            flush=True,
        )
        return recovery
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
    return path


def _approved(row: dict[str, str]) -> bool:
    return row.get("approved", "").strip().lower() in APPROVED


def _candidate_key(row: dict[str, str]) -> tuple[str, str]:
    return row.get("yt_product_id", ""), row.get("glowpick_product_id", "")


def _is_known_brand(value: str | None) -> bool:
    return _normalize(value) not in {
        "",
        "확인필요",
        "미상",
        "없음",
        "unknown",
        "none",
        "na",
    }


def _rank_candidates(source: dict, candidates: list[dict]) -> list[dict]:
    ranked = []
    source_brand = (
        _normalize(source["brand_name"])
        if _is_known_brand(source["brand_name"])
        else ""
    )
    for item in candidates:
        title_score = _similarity(source["product_name"], item["name"])
        candidate_brand = _normalize(item["brand"])
        brand_match = "not_available"
        if source_brand and candidate_brand:
            brand_match = (
                "exact"
                if source_brand == candidate_brand
                else "partial"
                if source_brand in candidate_brand or candidate_brand in source_brand
                else "different"
            )
        item = {**item, "score": title_score, "brand_match": brand_match}
        ranked.append(item)
    ranked.sort(
        key=lambda item: (
            item["brand_match"] not in {"exact", "partial"},
            -item["score"],
            item["product_id"],
        )
    )
    return ranked[:MAX_CANDIDATES]


async def _connect(args: argparse.Namespace) -> asyncpg.Connection:
    if args.host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Only a local PostgreSQL host is supported")
    password = getpass.getpass("Local PostgreSQL password: ")
    return await asyncpg.connect(
        host=args.host,
        port=args.port,
        database=args.database,
        user=args.user,
        password=password,
        ssl=False,
    )


async def collect(args: argparse.Namespace) -> None:
    conn = await _connect(args)
    glowpick = GlowpickClient(args.delay)
    try:
        products = await conn.fetch(
            """SELECT yt_product_id, brand_name, product_name, category
               FROM public.raw_yt_product
               WHERE price_krw IS NULL
               ORDER BY yt_product_id"""
        )
        if args.limit is not None:
            products = products[: args.limit]
        old_rows = _load_report(args.report)
        rows = list(old_rows)
        by_source: dict[str, list[dict[str, str]]] = {}
        for row in old_rows:
            by_source.setdefault(row["yt_product_id"], []).append(row)
        already_done = (
            set()
            if args.refresh
            else {
                yt_id
                for yt_id, prior in by_source.items()
                if prior
                and all(
                    row.get("source_status") in {"found", "no_results"} for row in prior
                )
            }
        )
        pending = [row for row in products if row["yt_product_id"] not in already_done]
        print(
            f"Price-missing source products: {len(products):,}; "
            f"already reviewed: {len(products) - len(pending):,}; remaining: {len(pending):,}; "
            f"workers: {args.workers}; mobile browser headers enabled",
            flush=True,
        )
        if args.refresh:
            print(
                "Refresh enabled; all current price-missing products will be searched again"
            )
        if pending:
            # Fetch the web token before workers start so they share one valid token.
            glowpick.ensure_token()
        found_count = no_result_count = error_count = completed = 0
        executor = ThreadPoolExecutor(max_workers=args.workers)
        futures = {
            executor.submit(_search_source, source, glowpick): source
            for source in pending
        }
        try:
            for future in as_completed(futures):
                source = futures[future]
                yt_id = source["yt_product_id"]
                rows = [row for row in rows if row.get("yt_product_id") != yt_id]
                base = {column: "" for column in REPORT_COLUMNS}
                try:
                    candidates = future.result()
                    if not candidates:
                        rows.append(
                            {
                                **base,
                                "yt_product_id": yt_id,
                                "source_brand": source["brand_name"],
                                "source_product_name": source["product_name"],
                                "source_category_current": source["category"] or "",
                                "source_status": "no_results",
                            }
                        )
                        no_result_count += 1
                    else:
                        for rank, candidate in enumerate(candidates, start=1):
                            key = (yt_id, str(candidate["product_id"]))
                            old = next(
                                (
                                    entry
                                    for entry in by_source.get(yt_id, [])
                                    if _candidate_key(entry) == key
                                ),
                                {},
                            )
                            rows.append(
                                {
                                    **base,
                                    "yt_product_id": yt_id,
                                    "source_brand": source["brand_name"],
                                    "source_product_name": source["product_name"],
                                    "source_category_current": source["category"] or "",
                                    "candidate_rank": str(rank),
                                    "similarity_score": f"{candidate['score']:.4f}",
                                    "brand_match": candidate["brand_match"],
                                    "candidate_source": candidate["candidate_source"],
                                    "glowpick_product_id": str(candidate["product_id"]),
                                    "glowpick_brand": candidate["brand"],
                                    "glowpick_product_name": candidate["name"],
                                    "search_price_krw": str(candidate["price"] or ""),
                                    "glowpick_product_url": f"{BASE_URL}/products/{candidate['product_id']}",
                                    "approved": old.get("approved", ""),
                                    "detail_price_krw": old.get("detail_price_krw", ""),
                                    "glowpick_category": old.get(
                                        "glowpick_category", ""
                                    ),
                                    "detail_status": old.get("detail_status", ""),
                                    "detail_error": old.get("detail_error", ""),
                                    "source_status": "found",
                                }
                            )
                        found_count += 1
                except RateLimitStopped as exc:
                    print(f"\n{exc}", flush=True)
                    glowpick.stop()
                    for queued in futures:
                        queued.cancel()
                    args.report = _save_report(args.report, rows)
                    break
                except (httpx.HTTPError, ValueError, KeyError, StopIteration) as exc:
                    rows.append(
                        {
                            **base,
                            "yt_product_id": yt_id,
                            "source_brand": source["brand_name"],
                            "source_product_name": source["product_name"],
                            "source_category_current": source["category"] or "",
                            "source_status": "error",
                            "detail_error": f"{type(exc).__name__}: {str(exc)[:240]}",
                        }
                    )
                    error_count += 1
                completed += 1
                if completed % 10 == 0 or completed == len(pending):
                    args.report = _save_report(args.report, rows)
                    print(
                        f"Search {completed:,}/{len(pending):,} (remaining {len(pending) - completed:,}; "
                        f"found {found_count:,}; no results {no_result_count:,}; errors {error_count:,})",
                        flush=True,
                    )
        except KeyboardInterrupt:
            glowpick.stop()
            for queued in futures:
                queued.cancel()
            args.report = _save_report(args.report, rows)
            print(
                "\nInterrupted; completed rows were checkpointed and no DB rows were written"
            )
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
        if not pending:
            args.report = _save_report(args.report, rows)
        print(f"Review CSV: {args.report}")
        print("Collection phase finished; no database rows were written")
    finally:
        glowpick.close()
        await conn.close()


async def verify(args: argparse.Namespace) -> None:
    rows = _load_report(args.report)
    approved_rows = [row for row in rows if _approved(row)]
    approved_ids = [row["yt_product_id"] for row in approved_rows]
    if len(approved_ids) != len(set(approved_ids)):
        raise ValueError("Approve at most one Glowpick candidate per yt_product_id")
    glowpick = GlowpickClient(args.delay)
    try:
        total = len(approved_rows)
        verified = errors = completed = 0
        if approved_rows:
            glowpick.ensure_token()
        executor = ThreadPoolExecutor(max_workers=args.workers)
        futures = {
            executor.submit(_verify_candidate, row, glowpick): row
            for row in approved_rows
        }
        try:
            for future in as_completed(futures):
                row = futures[future]
                try:
                    detail = future.result()
                    row["detail_price_krw"] = str(detail["price"])
                    row["glowpick_category"] = detail["category"]
                    row["detail_status"] = "verified"
                    row["detail_error"] = ""
                    verified += 1
                except RateLimitStopped as exc:
                    print(f"\n{exc}", flush=True)
                    glowpick.stop()
                    for queued in futures:
                        queued.cancel()
                    args.report = _save_report(args.report, rows)
                    break
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    row["detail_status"] = "error"
                    row["detail_error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
                    errors += 1
                completed += 1
                if completed % 10 == 0 or completed == total:
                    args.report = _save_report(args.report, rows)
                    print(
                        f"Detail verify {completed:,}/{total:,} (remaining {total - completed:,}; "
                        f"verified {verified:,}; errors {errors:,})",
                        flush=True,
                    )
        except KeyboardInterrupt:
            glowpick.stop()
            for queued in futures:
                queued.cancel()
            args.report = _save_report(args.report, rows)
            print("\nInterrupted; completed verification results were checkpointed")
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
        args.report = _save_report(args.report, rows)
        print(f"Review CSV: {args.report}")
        print("Verification phase finished; no database rows were written")
    finally:
        glowpick.close()


async def apply(args: argparse.Namespace) -> None:
    rows = _load_report(args.report)
    approved_rows = [row for row in rows if _approved(row)]
    approved_ids = [row["yt_product_id"] for row in approved_rows]
    if len(approved_ids) != len(set(approved_ids)):
        raise ValueError("Approve at most one Glowpick candidate per yt_product_id")
    invalid = [
        row["yt_product_id"]
        for row in approved_rows
        if row.get("detail_status") != "verified"
        or not row.get("detail_price_krw")
        or (
            not row.get("source_category_current", "").strip()
            and not row.get("glowpick_category", "").strip()
        )
    ]
    if invalid:
        raise ValueError(
            f"Approved rows need successful detail verification first; pending: {len(invalid)}"
        )
    conn = await _connect(args)
    try:
        updates = []
        for row in approved_rows:
            price = int(row["detail_price_krw"])
            category = row.get("glowpick_category", "").strip() or None
            updates.append((row["yt_product_id"], price, category))
        written = 0
        async with conn.transaction():
            for yt_id, price, category in updates:
                result = await conn.execute(
                    """UPDATE public.raw_yt_product
                       SET price_krw=COALESCE(price_krw,$2),
                           category=COALESCE(NULLIF(BTRIM(category),''),$3),
                           updated_at=now()
                       WHERE yt_product_id=$1
                         AND (price_krw IS NULL OR NULLIF(BTRIM(category),'') IS NULL)""",
                    yt_id,
                    price,
                    category,
                )
                written += int(result.rsplit(" ", 1)[-1])
        print(
            f"Approved candidates: {len(approved_rows):,}; rows updated: {written:,}; "
            "existing price/category values were preserved"
        )
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=("collect", "verify", "apply"), default="collect"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15432)
    parser.add_argument("--database", default="vishue_db")
    parser.add_argument("--user", default="vishue")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path.home() / "Downloads" / "youtube-glowpick-enrichment-review.csv",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-search all price-missing products and replace their prior candidate rows",
    )
    parser.add_argument("--delay", type=float, default=0.4)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.delay < 0.2:
        parser.error("--delay must be at least 0.2 seconds to avoid rapid requests")
    if not 1 <= args.workers <= 10:
        parser.error("--workers must be between 1 and 10")
    if args.phase == "collect":
        asyncio.run(collect(args))
    elif args.phase == "verify":
        asyncio.run(verify(args))
    else:
        asyncio.run(apply(args))


if __name__ == "__main__":
    main()
