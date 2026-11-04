"""팀원에게 줄 DB 덤프를 만든다. AI-Hub 테이블은 제외하고, 제외됐는지 검증한다.

AI-Hub 원본은 이용정책상 승인받지 않은 제3자에게 제공할 수 없다(docs/AIHUB_DATA_RIGHTS.md).
aihub_ 접두사 덕분에 --exclude-table 한 줄로 전부 빠지지만, 사람이 빠뜨릴 수 있으므로
만든 덤프의 목차를 다시 읽어 aihub 테이블이 하나도 없는지 확인한다. 하나라도 있으면
덤프 파일을 지우고 실패로 끝낸다.

반대 방향도 확인한다. 꼭 있어야 하는 테이블이 비어 있으면 잘못 만든 덤프다.

pg_dump 는 compose 의 postgres 컨테이너 안에서 돈다. Windows 에 설치할 필요가 없다.

저장소 루트에서:
  python scripts\\data\\make_team_dump.py
  python scripts\\data\\make_team_dump.py --out %USERPROFILE%\\Downloads
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "infra" / "compose" / "compose.yaml"

# 제외 대상. 와일드카드 하나로 aihub_ 로 시작하는 모든 테이블이 빠진다.
EXCLUDE = "aihub_*"

# 덤프에 반드시 있어야 하는 테이블. 하나라도 없으면 잘못 만든 덤프다.
EXPECTED = (
    "products",
    "shades",
    "raw_oy_product",
    "raw_oy_option_ingredient",
    "raw_mfds_ingredient",
    "oy_mfds_ingredient_map",
    "rec_mapping",
    "alembic_version",
)


def dc(*args: str, capture: bool = False) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose", "-f", str(COMPOSE), *args]
    return subprocess.run(
        cmd,
        check=False,
        text=True,
        capture_output=capture,
        encoding="utf-8",
        errors="replace",
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", default="vishue_db")
    p.add_argument("--user", default="vishue")
    p.add_argument("--out", type=Path, default=ROOT / "data", help="덤프를 둘 폴더")
    p.add_argument("--name", help="파일 이름. 생략하면 vishue_db_YYYYMMDD.dump")
    a = p.parse_args()

    stamp = datetime.now().strftime("%Y%m%d")
    name = a.name or f"{a.database}_{stamp}.dump"
    inside = f"/tmp/{name}"
    a.out.mkdir(parents=True, exist_ok=True)
    outside = a.out / name

    print(f"대상 DB   {a.database}")
    print(f"제외      {EXCLUDE}  (AI-Hub 원본은 제3자에게 제공하지 않음)")
    print(f"저장 위치 {outside}")

    print("\n[1/4] pg_dump")
    r = dc(
        "exec", "-T", "postgres", "pg_dump",
        "-U", a.user, "-d", a.database,
        f"--exclude-table={EXCLUDE}",
        "--no-owner", "--no-privileges",
        "-Fc", "-f", inside,
    )
    if r.returncode != 0:
        raise SystemExit(f"pg_dump 실패 (종료코드 {r.returncode})")

    print("[2/4] 목차 검증")
    r = dc("exec", "-T", "postgres", "pg_restore", "-l", inside, capture=True)
    if r.returncode != 0:
        dc("exec", "-T", "postgres", "rm", "-f", inside)
        raise SystemExit(f"목차를 읽을 수 없습니다 (종료코드 {r.returncode})\n{r.stderr}")
    toc = r.stdout

    leaked = sorted({
        line.strip()
        for line in toc.splitlines()
        if "aihub" in line.lower() and not line.lstrip().startswith(";")
    })
    if leaked:
        dc("exec", "-T", "postgres", "rm", "-f", inside)
        print("\n덤프에 AI-Hub 항목이 남아 있습니다. 파일을 지웠습니다.", file=sys.stderr)
        for line in leaked[:20]:
            print(f"  {line}", file=sys.stderr)
        raise SystemExit(1)
    print(f"  aihub 항목 0건 확인 (목차 {len(toc.splitlines())}줄)")

    missing = [t for t in EXPECTED if f" TABLE DATA public {t} " not in toc]
    if missing:
        dc("exec", "-T", "postgres", "rm", "-f", inside)
        raise SystemExit(
            "덤프에 꼭 있어야 할 테이블 데이터가 없습니다: " + ", ".join(missing)
        )
    print(f"  필수 테이블 {len(EXPECTED)}개 데이터 확인")

    print("[3/4] 컨테이너 밖으로 복사")
    r = dc("cp", f"postgres:{inside}", str(outside))
    if r.returncode != 0:
        raise SystemExit(f"복사 실패 (종료코드 {r.returncode})")

    print("[4/4] 정리")
    dc("exec", "-T", "postgres", "rm", "-f", inside)

    size = outside.stat().st_size
    print(f"\n완료  {outside}")
    print(f"크기  {size / 1024 / 1024:.1f} MB")
    print("\n팀원 안내: scripts/data/README_TEAM_SETUP.md")


if __name__ == "__main__":
    main()
