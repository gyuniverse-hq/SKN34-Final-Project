"""추천 성분 코드를 수집 성분(raw_oy_ingredient)에 이름으로 연결한다.

전달본의 ingredient_id 는 구 수집본(out_skincare_v1, out_makeup_v23) 식별자이고 현재
raw_oy_ingredient 와 계보가 달라 쓸 수 없다. 495건을 전수 대조한 결과 일치가 0건이었다.
그래서 rec_ingredient_dictionary.name_ko 를 수집기와 같은 정규화로 맞춰 연결한다.

이름이 정확히 일치한 것만 exact_name 으로 기록한다. 표기 변형이나 성분군처럼 사람이
판단해야 하는 연결은 --manual-file 의 검수 파일로만 들어가며 검수자와 날짜를 남긴다.
미리보기가 기본이며 --apply 로만 기록한다. backend/api 에서 uv run python 으로 실행.
"""
import argparse, asyncio, csv, getpass, importlib.util, os, ssl, sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[3]
MOD = ROOT / "scripts" / "data" / "oliveyoung" / "collectors" / "oliveyoung_erd_v30.py"
sys.path.insert(0, str(MOD.parent))
_spec = importlib.util.spec_from_file_location("oy_erd_v30", MOD)
oy = importlib.util.module_from_spec(_spec)
sys.modules["oy_erd_v30"] = oy
_spec.loader.exec_module(oy)
norm = oy.norm  # 수집기와 동일한 정규화

MANUAL_COLUMNS = ("ingredient_code", "oy_ingredient_name", "link_method", "reviewed_by",
                  "reviewed_at", "note")
DEFAULT_MANUAL = Path(__file__).resolve().parent / "ingredient_links_manual.csv"


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


def read_manual(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    missing = set(MANUAL_COLUMNS) - set(rows[0].keys() if rows else MANUAL_COLUMNS)
    if missing:
        raise SystemExit(f"검수 파일 열이 부족합니다: {sorted(missing)}")
    for r in rows:
        if r["link_method"] not in ("manual", "group_member"):
            raise SystemExit(f"검수 파일의 link_method 는 manual 또는 group_member 여야 합니다: {r}")
        if not (r["reviewed_by"] and r["reviewed_at"]):
            raise SystemExit(f"검수자와 날짜가 비어 있습니다: {r}")
        try:
            # asyncpg 는 date 컬럼에 문자열을 받지 않는다.
            r["reviewed_at"] = date.fromisoformat(r["reviewed_at"].strip())
        except ValueError:
            raise SystemExit(f"reviewed_at 는 YYYY-MM-DD 형식이어야 합니다: {r['reviewed_at']!r}")
    return rows


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--target", choices=("local", "shared"), default="local")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=15432)
    p.add_argument("--database", default="vishue_v29")
    p.add_argument("--user", default="vishue")
    p.add_argument("--ssl-ca-file")
    p.add_argument("--manual-file", type=Path, default=DEFAULT_MANUAL)
    p.add_argument("--apply", action="store_true", help="실제로 기록한다")
    p.add_argument("--execute-shared", action="store_true")
    a = p.parse_args()

    manual = read_manual(a.manual_file)
    conn = await connect(a)
    try:
        codes = await conn.fetch(
            "SELECT ingredient_code, name_ko, source_match_status "
            "FROM public.rec_ingredient_dictionary ORDER BY ingredient_code"
        )
        if not codes:
            raise SystemExit("rec_ingredient_dictionary 가 비어 있습니다. load_mapping.py 를 먼저 실행하세요.")
        by_norm = defaultdict(list)
        for r in await conn.fetch(
            "SELECT ingredient_id, ingredient_name FROM public.raw_oy_ingredient"
        ):
            by_norm[norm(r["ingredient_name"])].append((r["ingredient_id"], r["ingredient_name"]))
        existing = {
            (r["ingredient_code"], r["oy_ingredient_id"])
            for r in await conn.fetch(
                "SELECT ingredient_code, oy_ingredient_id FROM public.rec_ingredient_link"
            )
        }

        planned: list[tuple] = []
        unmatched: list[tuple[str, str, str]] = []
        for r in codes:
            hits = by_norm.get(norm(r["name_ko"]), [])
            if not hits:
                unmatched.append((r["ingredient_code"], r["name_ko"], r["source_match_status"] or ""))
                continue
            for iid, nm in hits:
                planned.append((r["ingredient_code"], iid, "exact_name", None, None,
                                f"이름 일치: {nm}"))

        manual_planned: list[tuple] = []
        for r in manual:
            hits = by_norm.get(norm(r["oy_ingredient_name"]), [])
            if not hits:
                print(f"  [경고] 검수 파일의 성분명을 DB에서 찾지 못했습니다: {r['oy_ingredient_name']!r}")
                continue
            for iid, nm in hits:
                manual_planned.append((r["ingredient_code"], iid, r["link_method"],
                                       r["reviewed_by"], r["reviewed_at"], r["note"] or None))

        print(f"\n성분 코드 {len(codes)}개")
        print(f"  이름 일치로 연결 가능   {len({c for c, *_ in planned})}개  (연결 {len(planned)}건)")
        print(f"  검수 파일로 연결        {len({c for c, *_ in manual_planned})}개  (연결 {len(manual_planned)}건)")
        print(f"  연결 안 됨              {len(unmatched)}개")
        if unmatched:
            print("\n  사람 판단이 필요한 코드:")
            for code, nm, status in unmatched:
                print(f"    {code:<22} {nm:<18} {status}")

        new = [row for row in planned + manual_planned if (row[0], row[1]) not in existing]
        print(f"\n새로 기록할 연결: {len(new)}건 (이미 있는 것 {len(planned) + len(manual_planned) - len(new)}건 건너뜀)")
        if not a.apply:
            print("\n미리보기입니다. 기록하려면 --apply 를 붙이세요.")
            return
        async with conn.transaction():
            await conn.executemany(
                "INSERT INTO public.rec_ingredient_link "
                "(ingredient_code, oy_ingredient_id, link_method, reviewed_by, reviewed_at, note) "
                "VALUES ($1, $2, $3, $4, $5, $6) "
                "ON CONFLICT (ingredient_code, oy_ingredient_id) DO NOTHING",
                new,
            )
        total = await conn.fetchval("SELECT COUNT(*) FROM public.rec_ingredient_link")
        print(f"\n기록 완료. rec_ingredient_link 총 {total:,}행")
    finally:
        await conn.close()


asyncio.run(main())
