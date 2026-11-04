"""추천 매핑 전달본을 rec_* 테이블에 적재한다. 미리보기가 기본이며 --apply 로만 기록한다.

전달본 7개 파일 중 6개를 적재한다. ingredient_id_bridge.csv 는 구 수집본 ID 라서
적재하지 않는다(현재 raw_oy_ingredient 와 전수 대조 결과 일치 0건). 성분 코드와 수집
성분의 연결은 link_ingredients.py 가 이름을 근거로 rec_ingredient_link 에 만든다.

등급 컬럼(mapping_status, human_mapping_review, ai_paper_review, re_review_required,
runtime_enabled)은 거르지 않고 그대로 넣는다. 소비하는 쪽이 판단한다.

이 스크립트는 전달본 6개 테이블만 upsert 하며, 이 저장소가 계산한 rec_ingredient_link
와 rec_concern_match 는 건드리지 않는다.
backend/api 에서 uv run python 으로 실행.
"""
import argparse, asyncio, csv, getpass, os, ssl
from pathlib import Path

import asyncpg

DEFAULT_DIR = Path.home() / "Downloads" / "VISHUE_DB_추천매핑_요구사항정합_v1_2_1"

MAPPING_STATUSES = {
    "candidate_after_match", "research_only", "support_only", "formula_evidence_only",
    "excluded_treatment_scope", "excluded_wrong_endpoint", "excluded_context_mismatch",
}


def read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        raise SystemExit(f"파일이 없습니다: {path}")
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def flag(value: str) -> bool:
    """'1'/'0' 표기를 참/거짓으로 바꾼다."""
    v = (value or "").strip().lower()
    if v in ("1", "true", "y", "yes"):
        return True
    if v in ("0", "", "false", "n", "no"):
        return False
    raise SystemExit(f"참/거짓으로 읽을 수 없는 값: {value!r}")


def check_integrity(src: dict[str, list[dict]]) -> None:
    """적재 전에 전달본 안의 참조가 모두 맞는지 확인한다."""
    concerns = {r["target_concern"] for r in src["reason"]}
    evidences = {r["evidence_id"] for r in src["evidence"]}
    codes = {r["ingredient_code"] for r in src["dictionary"]}
    mappings = {r["mapping_id"] for r in src["mapping"]}
    problems = []
    for r in src["mapping"]:
        if r["target_concern"] not in concerns:
            problems.append(f"{r['mapping_id']}: 없는 target_concern {r['target_concern']}")
        if r["evidence_id"] and r["evidence_id"] not in evidences:
            problems.append(f"{r['mapping_id']}: 없는 evidence_id {r['evidence_id']}")
        if r["mapping_status"] not in MAPPING_STATUSES:
            problems.append(f"{r['mapping_id']}: 모르는 mapping_status {r['mapping_status']}")
        if r["mapping_type"] not in ("single", "combination"):
            problems.append(f"{r['mapping_id']}: 모르는 mapping_type {r['mapping_type']}")
    for r in src["mapping_ingredients"]:
        if r["mapping_id"] not in mappings:
            problems.append(f"구성 성분 행: 없는 mapping_id {r['mapping_id']}")
        if r["ingredient_code"] not in codes:
            problems.append(f"구성 성분 행: 없는 ingredient_code {r['ingredient_code']}")
    for r in src["manual"]:
        if r["ingredient_code"] not in codes:
            problems.append(f"보류 후보: 없는 ingredient_code {r['ingredient_code']}")
    if problems:
        print("전달본 참조 오류:")
        for p in problems[:20]:
            print("  -", p)
        raise SystemExit(f"참조 오류 {len(problems)}건. 적재를 중단합니다.")


async def connect(a):
    sslc: ssl.SSLContext | bool = False
    if a.target == "shared":
        if not a.ssl_ca_file:
            raise SystemExit("--ssl-ca-file 이 필요합니다")
        if a.apply and not a.execute_shared:
            raise SystemExit("공용 DB 기록에는 --apply 와 --execute-shared 가 모두 필요합니다")
        sslc = ssl.create_default_context(cafile=a.ssl_ca_file)
        pw = getpass.getpass("Shared PostgreSQL password: ")
    else:
        pw = os.environ.get("POSTGRES_PASSWORD") or getpass.getpass("Local PostgreSQL password: ")
    return await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                user=a.user, password=pw, ssl=sslc)


async def upsert(conn, table: str, keys: tuple[str, ...], columns: tuple[str, ...], rows: list[tuple]):
    """기본키가 같으면 갱신한다. 삭제는 하지 않는다."""
    if not rows:
        return 0
    placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c not in keys)
    sql = (
        f"INSERT INTO public.{table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {updates}"
        if updates
        else f"INSERT INTO public.{table} ({', '.join(columns)}) VALUES ({placeholders}) "
             f"ON CONFLICT ({', '.join(keys)}) DO NOTHING"
    )
    await conn.executemany(sql, rows)
    return len(rows)


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="전달본 폴더")
    p.add_argument("--target", choices=("local", "shared"), default="local")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=15432)
    p.add_argument("--database", default="vishue_db")
    p.add_argument("--user", default="vishue")
    p.add_argument("--ssl-ca-file")
    p.add_argument("--apply", action="store_true", help="실제로 기록한다")
    p.add_argument("--execute-shared", action="store_true")
    a = p.parse_args()

    src = {
        "reason": read_csv(a.dir / "recommendation_reason.csv"),
        "evidence": read_csv(a.dir / "evidence_sources.csv"),
        "dictionary": read_csv(a.dir / "ingredient_dictionary.csv"),
        "mapping": read_csv(a.dir / "recommendation_mapping.csv"),
        "mapping_ingredients": read_csv(a.dir / "mapping_ingredients.csv"),
        "manual": read_csv(a.dir / "manual_review_candidates.csv"),
    }
    print(f"전달본: {a.dir}")
    for k, v in src.items():
        print(f"  {k:<20} {len(v):>4}행")
    check_integrity(src)
    print("전달본 참조 정합성 통과")

    plan = [
        ("rec_concern", ("target_concern",),
         ("target_concern", "display_label", "recommendation_reason"),
         [(r["target_concern"], r["display_label"], r["recommendation_reason"])
          for r in src["reason"]]),
        ("rec_evidence", ("evidence_id",),
         ("evidence_id", "pmid", "title", "source_url", "ai_paper_review", "study_limit"),
         [(r["evidence_id"], r["pmid"] or None, r["title"] or None, r["source_url"] or None,
           r["ai_paper_review"] or None, r["study_limit"] or None) for r in src["evidence"]]),
        ("rec_ingredient_dictionary", ("ingredient_code",),
         ("ingredient_code", "name_ko", "inci_name", "source_match_status"),
         [(r["ingredient_code"], r["name_ko"], r["inci_name"] or None,
           r["source_match_status"] or None) for r in src["dictionary"]]),
        ("rec_mapping", ("mapping_id",),
         ("mapping_id", "mapping_type", "target_concern", "ingredient_codes", "evidence_id",
          "mapping_status", "human_mapping_review", "ai_paper_review", "re_review_required",
          "runtime_enabled", "requirements_scope"),
         [(r["mapping_id"], r["mapping_type"], r["target_concern"], r["ingredient_codes"] or None,
           r["evidence_id"] or None, r["mapping_status"], r["human_mapping_review"] or None,
           r["ai_paper_review"] or None, flag(r["re_review_required"]),
           flag(r["runtime_enabled"]), r["requirements_scope"] or None) for r in src["mapping"]]),
        ("rec_mapping_ingredient", ("mapping_id", "ingredient_code"),
         ("mapping_id", "ingredient_code", "component_order"),
         [(r["mapping_id"], r["ingredient_code"], int(r["component_order"]))
          for r in src["mapping_ingredients"]]),
        ("rec_manual_review_candidate", ("ingredient_code", "source_name"),
         ("ingredient_code", "source_name", "source_ingredient_id", "review_reason", "approved"),
         [(r["ingredient_code"], r["source_name"],
           int(r["ingredient_id"]) if r["ingredient_id"].strip().isdigit() else None,
           r["review_reason"] or None, flag(r["approved"])) for r in src["manual"]]),
    ]

    enabled = [r for r in src["mapping"] if flag(r["runtime_enabled"])]
    print(f"\nruntime_enabled 가 참인 매핑: {len(enabled)}건 (전달본은 0건이어야 정상)")

    conn = await connect(a)
    try:
        print("\n== 적재 전 행 수 ==")
        for table, *_ in plan:
            n = await conn.fetchval(f"SELECT COUNT(*) FROM public.{table}")
            print(f"  {table:<30} {n:>5,}")
        if not a.apply:
            print("\n미리보기입니다. 기록하려면 --apply 를 붙이세요.")
            return
        async with conn.transaction():
            for table, keys, columns, rows in plan:
                n = await upsert(conn, table, keys, columns, rows)
                print(f"  {table:<30} {n:>5,}행 upsert")
        print("\n== 적재 후 행 수 ==")
        for table, *_ in plan:
            n = await conn.fetchval(f"SELECT COUNT(*) FROM public.{table}")
            print(f"  {table:<30} {n:>5,}")
    finally:
        await conn.close()


asyncio.run(main())
