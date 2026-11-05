"""적재된 QA 를 두 가지로 측정한다. 읽기 전용, 기록하지 않는다.

A. 대상자 ID 누출  학습·검증이 같은 대상자를 공유하는지, 질문·답변이 교차 중복하는지.
                 요청서 체크리스트의 '대상자 ID 단위 재분리 및 유사도 누출 위험 보고'.

B. 성분 문자열 구분자  추천·주의 성분 원문을 어떤 문자로 쪼개야 하는지 측정한다.
                     추측으로 쪼개면 성분이 아닌 값이 성분으로 들어간다. 후보 구분자마다
                     쪼갠 뒤 식약처 표준명과 일치하는 비율을 비교해 규칙을 고른다.

집계는 --out 에, 사람이 읽을 예시는 --samples-out 에 따로 쓴다. 원문 내용은 집계
파일에 넣지 않는다.
backend/api 에서 uv run python 으로 실행.
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

# 쪼개는 문자 후보. 단독과 조합을 모두 재본다.
CANDIDATES = {
    "쉼표": r",",
    "쉼표+줄바꿈": r"[,\n]",
    "쉼표+가운뎃점": r"[,·ㆍ]",
    "쉼표+슬래시": r"[,/]",
    "쉼표+줄바꿈+가운뎃점": r"[,\n·ㆍ]",
    "쉼표+줄바꿈+가운뎃점+세미콜론": r"[,\n·ㆍ;]",
    "쉼표+' 및 '+' 또는 '": r"(?:,|\s및\s|\s또는\s)",
    "전체후보": r"(?:[,\n·ㆍ;]|\s및\s|\s또는\s)",
}
# 성분명이 아닐 가능성이 큰 꼬리표. 분류 전 참고용으로 센다.
NOT_INGREDIENT_HINT = ("논코메도제닉", "무향", "무알콜", "저자극", "성분", "제품", "사용", "함유")


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
    p.add_argument("--out", type=Path, required=True, help="집계 결과 (UTF-8)")
    p.add_argument("--samples-out", type=Path, help="사람이 읽을 예시 (UTF-8)")
    p.add_argument("--samples", type=int, default=40, help="예시 건수")
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
            "SELECT q.seq, q.subject_id, r.split, q.question_text, q.answer_text, "
            "       q.recommended_raw, q.avoid_raw "
            "FROM public.aihub_qa_case q JOIN public.aihub_qa_case_raw r ON r.seq = q.seq"
        )
    finally:
        await conn.close()

    # ---- A. 대상자 ID 누출 ----
    by_split = collections.defaultdict(set)
    qa_by_split = collections.Counter()
    for r in rows:
        by_split[r["split"]].add(r["subject_id"])
        qa_by_split[r["split"]] += 1
    shared = by_split["train"] & by_split["validation"]
    val_leaked = sum(
        1 for r in rows if r["split"] == "validation" and r["subject_id"] in shared
    )
    q_index = collections.defaultdict(set)
    a_index = collections.defaultdict(set)
    for r in rows:
        if r["question_text"]:
            q_index[r["question_text"].strip()].add(r["split"])
        if r["answer_text"]:
            a_index[r["answer_text"].strip()].add(r["split"])
    q_cross = sum(1 for v in q_index.values() if len(v) > 1)
    a_cross = sum(1 for v in a_index.values() if len(v) > 1)
    q_dup = sum(c - 1 for c in collections.Counter(
        r["question_text"].strip() for r in rows if r["question_text"]).values() if c > 1)
    a_dup = sum(c - 1 for c in collections.Counter(
        r["answer_text"].strip() for r in rows if r["answer_text"]).values() if c > 1)
    same_field = sum(
        1 for r in rows
        if r["recommended_raw"] and r["avoid_raw"]
        and r["recommended_raw"].strip() == r["avoid_raw"].strip()
    )

    # ---- B. 성분 문자열 구분자 ----
    strings = []
    for r in rows:
        for kind in ("recommended_raw", "avoid_raw"):
            if r[kind]:
                strings.append((kind, r[kind]))
    char_freq = collections.Counter()
    for _, text in strings:
        for ch in text:
            if not ch.isalnum() and not ch.isspace() or ch == "\n":
                char_freq[ch] += 1

    results = {}
    for label, pattern in CANDIDATES.items():
        tokens, valid, hint, long_tokens = 0, 0, 0, 0
        per_string = []
        for _, text in strings:
            parts = [t.strip() for t in re.split(pattern, text) if t.strip()]
            per_string.append(len(parts))
            for t in parts:
                tokens += 1
                if norm(t) in mfds:
                    valid += 1
                if any(h in t for h in NOT_INGREDIENT_HINT):
                    hint += 1
                if len(t) > 30:
                    long_tokens += 1
        results[label] = {
            "tokens": tokens, "valid": valid, "hint": hint, "long": long_tokens,
            "avg_per_string": sum(per_string) / len(per_string) if per_string else 0,
        }

    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", encoding="utf-8") as fh:
        w = lambda s="": fh.write(s + "\n")
        w("# AI-Hub QA 측정 (집계만, 원문 내용 없음)")
        w(f"\nQA {len(rows):,}건")

        w("\n## A. 대상자 ID 누출")
        w(f"  학습 QA {qa_by_split['train']:,} / 고유 대상자 {len(by_split['train']):,}")
        w(f"  검증 QA {qa_by_split['validation']:,} / 고유 대상자 {len(by_split['validation']):,}")
        w(f"  양쪽에 걸친 대상자        {len(shared):>6,}")
        w(f"  그 대상자의 검증 QA       {val_leaked:>6,} / {qa_by_split['validation']:,}")
        w(f"  질문이 양쪽 분할에 등장    {q_cross:>6,}")
        w(f"  답변이 양쪽 분할에 등장    {a_cross:>6,}")
        w(f"  완전 동일 질문 중복       {q_dup:>6,}")
        w(f"  완전 동일 답변 중복       {a_dup:>6,}")
        w(f"  추천=주의 가 같은 문자열   {same_field:>6,}")

        w("\n## B. 성분 문자열 구분자")
        w(f"  대상 문자열 {len(strings):,}개 (추천 + 주의)")
        w("\n  구분자 후보 문자 출현 (문자: 총 등장 수)")
        for ch, c in char_freq.most_common(25):
            name = repr(ch)
            w(f"    {c:>8,}  {name}")
        w("\n  후보 규칙별 결과")
        w(f"    {'규칙':<34}{'토큰':>9}{'식약처일치':>11}{'일치율':>8}"
          f"{'비성분힌트':>11}{'30자초과':>9}{'문자열당':>9}")
        for label, v in results.items():
            rate = v["valid"] / v["tokens"] * 100 if v["tokens"] else 0
            w(f"    {label:<34}{v['tokens']:>9,}{v['valid']:>11,}{rate:>7.1f}%"
              f"{v['hint']:>11,}{v['long']:>9,}{v['avg_per_string']:>9.1f}")
        w("\n  일치율이 가장 높고 30자 초과 토큰이 적은 규칙이 후보다.")
        w("  일치율이 낮으면 성분이 아닌 값이 섞여 있다는 뜻이므로 분류가 먼저다.")

    print("wrote", a.out)

    if a.samples_out:
        import random
        random.seed(1)
        picked = random.sample(strings, min(a.samples, len(strings)))
        with a.samples_out.open("w", encoding="utf-8") as fh:
            fh.write("# 추천·주의 성분 원문 예시 (사람이 읽고 판단용)\n\n")
            fh.write("쪼개는 규칙을 정하기 전에 실제 표기를 확인합니다.\n")
            fh.write("성분이 아닌 값(제품 특성, 의약품명)이 섞였는지 함께 봅니다.\n\n")
            for i, (kind, text) in enumerate(picked, 1):
                label = "추천" if kind == "recommended_raw" else "주의"
                fh.write(f"## {i}. [{label}]\n{text}\n\n")
        print("wrote", a.samples_out)


asyncio.run(main())
