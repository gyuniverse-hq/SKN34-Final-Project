"""AI-Hub 적재를 한 명령으로 실행한다. 각 단계는 기존 스크립트를 그대로 호출한다.

테이블은 alembic 이 만든다. 이 스크립트는 테이블이 있는지 확인만 하고, 없으면
`alembic upgrade head` 를 안내하고 멈춘다.

--apply 가 없으면 각 단계가 자기 미리보기 모드로 돌고 DB 를 바꾸지 않는다.
비밀번호는 한 번만 묻고 하위 단계에 환경변수로 넘긴다. 명령줄에 남지 않는다.

backend/api 에서:
  uv run python ..\\..\\scripts\\data\\aihub\\load_all.py --data-dir "%DATA%"
  uv run python ..\\..\\scripts\\data\\aihub\\load_all.py --data-dir "%DATA%" --apply
"""

import argparse
import asyncio
import getpass
import ipaddress
import os
import socket
import subprocess
import sys
from pathlib import Path

import asyncpg

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

# 순서가 중요하다. 출처 연결은 QA 와 문서가 모두 들어온 뒤에만 가능하다.
STEPS = (
    ("원본 구조 검증", "verify_source.py", ("data_dir", "out"), False),
    ("QA 적재", "load_qa.py", ("data_dir", "conn", "qa_opts"), True),
    ("지식 문서 적재", "load_documents.py", ("data_dir", "conn"), True),
    ("QA-문서 출처 연결", "match_sources.py", ("conn",), True),
    ("성분 언급 적재", "load_mentions.py", ("conn",), True),
)

# 적재 전에 있어야 하는 테이블. 없으면 alembic 을 먼저 돌려야 한다.
REQUIRED = (
    "aihub_dataset_release",
    "aihub_skin_concern",
    "aihub_skin_type",
    "aihub_qa_case_raw",
    "aihub_qa_case",
    "aihub_knowledge_document",
    "aihub_knowledge_document_file",
    "aihub_qa_source_link",
    "aihub_ingredient_mention",
    "aihub_claim_review",
)


def assert_local(host: str) -> None:
    """로컬이 아닌 곳에는 아예 연결하지 않는다. 각 적재 스크립트와 같은 규칙이다."""
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
        "AI-Hub 원본은 각자 국내 로컬에만 둡니다(docs/AIHUB_DATA_RIGHTS.md)."
    )


async def check_tables(a, pw: str) -> list[str]:
    conn = await asyncpg.connect(
        host=a.host, port=a.port, database=a.database, user=a.user, password=pw
    )
    try:
        rows = await conn.fetch(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema = 'public' AND table_name = ANY($1::text[])",
            list(REQUIRED),
        )
        found = {r[0] for r in rows}
        return [t for t in REQUIRED if t not in found]
    finally:
        await conn.close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", required=True, help="AI-Hub 원본 폴더 (3.개방데이터\\1.데이터)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=15432)
    p.add_argument("--database", default="vishue_db")
    p.add_argument("--user", default="vishue")
    p.add_argument("--received-at", help="배포본 수령일 YYYY-MM-DD. 생략하면 오늘")
    p.add_argument("--release-version", help="배포본 버전 표기")
    p.add_argument("--skip-verify", action="store_true", help="원본 구조 검증 단계를 건너뜀")
    p.add_argument(
        "--verify-out",
        default=str(ROOT / "data" / "aihub-source-verify.txt"),
        help="검증 결과 파일",
    )
    p.add_argument("--apply", action="store_true", help="없으면 미리보기만 하고 DB 를 바꾸지 않음")
    a = p.parse_args()

    assert_local(a.host)
    data_dir = Path(a.data_dir)
    if not data_dir.is_dir():
        raise SystemExit(f"원본 폴더를 찾을 수 없습니다: {data_dir}")

    pw = os.environ.get("POSTGRES_PASSWORD") or getpass.getpass("Local PostgreSQL password: ")

    missing = asyncio.run(check_tables(a, pw))
    if missing:
        raise SystemExit(
            "다음 테이블이 없습니다: " + ", ".join(missing) + "\n"
            "테이블은 alembic 이 만듭니다. backend/api 에서 먼저 실행하세요:\n"
            "  uv run alembic upgrade head"
        )

    conn_args = [
        "--host", a.host, "--port", str(a.port),
        "--database", a.database, "--user", a.user,
    ]
    qa_opts: list[str] = []
    if a.received_at:
        qa_opts += ["--received-at", a.received_at]
    if a.release_version:
        qa_opts += ["--release-version", a.release_version]

    env = dict(os.environ)
    env["POSTGRES_PASSWORD"] = pw

    mode = "적재" if a.apply else "미리보기"
    print(f"AI-Hub {mode} 시작. 대상 {a.user}@{a.host}:{a.port}/{a.database}")
    print(f"원본 {data_dir}")

    for i, (label, script, needs, needs_apply) in enumerate(STEPS, 1):
        if script == "verify_source.py" and a.skip_verify:
            print(f"\n[{i}/{len(STEPS)}] {label} — 건너뜀")
            continue
        cmd = [sys.executable, str(HERE / script)]
        if "data_dir" in needs:
            cmd += ["--data-dir", str(data_dir)]
        if "out" in needs:
            cmd += ["--out", a.verify_out]
        if "conn" in needs:
            cmd += conn_args
        if "qa_opts" in needs:
            cmd += qa_opts
        if needs_apply and a.apply:
            cmd += ["--apply"]
        print(f"\n[{i}/{len(STEPS)}] {label}")
        print(f"  $ {script} {' '.join(cmd[2:])}")
        r = subprocess.run(cmd, env=env, cwd=str(HERE))
        if r.returncode != 0:
            raise SystemExit(
                f"\n[{i}/{len(STEPS)}] {label} 가 실패했습니다 (종료코드 {r.returncode}).\n"
                "다음 단계는 실행하지 않았습니다. 위 출력을 확인하세요."
            )

    print(f"\n모든 단계 완료 ({mode}).")
    if not a.apply:
        print("--apply 를 붙이면 실제로 적재합니다.")


if __name__ == "__main__":
    main()
