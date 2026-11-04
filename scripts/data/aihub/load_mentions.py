"""추천·주의 성분 문자열을 ingredient_mention 에 적재한다. 미리보기가 기본.

측정 결과 한 문자열이 곧 한 성분이므로 쪼개지 않는다. 문자열 18,062개를 재어 보니
구분자 후보를 무엇으로 바꿔도 문자열당 토큰이 1.0 이었고, 쉼표는 633번, 줄바꿈은 1번만
나왔다. 쪼개는 규칙을 만들면 괄호 안 수식어(고농도 등)나 학명의 쉼표를 잘못 자른다.

entity_kind 는 확실한 것만 정하고 나머지는 unknown 으로 둔다.
  ingredient  식약처 현행 표준명과 정확히 일치
  unknown     그 밖의 모든 것

영문명, 학명, 성분군(레티노이드·계면활성제·파라벤 등), 수식어가 붙은 표기는 자동으로
판정하지 않는다. 식약처 매핑에 자동 연결하지도 않는다. mfds_ingredient_id 는 사람이
승인해야 채워지며 테이블 제약이 그것을 강제한다.

공용(원격) DB 에는 접속하지 않는다(docs/AIHUB_DATA_RIGHTS.md).
재실행해도 중복이 늘지 않는다. backend/api 에서 uv run python 으로 실행.
"""
import argparse, asyncio, collections, getpass, importlib.util, ipaddress, os, re, socket, sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[3]
MOD = ROOT / "scripts" / "data" / "oliveyoung" / "collectors" / "oliveyoung_erd_v30.py"
sys.path.insert(0, str(MOD.parent))
_spec = importlib.util.spec_from_file_location("oy_erd_v30", MOD)
oy = importlib.util.module_from_spec(_spec)
sys.modules["oy_erd_v30"] = oy
_spec.loader.exec_module(oy)
norm = oy.norm

HANGUL = re.compile(r"[가-힣]")
ASCII_WORD = re.compile(r"^[\x00-\x7F]+$")


def shape(text: str, mfds: set[str]) -> str:
    """판정하지 않고 모양만 분류한다. 보고용이며 entity_kind 가 아니다."""
    if norm(text) in mfds:
        return "식약처 표준명 일치"
    if not HANGUL.search(text) and ASCII_WORD.match(text.strip()):
        return "영문·학명만"
    if not HANGUL.search(text):
        return "비한글 혼합"
    if "(" in text or ")" in text:
        return "한글+괄호"
    if " " in text.strip():
        return "한글+공백"
    return "한글 단일어"


def assert_local(host: str) -> None:
    if host in ("localhost", "127.0.0.1", "::1"):
        return
    try:
        if ipaddress.ip_address(socket.gethostbyname(host)).is_loopback:
            return
    except OSError:
        pass
    raise SystemExit(f"로컬이 아닌 host 에는 연결하지 않습니다: {host}")


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=15432)
    p.add_argument("--database", default="vishue_db")
    p.add_argument("--user", default="vishue")
    p.add_argument("--apply", action="store_true", help="실제로 기록한다")
    a = p.parse_args()

    assert_local(a.host)
    pw = os.environ.get("POSTGRES_PASSWORD") or getpass.getpass("Local PostgreSQL password: ")
    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                user=a.user, password=pw, ssl=False)
    try:
        mfds = {
            n for n in (
                norm(r["name_ko"]) for r in await conn.fetch(
                    "SELECT name_ko FROM public.raw_mfds_ingredient WHERE is_current"
                )
            ) if n
        }
        rows = await conn.fetch(
            "SELECT seq, recommended_raw, avoid_raw FROM public.aihub_qa_case "
            "WHERE recommended_raw IS NOT NULL OR avoid_raw IS NOT NULL"
        )

        mentions = []
        kinds = collections.Counter()
        shapes = collections.Counter()
        by_type = collections.Counter()
        distinct = collections.Counter()
        for r in rows:
            for column, mention_type in (("recommended_raw", "recommended"),
                                         ("avoid_raw", "avoid")):
                text = (r[column] or "").strip()
                if not text:
                    continue
                kind = "ingredient" if norm(text) in mfds else "unknown"
                mentions.append((r["seq"], mention_type, text, kind))
                kinds[kind] += 1
                shapes[shape(text, mfds)] += 1
                by_type[mention_type] += 1
                distinct[norm(text)] += 1

        print(f"\n  성분 언급 {len(mentions):,}건")
        print(f"    추천 {by_type['recommended']:,} / 주의 {by_type['avoid']:,}")
        print(f"    고유 표기 {len(distinct):,}종")
        print("\n  entity_kind (확실한 것만 판정)")
        for k, c in kinds.most_common():
            print(f"    {k:<14}{c:>8,}  ({c / len(mentions) * 100:5.1f}%)")
        print("\n  표기 모양 (보고용. 판정 아님)")
        for k, c in shapes.most_common():
            print(f"    {k:<20}{c:>8,}  ({c / len(mentions) * 100:5.1f}%)")

        before = await conn.fetchval("SELECT COUNT(*) FROM public.aihub_ingredient_mention")
        print(f"\n  적재 전 ingredient_mention {before:>8,}행")
        if not a.apply:
            print("\n미리보기입니다. 기록하려면 --apply 를 붙이세요.")
            return

        async with conn.transaction():
            await conn.executemany(
                "INSERT INTO public.aihub_ingredient_mention "
                "(seq, mention_type, raw_text, entity_kind) VALUES ($1, $2, $3, $4) "
                "ON CONFLICT DO NOTHING",
                mentions,
            )
        after = await conn.fetchval("SELECT COUNT(*) FROM public.aihub_ingredient_mention")
        print(f"\n기록 완료. ingredient_mention {after:,}행")
        for r in await conn.fetch(
            "SELECT mention_type, entity_kind, COUNT(*) AS n "
            "FROM public.aihub_ingredient_mention GROUP BY mention_type, entity_kind "
            "ORDER BY mention_type, n DESC"
        ):
            print(f"  {r['mention_type']:<12}{r['entity_kind']:<14}{r['n']:>8,}")
        mapped = await conn.fetchval(
            "SELECT COUNT(*) FROM public.aihub_ingredient_mention"
            " WHERE mfds_ingredient_id IS NOT NULL"
        )
        print(f"  식약처 id 가 채워진 행 {mapped:,}  (사람 승인 전이므로 0 이어야 정상)")
    finally:
        await conn.close()


asyncio.run(main())
