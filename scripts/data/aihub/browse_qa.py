"""적재된 QA 를 사람이 읽을 수 있게 파일로 뽑는다. 읽기 전용.

이 데이터를 서비스 근거로 쓸 만한지 판단하려면 직접 읽어야 한다. 기본값은 고민 13종에서
2건씩 26건으로, 인수인계 문서의 표본 검증 26건과 같은 구성이라 결과를 비교할 수 있다.

출력은 UTF-8 파일이다. 콘솔에 한글 장문을 찍으면 깨지므로 에디터로 연다.
backend/api 에서 uv run python 으로 실행.
"""
import argparse, asyncio, getpass, ipaddress, os, socket, textwrap
from pathlib import Path

import asyncpg

CHECKLIST = """\
# 읽을 때 볼 것 (인수인계 문서의 표본 검증에서 실제로 나온 실패 유형)

1. 주제 불일치      답변·질문과 근거 문서의 주제가 다른가
                   예: 홍조 상담에 유방암 환자 열감 연구, 켈로이드에 여드름 연구
2. 권고 과잉 일반화  특정 약제를 무조건 피하라고 하는데 근거 문서의 적용 범위는 다른가
3. 근거 격차        피부 질환 연구가 '이 화장법·이 성분'을 직접 입증하는가
4. 값 의미 혼재     추천·주의 성분에 성분이 아닌 것이 섞였는가
                   예: 논코메도제닉은 제품 특성, 약제명이 회피 성분으로 기록
5. 답변 품질        실제 상담으로 쓸 만한 구체성인가, 템플릿처럼 반복되는가

판단 결과는 둘 중 하나다.
  - 쓸 만하다  -> 검수 등급 구조를 설계하고 근거 검토로 넘어간다
  - 못 쓰겠다  -> aihub.qa_case / qa_case_raw / qa_source_link 를 비우고 논문만 남긴다
"""

SQL = """
SELECT q.seq, q.concern_code, c.label_ko AS concern_label, c.major_category,
       q.skin_type_raw, t.display_label_ko AS skin_label, r.split,
       q.area_raw, q.concern_label_raw, q.skin_brightness_raw,
       q.question_text, q.answer_text, q.recommended_raw, q.avoid_raw
FROM aihub.qa_case q
JOIN aihub.qa_case_raw r ON r.seq = q.seq
JOIN aihub.skin_concern c ON c.concern_code = q.concern_code
LEFT JOIN aihub.skin_type t ON t.skin_type_raw = q.skin_type_raw
WHERE ($1::text IS NULL OR q.concern_code = $1)
  AND ($2::text IS NULL OR q.skin_type_raw = $2)
  AND ($3::text IS NULL OR r.split = $3)
ORDER BY q.concern_code, md5(q.seq || $4::text)
"""

SOURCE_SQL = """
SELECT source_position, source_title_raw, author_raw, publisher_raw,
       publication_year_raw, file_name_raw, status_raw, quote_raw, match_status
FROM aihub.qa_source_link
WHERE seq = $1
ORDER BY source_position
"""


def assert_local(host: str) -> None:
    if host in ("localhost", "127.0.0.1", "::1"):
        return
    try:
        if ipaddress.ip_address(socket.gethostbyname(host)).is_loopback:
            return
    except OSError:
        pass
    raise SystemExit(f"로컬이 아닌 host 에는 연결하지 않습니다: {host}")


def block(label: str, text: str | None, width: int = 96) -> str:
    if not text:
        return f"  {label}: (없음)\n"
    wrapped = textwrap.fill(text, width=width, initial_indent="    ",
                            subsequent_indent="    ", replace_whitespace=False)
    return f"  {label}:\n{wrapped}\n"


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=15432)
    p.add_argument("--database", default="vishue_v29")
    p.add_argument("--user", default="vishue")
    p.add_argument("--concern", help="고민 코드 01~13. 없으면 13종에서 고르게 뽑는다")
    p.add_argument("--skin-type", help="복합성 / 건성 / 지성 / 정상")
    p.add_argument("--split", choices=("train", "validation"))
    p.add_argument("--per-concern", type=int, default=2, help="고민별 건수 (기본 2)")
    p.add_argument("--limit", type=int, help="--concern 지정 시 총 건수")
    p.add_argument("--seed", default="1", help="같은 값이면 같은 표본이 나온다")
    p.add_argument("--out", type=Path, required=True, help="결과를 쓸 파일 (UTF-8)")
    a = p.parse_args()

    assert_local(a.host)
    pw = os.environ.get("POSTGRES_PASSWORD") or getpass.getpass("Local PostgreSQL password: ")
    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                user=a.user, password=pw, ssl=False)
    try:
        rows = await conn.fetch(SQL, a.concern, a.skin_type, a.split, a.seed)
        if not rows:
            raise SystemExit("조건에 맞는 QA 가 없습니다")
        picked, per_code = [], {}
        cap = a.limit if a.concern else None
        for r in rows:
            code = r["concern_code"]
            if a.concern is None and per_code.get(code, 0) >= a.per_concern:
                continue
            per_code[code] = per_code.get(code, 0) + 1
            picked.append(r)
            if cap and len(picked) >= cap:
                break

        sources = {}
        for r in picked:
            sources[r["seq"]] = await conn.fetch(SOURCE_SQL, r["seq"])

        total = await conn.fetchval("SELECT COUNT(*) FROM aihub.qa_case")
        a.out.parent.mkdir(parents=True, exist_ok=True)
        with a.out.open("w", encoding="utf-8") as fh:
            fh.write("# AI-Hub 질의응답 표본 (적재 판단용)\n\n")
            fh.write(f"전체 {total:,}건 중 {len(picked)}건을 뽑았습니다. ")
            fh.write(f"표본 기준: ")
            if a.concern:
                fh.write(f"고민 {a.concern} 에서 {len(picked)}건")
            else:
                fh.write(f"고민 13종에서 {a.per_concern}건씩")
            if a.skin_type:
                fh.write(f", 피부 타입 {a.skin_type}")
            if a.split:
                fh.write(f", {a.split}")
            fh.write(f" (seed={a.seed})\n\n")
            fh.write(CHECKLIST)
            fh.write("\n" + "=" * 100 + "\n")

            for i, r in enumerate(picked, 1):
                fh.write(f"\n## {i}. {r['seq']}\n\n")
                fh.write(f"  고민      {r['concern_code']} {r['major_category']} / "
                         f"{r['concern_label']}\n")
                fh.write(f"  원문 표기  {r['concern_label_raw'] or '(없음)'}\n")
                fh.write(f"  피부 타입  {r['skin_type_raw'] or '(없음)'}"
                         f" ({r['skin_label'] or '-'})"
                         f"   밝기 {r['skin_brightness_raw'] or '-'}\n")
                fh.write(f"  부위      {r['area_raw'] or '(없음)'}\n")
                fh.write(f"  분할      {r['split']}\n\n")
                fh.write(block("질문", r["question_text"]))
                fh.write("\n")
                fh.write(block("답변", r["answer_text"]))
                fh.write("\n")
                fh.write(block("추천 성분", r["recommended_raw"]))
                fh.write(block("주의 성분", r["avoid_raw"]))
                fh.write("\n  근거 출처:\n")
                srcs = sources[r["seq"]]
                if not srcs:
                    fh.write("    (없음)\n")
                for s in srcs:
                    fh.write(f"\n    [{s['source_position']}] {s['source_title_raw'] or '(제목 없음)'}\n")
                    fh.write(f"        저자 {s['author_raw'] or '-'} / "
                             f"기관 {s['publisher_raw'] or '-'} / "
                             f"연도 {s['publication_year_raw'] or '-'} / "
                             f"구분 {s['status_raw'] or '-'}\n")
                    fh.write(f"        파일 {s['file_name_raw'] or '-'} "
                             f"(연결 {s['match_status']})\n")
                    if s["quote_raw"]:
                        fh.write(textwrap.fill(s["quote_raw"], width=92,
                                               initial_indent="        인용: ",
                                               subsequent_indent="              ",
                                               replace_whitespace=False) + "\n")
                fh.write("\n" + "-" * 100 + "\n")
        print("wrote", a.out)
        print(f"  {len(picked)}건 (고민별: " +
              ", ".join(f"{k}:{v}" for k, v in sorted(per_code.items())) + ")")
    finally:
        await conn.close()


asyncio.run(main())
