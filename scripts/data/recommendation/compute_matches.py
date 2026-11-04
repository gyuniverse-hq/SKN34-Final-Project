"""매핑의 성분 구성을 모두 갖춘 상품 옵션을 계산해 rec_concern_match 에 기록한다.

조합 매핑은 한 옵션에 구성 성분이 모두 있어야 일치한다(부분 일치 보너스 없음).
성분은 옵션 단위로 달려 있어(색조는 호수별로 다름) 옵션 기준으로 계산하고,
상품 단위 노출은 옵션 중 하나라도 일치하는지로 판단한다.

카탈로그 안팎을 가리지 않고 모든 옵션을 계산한다. 카탈로그가 바뀌어도 다시 계산할
필요가 없고, 소비하는 쪽이 is_in_catalog 로 거를 수 있다. 보고에는 두 수를 다 찍는다.

연결되지 않은 성분 코드를 쓰는 매핑은 계산하지 않고 사유와 함께 건너뛴다. 일부만
연결된 상태로 계산하면 조합이 실제보다 느슨하게 일치한다.

파생 테이블이므로 --apply 는 전체를 다시 계산한다(기존 행 삭제 후 삽입).
미리보기가 기본. backend/api 에서 uv run python 으로 실행.
"""
import argparse, asyncio, getpass, os, ssl
from collections import defaultdict

import asyncpg

# 옵션이 요구 성분 코드를 '전부' 가졌는지. 코드별로 중복 성분이 있어도
# COUNT(DISTINCT ingredient_code) 로 세므로 한 번만 센다.
MATCH_SQL = """
SELECT oi.option_id
FROM public.raw_oy_option_ingredient oi
JOIN public.rec_ingredient_link l ON l.oy_ingredient_id = oi.ingredient_id
WHERE l.ingredient_code = ANY($1::text[])
GROUP BY oi.option_id
HAVING COUNT(DISTINCT l.ingredient_code) = $2
"""

COUNT_SQL = """
WITH matched AS (
""" + MATCH_SQL + """
)
SELECT COUNT(*) AS options,
       COUNT(DISTINCT po.goods_no) AS products,
       COUNT(DISTINCT CASE WHEN pr.is_in_catalog THEN po.goods_no END) AS catalog_products
FROM matched m
JOIN public.raw_oy_product_option po ON po.option_id = m.option_id
LEFT JOIN public.raw_oy_product pr ON pr.goods_no = po.goods_no
"""


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


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--target", choices=("local", "shared"), default="local")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=15432)
    p.add_argument("--database", default="vishue_db")
    p.add_argument("--user", default="vishue")
    p.add_argument("--ssl-ca-file")
    p.add_argument("--apply", action="store_true", help="실제로 다시 계산해 기록한다")
    p.add_argument("--execute-shared", action="store_true")
    a = p.parse_args()

    conn = await connect(a)
    try:
        mappings = await conn.fetch(
            "SELECT mapping_id, mapping_type, target_concern, mapping_status, "
            "re_review_required, runtime_enabled "
            "FROM public.rec_mapping ORDER BY mapping_id"
        )
        if not mappings:
            raise SystemExit("rec_mapping 이 비어 있습니다. load_mapping.py 를 먼저 실행하세요.")
        components = defaultdict(list)
        for r in await conn.fetch(
            "SELECT mapping_id, ingredient_code FROM public.rec_mapping_ingredient "
            "ORDER BY mapping_id, component_order"
        ):
            components[r["mapping_id"]].append(r["ingredient_code"])
        linked = {
            r["ingredient_code"]
            for r in await conn.fetch(
                "SELECT DISTINCT ingredient_code FROM public.rec_ingredient_link"
            )
        }

        computable, skipped = [], []
        for m in mappings:
            codes = components[m["mapping_id"]]
            missing = [c for c in codes if c not in linked]
            if not codes:
                skipped.append((m, "구성 성분이 없음"))
            elif missing:
                skipped.append((m, "연결 안 된 성분: " + ", ".join(missing)))
            else:
                computable.append((m, codes))

        print(f"\n매핑 {len(mappings)}건 중 계산 가능 {len(computable)}건, 건너뜀 {len(skipped)}건")

        print("\n== 계산 가능 ==")
        header = f"  {'매핑':<6}{'유형':<12}{'고민':<14}{'성분':<3}{'옵션':>8}{'상품':>8}{'카탈로그':>9}  등급"
        print(header)
        total_rows = 0
        results = []
        for m, codes in computable:
            row = await conn.fetchrow(COUNT_SQL, codes, len(codes))
            total_rows += row["options"]
            results.append((m, codes, row))
            flags = m["mapping_status"]
            if m["re_review_required"]:
                flags += " /재검수"
            print(f"  {m['mapping_id']:<6}{m['mapping_type']:<12}{m['target_concern']:<14}"
                  f"{len(codes):<3}{row['options']:>8,}{row['products']:>8,}"
                  f"{row['catalog_products']:>9,}  {flags}")

        if skipped:
            print("\n== 건너뜀 ==")
            for m, reason in skipped:
                print(f"  {m['mapping_id']:<6}{m['mapping_type']:<12}{m['target_concern']:<14}{reason}")

        print(f"\n기록할 행 수 합계: {total_rows:,}")
        if not a.apply:
            print("\n미리보기입니다. 기록하려면 --apply 를 붙이세요.")
            return

        async with conn.transaction():
            # 파생 테이블이므로 전체를 다시 계산한다.
            deleted = await conn.execute("DELETE FROM public.rec_concern_match")
            print(f"\n기존 행 삭제: {deleted}")
            for m, codes, _ in results:
                await conn.execute(
                    "INSERT INTO public.rec_concern_match (mapping_id, option_id) "
                    "SELECT $3, option_id FROM (" + MATCH_SQL + ") s "
                    "ON CONFLICT (mapping_id, option_id) DO NOTHING",
                    codes, len(codes), m["mapping_id"],
                )
        total = await conn.fetchval("SELECT COUNT(*) FROM public.rec_concern_match")
        print(f"기록 완료. rec_concern_match 총 {total:,}행")
    finally:
        await conn.close()


asyncio.run(main())
