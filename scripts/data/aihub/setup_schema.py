"""aihub 스키마와 테이블을 로컬 DB 에 만든다. 미리보기가 기본이며 --apply 로만 실행한다.

이 스크립트는 공용(원격) DB 에 접속하지 않는다. AI-Hub 원본은 국외 리전에 두지 않기로
결정했고(docs/AIHUB_DATA_RIGHTS.md), 스키마만 올려두면 나중에 누가 모르고 채울 수
있기 때문이다. 공용 반영이 허용되면 그때 이 제한을 명시적으로 푼다.

schema.sql 은 재실행해도 안전하다. 사전 2종(고민 13종, 피부 타입 4종)도 함께 넣는다.
backend/api 에서 uv run python 으로 실행.
"""
import argparse, asyncio, getpass, ipaddress, os, socket
from pathlib import Path

import asyncpg

HERE = Path(__file__).resolve().parent
SCHEMA_SQL = HERE / "schema.sql"

CONCERNS = [
    ("01", "염증성", "화농성 여드름", "pustular_acne"),
    ("02", "염증성", "면포성 여드름", "comedonal_acne"),
    ("03", "염증성", "지루성 피부염", "seborrheic_dermatitis"),
    ("04", "염증성", "주사 피부", "rosacea"),
    ("05", "민감성", "홍조", "facial_redness"),
    ("06", "민감성", "모세혈관 확장", "telangiectasia"),
    ("07", "민감성", "민감성 피부", "sensitive_skin"),
    ("08", "민감성", "아토피", "atopic_dermatitis"),
    ("09", "색소문제", "색소침착", "hyperpigmentation"),
    ("10", "색소문제", "기미·주근깨", "melasma_freckles"),
    ("11", "조직변화", "모공확장", "enlarged_pores"),
    ("12", "조직변화", "노화", "aging"),
    ("13", "조직변화", "켈로이드성", "keloid_prone"),
]
# 원본 값은 '정상' 이지만 서비스 표시명은 '중성' 이다. 둘을 분리해 저장한다.
SKIN_TYPES = [
    ("복합성", "combination", "복합성"),
    ("건성", "dry", "건성"),
    ("지성", "oily", "지성"),
    ("정상", "normal", "중성"),
]


def assert_local(host: str) -> None:
    """로컬이 아닌 곳에는 아예 연결하지 않는다."""
    if host in ("localhost", "127.0.0.1", "::1"):
        return
    try:
        resolved = socket.gethostbyname(host)
        if ipaddress.ip_address(resolved).is_loopback:
            return
    except OSError:
        pass
    raise SystemExit(
        f"로컬이 아닌 host 에는 연결하지 않습니다: {host}\n"
        "AI-Hub 원본은 국외 리전에 두지 않기로 결정했습니다(docs/AIHUB_DATA_RIGHTS.md).\n"
        "공용 반영이 허용되면 이 제한을 명시적으로 푼 뒤 사용하세요."
    )


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=15432)
    p.add_argument("--database", default="vishue_v29")
    p.add_argument("--user", default="vishue")
    p.add_argument("--apply", action="store_true", help="실제로 만든다")
    a = p.parse_args()

    assert_local(a.host)
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    print(f"스키마 파일: {SCHEMA_SQL}")
    print(f"  CREATE TABLE {sql.count('CREATE TABLE')}개, CREATE INDEX {sql.count('CREATE INDEX')}개")

    pw = os.environ.get("POSTGRES_PASSWORD") or getpass.getpass("Local PostgreSQL password: ")
    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                user=a.user, password=pw, ssl=False)
    try:
        exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'aihub')"
        )
        print(f"\naihub 스키마 존재: {'예' if exists else '아니오'}")
        if exists:
            rows = await conn.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'aihub' ORDER BY table_name"
            )
            for r in rows:
                n = await conn.fetchval(f'SELECT COUNT(*) FROM aihub."{r["table_name"]}"')
                print(f"  {r['table_name']:<28}{n:>8,}행")
        if not a.apply:
            print("\n미리보기입니다. 만들려면 --apply 를 붙이세요.")
            return

        async with conn.transaction():
            await conn.execute(sql)
            await conn.executemany(
                "INSERT INTO aihub.skin_concern (concern_code, major_category, label_ko, label_en) "
                "VALUES ($1, $2, $3, $4) ON CONFLICT (concern_code) DO UPDATE SET "
                "major_category = EXCLUDED.major_category, label_ko = EXCLUDED.label_ko, "
                "label_en = EXCLUDED.label_en",
                CONCERNS,
            )
            await conn.executemany(
                "INSERT INTO aihub.skin_type (skin_type_raw, skin_type_normalized, display_label_ko) "
                "VALUES ($1, $2, $3) ON CONFLICT (skin_type_raw) DO UPDATE SET "
                "skin_type_normalized = EXCLUDED.skin_type_normalized, "
                "display_label_ko = EXCLUDED.display_label_ko",
                SKIN_TYPES,
            )
        print("\n생성 완료")
        rows = await conn.fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'aihub' ORDER BY table_name"
        )
        for r in rows:
            n = await conn.fetchval(f'SELECT COUNT(*) FROM aihub."{r["table_name"]}"')
            print(f"  {r['table_name']:<28}{n:>8,}행")
    finally:
        await conn.close()


asyncio.run(main())
