"""로컬 DB에 QA를 등록하고 검수 상태를 읽는다.

--register DATA_DIR은 기존 적재기를 실행한다. 같은 원본의 재등록은 이어서 처리한다.
--inventory는 원문이나 발췌 없이 집계만 출력한다. --list는 전체 QA 목록,
--qa는 특정 QA의 출처와 주장 개정본, --verify-release는 71961 배포본 검증을 추가한다.

기존 --out 모드에서는 적재된 QA를 두 가지로 측정한다.

A. 대상자 ID 누출  학습·검증이 같은 대상자를 공유하는지, 질문·답변이 교차 중복하는지.
                 요청서 체크리스트의 '대상자 ID 단위 재분리 및 유사도 누출 위험 보고'.

B. 성분 문자열 구분자  추천·주의 성분 원문을 어떤 문자로 쪼개야 하는지 측정한다.
                     추측으로 쪼개면 성분이 아닌 값이 성분으로 들어간다. 후보 구분자마다
                     쪼갠 뒤 식약처 표준명과 일치하는 비율을 비교해 규칙을 고른다.

집계는 --out 에, 사람이 읽을 예시는 --samples-out 에 따로 쓴다. 원문 내용은 집계
파일에 넣지 않는다.
backend/api 에서 uv run python 으로 실행.
"""
import argparse
import asyncio
import collections
import getpass
import hashlib
import importlib.util
import ipaddress
import json
import os
import re
import socket
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[3]
RELEASE_BASELINE = {
    "releases": 1,
    "raw_qa": 9031,
    "qa": 9031,
    "by_split": {"train": 8031, "validation": 1000},
    "by_concern": {
        "01": 732, "02": 720, "03": 598, "04": 720, "05": 943, "06": 694, "07": 942,
        "08": 892, "09": 493, "10": 495, "11": 675, "12": 675, "13": 452,
    },
    "source_links": 9181,
    "links_by_match": {"matched": 8957, "unmatched": 224},
    "qa_with_matched_source": 8821,
    "documents": 3108,
    "document_files": 6245,
    "ingredient_mentions": 18062,
}

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


async def read_inventory(
    conn: asyncpg.Connection, *, list_cases: bool, case_ids: list[str]
) -> dict:
    """한 스냅샷에서 원본 목록과 검수 상태를 읽는다."""
    async with conn.transaction(isolation="repeatable_read", readonly=True):
        counts = await conn.fetchrow("""
            SELECT
                (SELECT count(*) FROM public.aihub_dataset_release WHERE dataset_id = '71961')
                    AS releases,
                (SELECT count(*) FROM public.aihub_qa_case_raw) AS raw_qa,
                (SELECT count(*) FROM public.aihub_knowledge_document) AS documents,
                (SELECT count(*) FROM public.aihub_knowledge_document_file) AS document_files,
                (SELECT count(*) FROM public.aihub_ingredient_mention) AS ingredient_mentions
        """)
        concerns = await conn.fetch("""
            SELECT concern_code, label_ko FROM public.aihub_skin_concern ORDER BY concern_code
        """)
        cases = await conn.fetch("""
            SELECT q.seq, r.split, r.release_id, q.concern_code, q.review_progress,
                   EXISTS (
                       SELECT 1 FROM public.aihub_qa_source_link s WHERE s.seq = q.seq
                   ) AS has_source_ref,
                   EXISTS (
                       SELECT 1 FROM public.aihub_qa_source_link s
                       WHERE s.seq = q.seq AND s.match_status = 'matched'
                   ) AS has_matched_source,
                   EXISTS (
                       SELECT 1 FROM public.aihub_qa_claim qc WHERE qc.seq = q.seq
                   ) AS has_claim
            FROM public.aihub_qa_case q
            JOIN public.aihub_qa_case_raw r USING (seq)
            ORDER BY q.seq
        """)
        link_counts = await conn.fetch("""
            SELECT match_status, count(*) AS total FROM public.aihub_qa_source_link
            GROUP BY match_status ORDER BY match_status
        """)
        current_claims = await conn.fetch("""
            SELECT DISTINCT ON (claim_key) review_progress, approval_status
            FROM public.aihub_claim_version
            ORDER BY claim_key, revision DESC
        """)
        counts_by_concern = collections.Counter(row["concern_code"] for row in cases)
        report = {
            **dict(counts),
            "qa": len(cases),
            "by_split": dict(collections.Counter(row["split"] for row in cases)),
            "concern_labels": {row["concern_code"]: row["label_ko"] for row in concerns},
            "by_concern": {
                row["concern_code"]: counts_by_concern[row["concern_code"]] for row in concerns
            },
            "qa_review_progress": dict(collections.Counter(row["review_progress"] for row in cases)),
            "qa_without_claim": sum(not row["has_claim"] for row in cases),
            "qa_without_source_ref": sum(not row["has_source_ref"] for row in cases),
            "qa_with_matched_source": sum(row["has_matched_source"] for row in cases),
            "qa_without_matched_source": sum(not row["has_matched_source"] for row in cases),
            "source_links": sum(row["total"] for row in link_counts),
            "links_by_match": {row["match_status"]: row["total"] for row in link_counts},
            "current_claim_review_progress": dict(collections.Counter(
                row["review_progress"] for row in current_claims
            )),
            "current_claim_approval": dict(collections.Counter(
                row["approval_status"] or "undecided" for row in current_claims
            )),
        }
        if list_cases:
            report["cases"] = [dict(row) for row in cases]
        if case_ids:
            requested = set(case_ids)
            selected = {
                row["seq"]: {**dict(row), "sources": [], "claims": []}
                for row in cases if row["seq"] in requested
            }
            sources = await conn.fetch("""
                SELECT s.seq, s.source_position, s.match_status, s.quote_match_status,
                       s.document_id, d.content_sha256, d.source_identifier, d.source_version,
                       d.rights_status
                FROM public.aihub_qa_source_link s
                LEFT JOIN public.aihub_knowledge_document d USING (document_id)
                WHERE s.seq = ANY($1::text[]) ORDER BY s.seq, s.source_position
            """, case_ids)
            for row in sources:
                selected[row["seq"]]["sources"].append(dict(row))
            claims = await conn.fetch("""
                SELECT qc.seq, v.claim_key::text, v.claim_version_id, v.revision,
                       NOT EXISTS (
                           SELECT 1 FROM public.aihub_claim_version newer
                           WHERE newer.claim_key = v.claim_key AND newer.revision > v.revision
                       ) AS is_current,
                       v.review_progress, v.approval_status, v.approved_uses,
                       e.claim_id AS evidence_review_id, e.source_position, e.document_id,
                       d.content_sha256, d.source_identifier, d.source_version,
                       e.support_status, e.rights_status
                FROM public.aihub_qa_claim qc
                JOIN public.aihub_claim_version v USING (claim_version_id)
                LEFT JOIN public.aihub_claim_review e
                    ON e.claim_version_id = v.claim_version_id
                    AND (e.seq IS NULL OR e.seq = qc.seq)
                LEFT JOIN public.aihub_knowledge_document d ON d.document_id = e.document_id
                WHERE qc.seq = ANY($1::text[])
                ORDER BY qc.seq, v.claim_key, v.revision, e.claim_id
            """, case_ids)
            for row in claims:
                selected[row["seq"]]["claims"].append(dict(row))
            report["selected_cases"] = list(selected.values())
            report["missing_case_ids"] = sorted(requested - selected.keys())
    return report


def validate_release(report: dict) -> dict:
    mismatches = {
        key: {"expected": expected, "actual": report.get(key)}
        for key, expected in RELEASE_BASELINE.items() if report.get(key) != expected
    }
    return {"passed": not mismatches, "mismatches": mismatches}


def release_fingerprint(data_dir: Path) -> str:
    """기존 load_qa.py가 배포본에 저장하는 ZIP 집합 해시."""
    digest = hashlib.sha256()
    for subdir in ("Training/2.라벨링데이터", "Validation/2.라벨링데이터", "Other"):
        archives = sorted((data_dir / subdir).glob("*.zip"))
        if not archives:
            raise SystemExit(f"{subdir}에서 원본 ZIP을 찾을 수 없습니다")
        for archive in archives:
            digest.update(archive.name.encode("utf-8"))
            with archive.open("rb") as source:
                hashlib.file_digest(source, lambda: digest)
    return digest.hexdigest()


async def run_loader(script: str, args, password: str, *options: str) -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(Path(__file__).resolve().with_name(script)),
        "--host", args.host, "--port", str(args.port),
        "--database", args.database, "--user", args.user,
        "--apply", *options,
        env={**os.environ, "POSTGRES_PASSWORD": password},
        stdout=sys.stderr,
    )
    if await process.wait():
        raise SystemExit(f"{script} 적재 실패. 같은 원본으로 --register를 다시 실행할 수 있습니다.")


async def register_release(conn: asyncpg.Connection, args, password: str) -> dict:
    data_dir = args.register.resolve()
    digest = release_fingerprint(data_dir)
    # 다른 --register 실행과 직렬화한다. 하위 적재기는 각자 트랜잭션을 커밋한다.
    await conn.execute("SELECT pg_advisory_lock(71961::bigint)")
    try:
        releases = await conn.fetch("""
            SELECT release_id, source_sha256 FROM public.aihub_dataset_release
            WHERE dataset_id = '71961'
        """)
        before = await read_inventory(conn, list_cases=False, case_ids=[])
        if not releases:
            await run_loader(
                "load_all.py", args, password, "--data-dir", str(data_dir), "--skip-verify"
            )
            status = "registered"
        else:
            if len(releases) != 1 or releases[0]["source_sha256"] != digest:
                raise SystemExit("기존 배포본이 중복되었거나 원본 해시가 다릅니다. 배포본 이력을 확인하세요.")
            intake_fields = ("raw_qa", "qa", "by_split", "by_concern", "source_links")
            if any(before[key] != RELEASE_BASELINE[key] for key in intake_fields):
                raise SystemExit("배포본의 QA 등록 건수가 다릅니다. --inventory에서 상태를 확인하세요.")
            pending_links = before["links_by_match"].get("not_attempted", 0)
            if 0 < pending_links < before["source_links"]:
                raise SystemExit("출처 연결 상태가 섞여 있습니다. 기존 연결을 먼저 확인하세요.")
            status = "already_registered"
            if any(before[key] < RELEASE_BASELINE[key] for key in ("documents", "document_files")):
                await run_loader("load_documents.py", args, password, "--data-dir", str(data_dir))
                status = "resumed"
            if pending_links:
                await run_loader("match_sources.py", args, password)
                status = "resumed"
            if before["ingredient_mentions"] < RELEASE_BASELINE["ingredient_mentions"]:
                await run_loader("load_mentions.py", args, password)
                status = "resumed"
        report = await read_inventory(conn, list_cases=False, case_ids=[])
        return {"registration": status, **report, "release_validation": validate_release(report)}
    finally:
        await conn.execute("SELECT pg_advisory_unlock(71961::bigint)")


def load_normalizer():
    mod = ROOT / "scripts" / "data" / "oliveyoung" / "collectors" / "oliveyoung_erd_v30.py"
    sys.path.insert(0, str(mod.parent))
    spec = importlib.util.spec_from_file_location("oy_erd_v30", mod)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.norm


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=15432)
    p.add_argument("--database", default="vishue_db")
    p.add_argument("--user", default="vishue")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--register", type=Path, metavar="DATA_DIR", help="로컬 DB에 71961 원본 등록")
    mode.add_argument("--inventory", action="store_true", help="적재·검수 상태 JSON 출력")
    mode.add_argument("--out", type=Path, help="기존 원본 품질 집계 결과 (UTF-8)")
    p.add_argument("--list", action="store_true", help="전체 QA 상태 목록 포함")
    p.add_argument("--qa", action="append", default=[], metavar="SEQ", help="QA 상세 조회. 반복 가능")
    p.add_argument("--verify-release", action="store_true", help="71961 배포본 기준 건수와 대조")
    p.add_argument("--samples-out", type=Path, help="사람이 읽을 예시 (UTF-8)")
    p.add_argument("--samples", type=int, default=40, help="예시 건수")
    a = p.parse_args()
    if not a.inventory and (a.list or a.qa or a.verify_release):
        p.error("--list, --qa, --verify-release는 --inventory와 함께 사용합니다")
    if not a.out and a.samples_out:
        p.error("--samples-out은 --out과 함께 사용합니다")

    assert_local(a.host)
    pw = os.environ.get("POSTGRES_PASSWORD") or getpass.getpass("Local PostgreSQL password: ")
    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                user=a.user, password=pw, ssl=False)
    try:
        if a.register:
            report = await register_release(conn, a, pw)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            if (
                report["registration"] != "already_registered"
                and not report["release_validation"]["passed"]
            ):
                raise SystemExit(1)
            return
        if a.inventory:
            report = await read_inventory(conn, list_cases=a.list, case_ids=a.qa)
            if a.verify_release:
                report["release_validation"] = validate_release(report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            if report.get("missing_case_ids") or (
                a.verify_release and not report["release_validation"]["passed"]
            ):
                raise SystemExit(1)
            return
        norm = load_normalizer()
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


if __name__ == "__main__":
    asyncio.run(main())
