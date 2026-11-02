"""Collect a reviewable Olive Young snapshot before any database write.

The local CSV IDs are temporary. load_snapshot.py resolves them against the DB.
Only a complete category listing and complete product collection can be applied.
"""

from __future__ import annotations

import argparse
import csv
import json
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

COLLECTORS = Path(__file__).resolve().parent / "collectors"
sys.path.insert(0, str(COLLECTORS))


def _modules(kind: str):
    import oliveyoung_color_poc16 as oy
    import oliveyoung_erd_v30 as makeup

    if kind == "makeup":
        return oy, makeup, makeup
    import oliveyoung_skincare_v2 as skincare

    return oy, skincare, makeup


def _write_manifest(path: Path, data: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def _finish_run(path: Path, run_id: int, complete: bool, schema: dict) -> None:
    with path.open(encoding="utf-8-sig", newline="") as source:
        records = list(csv.DictReader(source))
    for record in records:
        if record["run_id"] == str(run_id):
            record["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            record["status"] = "done" if complete else "incomplete"
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=schema["crawl_run"])
        writer.writeheader()
        writer.writerows(records)


def unavailable_records(manifest: dict) -> dict:
    """Validate auditable exceptions to a complete category listing."""
    unavailable = manifest.get("unavailable", {})
    if not isinstance(unavailable, dict):
        raise TypeError("Snapshot unavailable records must be an object")
    jobs = [str(job[1]) for job in manifest["jobs"]]
    if len(jobs) != len(set(jobs)) or not set(unavailable) <= set(jobs):
        raise ValueError("Unavailable goods must be unique members of the listing")
    for goods_no, record in unavailable.items():
        if (
            not isinstance(record, dict)
            or record.get("method") not in {"http_404", "http_410", "manual"}
            or not record.get("reason")
            or not record.get("confirmed_at")
        ):
            raise ValueError(f"Invalid unavailable record: {goods_no}")
    return unavailable


def collect(
    kind: str,
    directory: Path,
    workers: int = 10,
    mode: str = "full",
    confirm_unavailable: list[str] | None = None,
) -> dict:
    if workers < 1 or workers > 16:
        raise ValueError("--workers must be between 1 and 16")
    confirm_unavailable = confirm_unavailable or []
    if len(confirm_unavailable) != len(set(confirm_unavailable)):
        raise ValueError("Duplicate --confirm-unavailable goods number")
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    oy, collector, base = _modules(kind)
    script_version = f"{collector.SCRIPT_VERSION}-db"
    if kind == "makeup":
        script_version = f"makeup-{script_version}"
    oy.STOP_EVENT.clear()
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("kind") != kind
            or manifest.get("mode") != mode
            or manifest.get("script_version") != script_version
            or not manifest.get("listing_complete")
        ):
            raise ValueError(
                "Cannot resume a snapshot with a different collector version, "
                "kind, mode, or incomplete listing"
            )
        if manifest.get("complete"):
            if confirm_unavailable:
                raise ValueError("Cannot change an already completed snapshot")
            print("Snapshot is already complete; no new requests were made")
            return manifest
        jobs = [tuple(item) for item in manifest["jobs"]]
        run_id = manifest["run_id"]
    else:
        jobs, seen = [], set()
        targets = oy.TARGETS if kind == "makeup" else collector.TARGETS
        for label, category_no in targets.items():
            goods = (
                oy.list_goods(category_no, None)
                if kind == "makeup"
                else collector.list_goods(category_no, None)
            )
            if not goods:
                raise ValueError(f"Category listing was empty: {label}")
            for goods_no in goods:
                if goods_no not in seen:
                    seen.add(goods_no)
                    jobs.append((label, goods_no))
            print(f"{label}: {len(goods)} items", flush=True)
            time.sleep(oy.THREAD_DELAY)
        run_id = time.time_ns() // 1_000_000
        manifest = {
            "kind": kind,
            "mode": mode,
            "run_id": run_id,
            "script_version": script_version,
            "listing_complete": True,
            "complete": False,
            "jobs": jobs,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }
        _write_manifest(manifest_path, manifest)

    base.OUT_DIR = str(directory)
    base.DONE_LOG = str(directory / "_done.log")
    base.REPORT = str(directory / "collection_report.txt")
    base.SCHEMA = collector.SCHEMA
    base.init_out()
    if kind == "makeup":
        with (directory / "texture_type.csv").open(
            encoding="utf-8-sig", newline=""
        ) as source:
            has_texture_rows = any(csv.DictReader(source))
        if not has_texture_rows:
            base.emit("texture_type", base.TEXTURE_TYPE_ROWS)
    run_csv = directory / "crawl_run.csv"
    with run_csv.open(encoding="utf-8-sig", newline="") as source:
        existing_runs = {r["run_id"] for r in csv.DictReader(source)}
    if str(run_id) not in existing_runs:
        base.emit(
            "crawl_run",
            [
                {
                    "run_id": run_id,
                    "script_version": manifest["script_version"],
                    "started_at": manifest["started_at"],
                    "finished_at": "",
                    "status": "running",
                }
            ],
        )

    done = base.load_done()
    unavailable = unavailable_records(manifest)
    job_numbers = {no for _, no in jobs}
    if not set(confirm_unavailable) <= job_numbers - done:
        raise ValueError("Only listed, unfinished goods can be confirmed unavailable")
    for goods_no in confirm_unavailable:
        unavailable[goods_no] = {
            "method": "manual",
            "reason": "상품 상세 제공 종료를 사람이 확인함",
            "confirmed_at": datetime.now().isoformat(timespec="seconds"),
        }
    if set(done) & set(unavailable):
        raise ValueError("A collected product cannot also be unavailable")
    remaining = [
        (label, no) for label, no in jobs if no not in done and no not in unavailable
    ]
    print(
        f"총 {len(jobs)}개 상품 수집 시작 "
        f"(작업자 {workers}, 기존 완료 {len(done)}, "
        f"판매 종료 확인 {len(unavailable)}, 남은 {len(remaining)})",
        flush=True,
    )
    failed = {}
    interrupted = False
    previous_sigint = None
    image_pool = (
        ThreadPoolExecutor(max_workers=oy.IMAGE_WORKERS) if kind == "makeup" else None
    )
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    base.collect if kind == "makeup" else collector.collect,
                    *(
                        (label, no, run_id, image_pool)
                        if kind == "makeup"
                        else (label, no, run_id)
                    ),
                ): (label, no)
                for label, no in remaining
            }

            def stop_collection(_signum, _frame):
                oy.STOP_EVENT.set()
                for pending in futures:
                    pending.cancel()
                raise KeyboardInterrupt

            previous_sigint = signal.signal(signal.SIGINT, stop_collection)
            with (directory / "_done.log").open("a", encoding="utf-8") as journal:
                for i, future in enumerate(as_completed(futures), len(done) + 1):
                    label, no = futures[future]
                    try:
                        rows = future.result()
                        if len(rows.get("product", [])) != 1:
                            raise ValueError(
                                "A product yielded zero or multiple product rows"
                            )
                        for table, items in rows.items():
                            base.emit(table, items)
                        journal.write(no + "\n")
                        journal.flush()
                        done.add(no)
                        goods_name = (
                            str(rows["product"][0].get("goods_name") or "")
                            .replace("\n", " ")
                            .replace("\r", " ")
                            .strip()
                        )
                        color_count = sum(
                            bool(color.get("hex_code"))
                            for color in rows.get("option_color", [])
                        )
                        color_log = f"HEX {color_count} / " if kind == "makeup" else ""
                        print(
                            f"   {i:04d}/{len(jobs)} [{label}] {no} {goods_name[:24]} → "
                            f"옵션 {len(rows.get('product_option', []))} / "
                            f"{color_log}성분 {len(rows.get('option_ingredient', []))} / "
                            f"이미지 {len(rows.get('image', []))}",
                            flush=True,
                        )
                    except oy.ProductUnavailable as exc:
                        unavailable[no] = {
                            "method": f"http_{exc.status_code}",
                            "reason": str(exc),
                            "confirmed_at": datetime.now().isoformat(
                                timespec="seconds"
                            ),
                        }
                        print(
                            f"   {i:04d}/{len(jobs)} [{label}] {no} 상세 페이지 없음: "
                            f"HTTP {exc.status_code}",
                            flush=True,
                        )
                    except Exception as exc:  # noqa: BLE001 - record per-product failures for resume
                        failed[no] = str(exc)[:300]
                        print(
                            f"   {i:04d}/{len(jobs)} [{label}] {no} 실패: {str(exc)[:90]}",
                            flush=True,
                        )
                        if isinstance(exc, oy.RateLimited) or oy.STOP_EVENT.is_set():
                            oy.STOP_EVENT.set()
                            for pending in futures:
                                pending.cancel()
                            print(f"중단: {exc}", flush=True)
                            break
    except KeyboardInterrupt:
        interrupted = True
        print("Ctrl+C: 남은 상품 작업을 취소하고 수집을 중단합니다.", flush=True)
    finally:
        if previous_sigint is not None:
            signal.signal(signal.SIGINT, previous_sigint)
        if image_pool:
            image_pool.shutdown(wait=True)
        for handle in base._files.values():
            handle.close()

    auto_unavailable = sum(
        record["method"].startswith("http_") for record in unavailable.values()
    )
    auto_limit = max(1, len(jobs) // 100)
    if auto_unavailable > auto_limit:
        print(
            f"자동 제외 {auto_unavailable}건이 목록의 1%를 초과해 완료 처리하지 않습니다. "
            "상세 주소 또는 응답 규칙을 검토하세요.",
            flush=True,
        )
    complete = (
        not interrupted
        and len(done) + len(unavailable) == len(jobs)
        and not failed
        and auto_unavailable <= auto_limit
        and not oy.STOP_EVENT.is_set()
    )
    _finish_run(run_csv, run_id, complete, collector.SCHEMA)
    manifest["complete"] = complete
    manifest["collected_count"] = len(done)
    manifest["unavailable"] = unavailable
    manifest["unavailable_count"] = len(unavailable)
    manifest["failed"] = failed
    manifest["finished_at"] = datetime.now().isoformat(timespec="seconds")
    _write_manifest(manifest_path, manifest)
    print(
        f"Collected {len(done)}/{len(jobs)}; unavailable={len(unavailable)}; "
        f"complete={complete}; snapshot={directory}"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("makeup", "skincare"), required=True)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--mode", choices=("full", "incremental"), default="full")
    parser.add_argument("--confirm-unavailable", action="append", default=[])
    args = parser.parse_args()
    result = collect(
        args.kind,
        args.snapshot_dir,
        args.workers,
        args.mode,
        args.confirm_unavailable,
    )
    if not result["complete"]:
        raise SystemExit(
            "Snapshot incomplete; rerun with the same folder after resolving failures"
        )


if __name__ == "__main__":
    main()
