"""QA 의 출처 참조를 실제 지식 문서에 연결한다. 미리보기가 기본이며 --apply 로만 기록한다.

출처 한 자리에 파일명이 둘이다. _1 은 .doc 원문, _2 는 같은 이름의 .json 메타다.
연결은 _1(.doc) 로만 한다. _2 로 연결하면 메타와 원문이 다른 문서를 가리키는 경우에
근거 없는 연결이 생긴다. _2 로만 붙는 건수는 보고만 하고 자동으로 붙이지 않는다.

같은 파일명이 여러 경로에 있어도 모두 같은 문서를 가리키면(중복 사본) 모호하지 않다.
서로 다른 문서를 가리키면 ambiguous 로 남기고 연결하지 않는다.

공용(원격) DB 에는 접속하지 않는다(docs/AIHUB_DATA_RIGHTS.md).
backend/api 에서 uv run python 으로 실행.
"""
import argparse, asyncio, collections, getpass, ipaddress, os, socket
from pathlib import PurePosixPath

import asyncpg


def assert_local(host: str) -> None:
    if host in ("localhost", "127.0.0.1", "::1"):
        return
    try:
        if ipaddress.ip_address(socket.gethostbyname(host)).is_loopback:
            return
    except OSError:
        pass
    raise SystemExit(f"로컬이 아닌 host 에는 연결하지 않습니다: {host}")


def key(name: str | None) -> str | None:
    """확장자를 떼고 소문자로 맞춘 파일명."""
    if not name:
        return None
    return PurePosixPath(name.strip()).stem.lower()


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
        # 파일명 -> 그 이름을 가진 파일들이 가리키는 문서 id 집합
        by_key: dict[str, set[int]] = collections.defaultdict(set)
        for r in await conn.fetch(
            "SELECT file_name, document_id FROM public.aihub_knowledge_document_file "
            "WHERE document_id IS NOT NULL"
        ):
            k = key(r["file_name"])
            if k:
                by_key[k].add(r["document_id"])

        links = await conn.fetch(
            "SELECT seq, source_position, file_name_raw, file_name_raw_2, match_status "
            "FROM public.aihub_qa_source_link ORDER BY seq, source_position"
        )
        print(f"  출처 참조 {len(links):,}행")
        filled_2 = sum(1 for r in links if r["file_name_raw_2"])
        differ = sum(
            1 for r in links
            if r["file_name_raw"] and r["file_name_raw_2"]
            and key(r["file_name_raw"]) != key(r["file_name_raw_2"])
        )
        print(f"  두 번째 파일명이 채워진 행 {filled_2:,}")
        print(f"  _1 과 _2 가 다른 행        {differ:,}")

        verdict = collections.Counter()
        updates: list[tuple] = []
        only_via_2 = 0
        for r in links:
            docs = by_key.get(key(r["file_name_raw"]) or "", set())
            if len(docs) == 1:
                verdict["matched"] += 1
                updates.append(("matched", next(iter(docs)), r["seq"], r["source_position"]))
            elif len(docs) > 1:
                verdict["ambiguous"] += 1
                updates.append(("ambiguous", None, r["seq"], r["source_position"]))
            else:
                verdict["unmatched"] += 1
                updates.append(("unmatched", None, r["seq"], r["source_position"]))
                # _2 로는 붙지만 _1 로는 안 붙는 경우. 보고만 한다.
                if len(by_key.get(key(r["file_name_raw_2"]) or "", set())) == 1:
                    only_via_2 += 1

        print("\n  연결 판정 (_1 = .doc 기준)")
        for k in ("matched", "unmatched", "ambiguous"):
            share = verdict[k] / len(links) * 100 if links else 0
            print(f"    {k:<12}{verdict[k]:>7,}  ({share:5.1f}%)")
        if only_via_2:
            print(f"\n  _1 로는 안 붙지만 _2 로는 붙는 행 {only_via_2:,}건")
            print("    메타와 원문이 다른 문서를 가리키는 경우입니다. 자동 연결하지 않습니다.")

        if not a.apply:
            print("\n미리보기입니다. 기록하려면 --apply 를 붙이세요.")
            return

        async with conn.transaction():
            await conn.executemany(
                "UPDATE public.aihub_qa_source_link SET match_status = $1, document_id = $2 "
                "WHERE seq = $3 AND source_position = $4",
                updates,
            )
        print("\n기록 완료")
        rows = await conn.fetch(
            "SELECT match_status, COUNT(*) AS n, COUNT(document_id) AS linked "
            "FROM public.aihub_qa_source_link GROUP BY match_status ORDER BY n DESC"
        )
        for r in rows:
            print(f"  {r['match_status']:<14}{r['n']:>7,}  (문서 연결 {r['linked']:,})")
        reached = await conn.fetchval(
            "SELECT COUNT(DISTINCT document_id) FROM public.aihub_qa_source_link "
            "WHERE document_id IS NOT NULL"
        )
        total_docs = await conn.fetchval("SELECT COUNT(*) FROM public.aihub_knowledge_document")
        qa_with = await conn.fetchval(
            "SELECT COUNT(DISTINCT seq) FROM public.aihub_qa_source_link"
            " WHERE match_status = 'matched'"
        )
        qa_total = await conn.fetchval("SELECT COUNT(*) FROM public.aihub_qa_case")
        print(f"\n  QA 가 가리키는 문서   {reached:>7,} / {total_docs:,}")
        print(f"  근거가 연결된 QA      {qa_with:>7,} / {qa_total:,}")
    finally:
        await conn.close()


asyncio.run(main())
