"""Save MFDS cosmetic-ingredient API records locally; never write to a database.

Run from backend/api with `uv run python ../../scripts/data/mfds/collect_ingredients.py`.
The API key is read from MFDS_SERVICE_KEY or prompted without echoing it.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote

import httpx

ENDPOINT = (
    "https://apis.data.go.kr/1471000/CsmtcsIngdCpntInfoService01/getCsmtcsIngdCpntInfoService01"
)
RETRYABLE_HTTP = {429, 500, 502, 503, 504}
RETRYABLE_API = {"05", "23"}


def parse_page(payload: object, page_no: int) -> tuple[int, list[dict[str, object]]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("header"), dict):
        raise ValueError("Response has no JSON header")
    header = payload["header"]
    if str(header.get("resultCode")) != "00":
        raise ValueError(f"API resultCode={header.get('resultCode')}")
    body = payload.get("body")
    if not isinstance(body, dict):
        raise ValueError("Response has no JSON body")
    try:
        returned_page = int(body["pageNo"])
        total_count = int(body["totalCount"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid pageNo or totalCount") from exc
    if returned_page != page_no or total_count < 0:
        raise ValueError(f"Unexpected pageNo or totalCount on page {page_no}")
    items = body.get("items") or []
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValueError("body.items is not a list of records")
    return total_count, items


def fetch_page(
    client: httpx.Client, key: str, page_no: int, page_size: int
) -> tuple[int, list[dict[str, object]]]:
    params = {"serviceKey": key, "pageNo": page_no, "numOfRows": page_size, "type": "json"}
    for attempt in range(4):
        try:
            response = client.get(ENDPOINT, params=params)
        except httpx.RequestError as exc:
            if attempt == 3:
                raise RuntimeError(
                    f"Page {page_no}: network error ({type(exc).__name__})"
                ) from None
            time.sleep(2**attempt)
            continue
        if response.status_code in RETRYABLE_HTTP and attempt < 3:
            time.sleep(2**attempt)
            continue
        if response.status_code != 200:
            raise RuntimeError(f"Page {page_no}: HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            raise RuntimeError(f"Page {page_no}: response is not JSON") from None
        try:
            return parse_page(payload, page_no)
        except ValueError as exc:
            header = payload.get("header") if isinstance(payload, dict) else None
            code = str(header.get("resultCode")) if isinstance(header, dict) else ""
            if code in RETRYABLE_API and attempt < 3:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(f"Page {page_no}: {exc}") from None
    raise AssertionError("Retry loop ended unexpectedly")


def collect(
    client: httpx.Client,
    key: str,
    output: Path,
    page_size: int,
    delay: float,
    max_pages: int | None,
) -> dict[str, object]:
    output = output.resolve()
    partial = output.with_name(output.name + ".partial")
    metadata_path = output.with_name(output.name + ".meta.json")
    if output.exists() or partial.exists() or metadata_path.exists():
        raise FileExistsError(f"Output or partial file already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    names: Counter[str] = Counter()
    fingerprints: Counter[str] = Counter()
    fields: set[str] = set()
    missing_names = 0
    bullet_rows = 0
    written = 0
    expected: int | None = None
    page_no = 1
    started_at = datetime.now(UTC).isoformat()
    with partial.open("x", encoding="utf-8", newline="\n") as destination:
        while True:
            total_count, items = fetch_page(client, key, page_no, page_size)
            if expected is None:
                expected = total_count
                print(f"API totalCount: {expected:,}", flush=True)
            elif total_count != expected:
                raise ValueError("totalCount changed during collection; discard the partial file")
            if len(items) > page_size or not items and written < expected:
                raise ValueError(f"Unexpected item count on page {page_no}")
            for item in items:
                encoded = json.dumps(
                    item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                destination.write(encoded + "\n")
                written += 1
                fields.update(item)
                name = item.get("INGR_KOR_NAME")
                if isinstance(name, str) and name.strip():
                    names[name.strip()] += 1
                else:
                    missing_names += 1
                fingerprints[hashlib.sha256(encoded.encode("utf-8")).hexdigest()] += 1
                bullet_rows += "■" in encoded
            print(f"Page {page_no}: {len(items):,} rows; collected {written:,}", flush=True)
            if written > expected:
                raise ValueError("Collected more records than totalCount")
            if written == expected or max_pages is not None and page_no >= max_pages:
                break
            page_no += 1
            time.sleep(delay)

    complete = written == expected
    if complete and expected and page_no != (expected + page_size - 1) // page_size:
        raise ValueError("Page count does not agree with totalCount")
    metadata: dict[str, object] = {
        "source": "MFDS cosmetic ingredient API",
        "endpoint": ENDPOINT,
        "started_at_utc": started_at,
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "page_size": page_size,
        "pages_fetched": page_no,
        "total_count_reported": expected,
        "rows_saved": written,
        "complete": complete,
        "fields_seen": sorted(fields),
        "missing_korean_name": missing_names,
        "repeated_korean_names": sum(count - 1 for count in names.values()),
        "repeated_name_examples": [
            {"name": name, "count": count} for name, count in names.most_common() if count > 1
        ][:10],
        "exact_duplicate_rows": sum(count - 1 for count in fingerprints.values()),
        "records_containing_square_bullet": bullet_rows,
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    partial.replace(output)
    print(f"Saved {written:,} records to {output}", flush=True)
    print(f"Audit metadata: {metadata_path}", flush=True)
    print(f"Complete snapshot: {complete}", flush=True)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--max-pages", type=int)
    args = parser.parse_args()
    if not 1 <= args.page_size <= 1000:
        parser.error("--page-size must be between 1 and 1000")
    if args.delay < 0 or args.max_pages is not None and args.max_pages < 1:
        parser.error("--delay must be non-negative and --max-pages must be positive")
    key = os.environ.get("MFDS_SERVICE_KEY") or getpass.getpass("MFDS service key: ")
    if not key.strip():
        parser.error("MFDS service key is empty")
    # httpx URL-encodes params itself. Decode a portal-provided encoded key once.
    key = unquote(key.strip()) if re.search(r"%[0-9A-Fa-f]{2}", key) else key.strip()
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        collect(client, key, args.output, args.page_size, args.delay, args.max_pages)


if __name__ == "__main__":
    main()
