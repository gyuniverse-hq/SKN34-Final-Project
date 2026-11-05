"""팀원 추천매핑 전달본의 성분 ID가 현재 운영 DB와 같은 계보인지 검증한다. 읽기 전용.

전달본 ingredient_id_bridge.csv 의 ingredient_id 는 out_skincare_v1 / out_makeup_v23
수집본 CSV 식별자다. 현재 DB(raw_oy_ingredient)와 같은 번호 체계인지 이름으로 대조한다.
동시에 이름 기반 연결이 가능한지도 함께 집계한다.
backend/api 에서 uv run python 으로 실행.
"""
import argparse, asyncio, csv, getpass, importlib.util, os, ssl, sys
from collections import Counter, defaultdict
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[3]  # 저장소 루트
MOD = ROOT / "scripts" / "data" / "oliveyoung" / "collectors" / "oliveyoung_erd_v30.py"
sys.path.insert(0, str(MOD.parent))
_spec = importlib.util.spec_from_file_location("oy_erd_v30", MOD)
oy = importlib.util.module_from_spec(_spec)
sys.modules["oy_erd_v30"] = oy
_spec.loader.exec_module(oy)
norm = oy.norm

DEFAULT_DIR = Path.home() / "Downloads" / "VISHUE_DB_추천매핑_요구사항정합_v1_2_1"


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="전달본 폴더")
    p.add_argument("--target", choices=("local", "shared"), default="local")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=15432)
    p.add_argument("--database", default="vishue_db")
    p.add_argument("--user", default="vishue")
    p.add_argument("--ssl-ca-file")
    p.add_argument("--out", default=str(ROOT / "data" / "mapping-bridge-check.txt"),
                   help="결과를 쓸 파일. 기본값은 gitignore 되는 data/ 안")
    a = p.parse_args()

    if not a.dir.is_dir():
        raise SystemExit(f"전달본 폴더를 찾을 수 없습니다: {a.dir}")
    dic = read_csv(a.dir / "ingredient_dictionary.csv")
    bridge = read_csv(a.dir / "ingredient_id_bridge.csv")

    sslc: ssl.SSLContext | bool = False
    if a.target == "shared":
        sslc = ssl.create_default_context(cafile=a.ssl_ca_file or None)
        pw = getpass.getpass("Shared PostgreSQL password: ")
    else:
        pw = os.environ.get("POSTGRES_PASSWORD") or getpass.getpass("Local PostgreSQL password: ")
    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                user=a.user, password=pw, ssl=sslc)
    try:
        db_by_id = {
            r["ingredient_id"]: r["ingredient_name"]
            for r in await conn.fetch(
                "SELECT ingredient_id, ingredient_name FROM public.raw_oy_ingredient"
            )
        }
        db_by_norm = defaultdict(list)
        for iid, nm in db_by_id.items():
            db_by_norm[norm(nm)].append((iid, nm))
        # 이름별 사용량 (몇 개 상품에 들어 있나)
        usage = {
            r["ingredient_id"]: r["product_count"]
            for r in await conn.fetch(
                "SELECT oi.ingredient_id, COUNT(DISTINCT po.goods_no) AS product_count "
                "FROM public.raw_oy_option_ingredient oi "
                "JOIN public.raw_oy_product_option po ON po.option_id = oi.option_id "
                "GROUP BY oi.ingredient_id"
            )
        }
        # 앱 서빙 카탈로그에 들어간 상품만으로 다시 센다.
        usage_cat = {
            r["ingredient_id"]: r["product_count"]
            for r in await conn.fetch(
                "SELECT oi.ingredient_id, COUNT(DISTINCT po.goods_no) AS product_count "
                "FROM public.raw_oy_option_ingredient oi "
                "JOIN public.raw_oy_product_option po ON po.option_id = oi.option_id "
                "JOIN public.raw_oy_product pr ON pr.goods_no = po.goods_no "
                "WHERE pr.is_in_catalog "
                "GROUP BY oi.ingredient_id"
            )
        }
        mapped_ids = {
            r["oy_ingredient_id"]
            for r in await conn.fetch(
                "SELECT oy_ingredient_id FROM public.oy_mfds_ingredient_map"
            )
        }
    finally:
        await conn.close()

    name_by_code = {r["ingredient_code"]: r["name_ko"] for r in dic}

    # 1) ID 계보 검증
    verdict = Counter()
    examples = []
    for r in bridge:
        code, bid = r["ingredient_code"], r["ingredient_id"]
        want = norm(name_by_code.get(code, ""))
        got_name = db_by_id.get(int(bid)) if bid.isdigit() else None
        if got_name is None:
            verdict["DB에 그 ID 없음"] += 1
            continue
        if norm(got_name) == want:
            verdict["이름 일치"] += 1
        else:
            verdict["이름 불일치"] += 1
            if len(examples) < 15:
                examples.append((code, bid, name_by_code.get(code, ""), got_name))

    # 2) 이름 기반 연결 가능성
    rows = []
    for r in dic:
        code, nm = r["ingredient_code"], r["name_ko"]
        hits = db_by_norm.get(norm(nm), [])
        prod = sum(usage.get(i, 0) for i, _ in hits)
        prod_cat = sum(usage_cat.get(i, 0) for i, _ in hits)
        std = sum(1 for i, _ in hits if i in mapped_ids)
        rows.append((code, nm, r["ingredient_id_count"], len(hits), prod, prod_cat, std))

    out = Path(a.out)
    with out.open("w", encoding="utf-8") as fh:
        w = lambda s="": fh.write(s + "\n")
        w(f"전달본: {a.dir}")
        w(f"대상 DB: {a.target}   raw_oy_ingredient {len(db_by_id):,}종")
        w("\n== 1) 전달본 ingredient_id 가 현재 DB와 같은 계보인가 ==")
        w(f"   bridge 행 {len(bridge):,}건을 ID로 조회해 이름을 비교")
        for k, c in verdict.most_common():
            w(f"   {c:>5,}  {k}")
        if examples:
            w("\n   불일치 예시 (전달본이 말하는 성분 -> 그 ID로 DB에서 나온 성분)")
            for code, bid, want, got in examples:
                w(f"     id {bid:>6}  {code:<20} {want!r:<22} -> {got!r}")
        w("\n== 2) 이름으로 연결하면 어떻게 되나 ==")
        w(f"   {'코드':<22}{'이름':<18}{'전달본ID':>8}{'DB일치':>7}{'전체상품':>9}{'카탈로그':>9}{'식약처':>7}")
        for code, nm, cnt, hits, prod, prod_cat, std in rows:
            w(f"   {code:<22}{nm:<18}{cnt:>8}{hits:>7}{prod:>9}{prod_cat:>9}{std:>7}")
        found = sum(1 for r in rows if r[3])
        in_cat = sum(1 for r in rows if r[5])
        w(f"\n   이름으로 찾은 코드: {found}/{len(rows)}")
        w(f"   카탈로그 상품에 실제로 들어 있는 코드: {in_cat}/{len(rows)}")
    print("wrote", out)


asyncio.run(main())
