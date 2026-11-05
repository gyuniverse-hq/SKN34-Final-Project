"""원문 줄바꿈 등으로 쪼개진 성분 조각을 다시 이어붙인다.

같은 옵션에서 seq가 연속인 미매칭 조각 2~5개를 묶어, 이어붙인 이름이 식약처 표준명과
일치하면 올바른 성분 하나로 연결을 교체한다. 기본은 미리보기이며 --apply 로만 기록한다.
backend/api 에서 uv run python 으로 실행.
"""

import argparse, asyncio, csv, getpass, importlib.util, os, ssl, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[3]  # 저장소 루트
MOD = Path(__file__).resolve().parent / "collectors" / "oliveyoung_erd_v30.py"
sys.path.insert(0, str(MOD.parent))
_spec = importlib.util.spec_from_file_location("oy_erd_v30", MOD)
oy = importlib.util.module_from_spec(_spec)
sys.modules["oy_erd_v30"] = oy
_spec.loader.exec_module(oy)
norm = oy.norm  # 수집기와 동일한 정규화를 사용한다

MAX_WINDOW = 5
# 백업은 DB 테이블이 아니라 CSV 로 남긴다. public 스키마에 모델에 없는 테이블을
# 만들면 alembic check 가 "지워야 할 테이블"로 감지해 CI 가 깨진다.
DEFAULT_BACKUP_DIR = ROOT / "data" / "repair-backup"


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


def write_backup(rows, path: Path, columns) -> None:
    """변경 전 상태를 CSV 로 남긴다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row[c] for c in columns])
    print(f"  백업: {path}  ({len(rows):,}행)")


async def purge_orphans(conn, backup_dir: Path) -> None:
    """연결이 하나도 없는 성분 행을 백업하고 삭제한다."""
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    orphans = await conn.fetch(
        "SELECT i.ingredient_id, i.ingredient_name, i.ingredient_norm "
        "FROM public.raw_oy_ingredient i "
        "WHERE NOT EXISTS (SELECT 1 FROM public.raw_oy_option_ingredient oi "
        "                  WHERE oi.ingredient_id = i.ingredient_id)"
    )
    if not orphans:
        print("연결 없는 성분 행이 없습니다")
        return
    write_backup(orphans, backup_dir / f"{run_id}_orphan_ingredient.csv",
                 ("ingredient_id", "ingredient_name", "ingredient_norm"))
    async with conn.transaction():
        status = await conn.execute(
            "DELETE FROM public.raw_oy_ingredient i "
            "WHERE NOT EXISTS (SELECT 1 FROM public.raw_oy_option_ingredient oi "
            "                  WHERE oi.ingredient_id = i.ingredient_id)"
        )
    print(f"연결 없는 성분 행 삭제: {int(status.rsplit(' ', 1)[-1]):,}개 (run_id {run_id})")


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", choices=("local", "shared"), default="local")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=15432)
    p.add_argument("--database", default="vishue_db")
    p.add_argument("--user", default="vishue")
    p.add_argument("--ssl-ca-file")
    p.add_argument("--apply", action="store_true", help="실제로 기록한다")
    p.add_argument("--execute-shared", action="store_true")
    p.add_argument("--delete-orphans", action="store_true",
                   help="연결이 0개가 된 조각 성분 행도 삭제한다")
    p.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR,
                   help="변경 전 상태를 CSV 로 남길 폴더")
    a = p.parse_args()

    conn = await connect(a)
    try:
        dict_names = {}
        for r in await conn.fetch(
            "SELECT name_ko FROM public.raw_mfds_ingredient WHERE is_current"
        ):
            k = norm(r["name_ko"])
            if k:
                dict_names.setdefault(k, r["name_ko"])

        unmatched = {
            r["ingredient_id"]
            for r in await conn.fetch(
                "SELECT i.ingredient_id FROM public.raw_oy_ingredient i "
                "LEFT JOIN public.oy_mfds_ingredient_map m "
                "  ON m.oy_ingredient_id = i.ingredient_id "
                "WHERE m.oy_ingredient_id IS NULL"
            )
        }
        names = {
            r["ingredient_id"]: r["ingredient_name"]
            for r in await conn.fetch(
                "SELECT ingredient_id, ingredient_name FROM public.raw_oy_ingredient"
            )
        }
        by_norm = {
            r["ingredient_norm"]: r["ingredient_id"]
            for r in await conn.fetch(
                "SELECT ingredient_id, ingredient_norm FROM public.raw_oy_ingredient "
                "WHERE ingredient_norm IS NOT NULL"
            )
        }

        links = defaultdict(list)
        for r in await conn.fetch(
            "SELECT option_id, ingredient_id, seq FROM public.raw_oy_option_ingredient "
            "ORDER BY option_id, seq NULLS LAST, ingredient_id"
        ):
            links[r["option_id"]].append((r["seq"], r["ingredient_id"]))

        # 옵션별로 연속한 미매칭 조각 묶음을 찾는다(긴 묶음 우선).
        repairs = []  # (option_id, [(seq, ingredient_id)...], 표준명, 이어붙인 표기)
        for option_id, seq_rows in links.items():
            rows = [(s, i) for s, i in seq_rows if s is not None]
            n = len(rows)
            used = [False] * n
            for size in range(MAX_WINDOW, 1, -1):
                for start in range(n - size + 1):
                    block = rows[start:start + size]
                    if any(used[start:start + size]):
                        continue
                    if any(i not in unmatched for _, i in block):
                        continue
                    if any(block[k + 1][0] != block[k][0] + 1 for k in range(size - 1)):
                        continue
                    joined = "".join(names[i] or "" for _, i in block)
                    std = dict_names.get(norm(joined))
                    if not std:
                        continue
                    for k in range(start, start + size):
                        used[k] = True
                    repairs.append((option_id, block, std, joined))

        if not repairs:
            print("이어붙일 조각 묶음이 없습니다 (이미 복구됨)")
            if not (a.apply and a.delete_orphans):
                return
            await purge_orphans(conn, a.backup_dir)
            return

        # 이어붙인 이름에 해당하는 성분 행을 찾거나 새로 만든다.
        need_new = {}
        for _, _, std, joined in repairs:
            k = norm(joined)
            if k not in by_norm:
                need_new.setdefault(k, joined)

        frag_ids = {i for _, block, _, _ in repairs for _, i in block}
        link_count = sum(len(block) for _, block, _, _ in repairs)
        print(f"복구 묶음        {len(repairs):,}개")
        print(f"  2개 묶음       {sum(1 for r in repairs if len(r[1]) == 2):,}")
        print(f"  3개 이상 묶음   {sum(1 for r in repairs if len(r[1]) >= 3):,}")
        print(f"교체할 연결      {link_count:,}개")
        print(f"영향 옵션        {len({r[0] for r in repairs}):,}개")
        print(f"복원될 성분 종류  {len({r[2] for r in repairs}):,}종")
        print(f"관여 조각 행     {len(frag_ids):,}개")
        print(f"성분행 신규 생성  {len(need_new):,}개")
        print("\n3개 이상으로 쪼개진 예:")
        for option_id, block, std, joined in [r for r in repairs if len(r[1]) >= 3][:8]:
            print(f"  {[names[i] for _, i in block]} -> {std!r}")

        if not a.apply:
            print("\n미리보기입니다. 기록하지 않았습니다 (--apply 로 실행)")
            return

        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        pairs = sorted({(o, i) for o, block, _, _ in repairs for _, i in block})
        before = await conn.fetch(
            "SELECT oi.option_id, oi.ingredient_id, oi.seq "
            "FROM public.raw_oy_option_ingredient oi "
            "JOIN unnest($1::text[], $2::bigint[]) AS t(option_id, ingredient_id) "
            "  ON t.option_id = oi.option_id AND t.ingredient_id = oi.ingredient_id",
            [o for o, _ in pairs], [i for _, i in pairs],
        )
        write_backup(before, a.backup_dir / f"{run_id}_option_ingredient.csv",
                     ("option_id", "ingredient_id", "seq"))

        async with conn.transaction():
            # raw_oy_ingredient.ingredient_id 에 기본값이 없어 수집기처럼 직접 부여한다.
            next_id = await conn.fetchval(
                "SELECT COALESCE(MAX(ingredient_id), 0) FROM public.raw_oy_ingredient"
            )
            for k, joined in need_new.items():
                next_id += 1
                new_id = await conn.fetchval(
                    "INSERT INTO public.raw_oy_ingredient "
                    "(ingredient_id, ingredient_name, ingredient_norm) "
                    "VALUES ($1, $2, $3) ON CONFLICT (ingredient_norm) DO NOTHING "
                    "RETURNING ingredient_id",
                    next_id, joined, k,
                )
                if new_id is None:  # 이미 같은 norm 의 행이 있었다
                    next_id -= 1
                    new_id = await conn.fetchval(
                        "SELECT ingredient_id FROM public.raw_oy_ingredient "
                        "WHERE ingredient_norm = $1", k
                    )
                by_norm[k] = new_id
                print(f"  성분행 생성 [{new_id}] {joined!r}")

            replaced = 0
            for option_id, block, std, joined in repairs:
                target = by_norm[norm(joined)]
                keep_seq = block[0][0]
                await conn.execute(
                    "DELETE FROM public.raw_oy_option_ingredient "
                    "WHERE option_id = $1 AND ingredient_id = ANY($2::bigint[])",
                    option_id, [i for _, i in block],
                )
                await conn.execute(
                    "INSERT INTO public.raw_oy_option_ingredient (option_id, ingredient_id, seq) "
                    "VALUES ($1, $2, $3) ON CONFLICT (option_id, ingredient_id) DO NOTHING",
                    option_id, target, keep_seq,
                )
                replaced += len(block)


        print(f"\n복구 완료 (run_id {run_id})")
        print(f"  교체한 연결   {replaced:,}개")
        if a.delete_orphans:
            await purge_orphans(conn, a.backup_dir)
        print(f"  백업 폴더     {a.backup_dir}")
    finally:
        await conn.close()


asyncio.run(main())
