"""Other.zip 의 지식 문서와 메타데이터를 aihub 스키마에 적재한다.

적재 대상
  knowledge_document        내용 해시로 식별한 고유 문서 (기준 3,108)
  knowledge_document_file   원본 파일 경로별 레코드 (기준 6,245)

같은 문서가 사용·미사용 폴더에 중복으로 들어 있을 수 있어, 내용 해시로 문서를 하나로
묶고 경로는 따로 추적한다.

메타데이터 JSON 3,122개는 File_info.File Name 으로 문서에 연결한다. 파일명으로
확정되지 않으면 연결하지 않고 사유를 남긴다. 후보가 여럿이어도 모두 같은 문서를
가리키면(중복 사본) 모호하지 않은 것으로 본다.

File_info.Purpose 와 Cautions 는 문서별 이용 제한이므로 반드시 보존한다.

공용(원격) DB 에는 접속하지 않는다(docs/AIHUB_DATA_RIGHTS.md).
재실행해도 중복이 늘지 않는다. backend/api 에서 uv run python 으로 실행.
"""
import argparse, asyncio, collections, getpass, hashlib, ipaddress, json, os, socket, zipfile
from pathlib import Path

import asyncpg

EMPTY_VALUES = {"", "0", "-", "없음", "none", "null", "n/a"}


def clean(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def assert_local(host: str) -> None:
    if host in ("localhost", "127.0.0.1", "::1"):
        return
    try:
        if ipaddress.ip_address(socket.gethostbyname(host)).is_loopback:
            return
    except OSError:
        pass
    raise SystemExit(
        f"로컬이 아닌 host 에는 연결하지 않습니다: {host}\n"
        "AI-Hub 원본은 국외 리전에 두지 않기로 결정했습니다(docs/AIHUB_DATA_RIGHTS.md)."
    )


def read_other(zip_path: Path):
    """문서 파일과 메타데이터를 읽는다. 값은 보존하되 화면에는 찍지 않는다."""
    files = []          # (경로, 파일명, 확장자, 크기, 내용해시)
    metas = []          # (경로, 매칭키, 메타필드들)
    stats = collections.Counter()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename
            ext = Path(name).suffix.lower().lstrip(".")
            if ext == "json":
                doc = json.loads(zf.read(name).decode("utf-8-sig"))
                data_info = doc.get("Data_info") or {}
                file_info = doc.get("File_info") or {}
                source_info = doc.get("Source_info") or {}
                ann = doc.get("Annotation_info") or {}
                metas.append({
                    "path": name,
                    "file_name": clean(file_info.get("File Name")),
                    "file_extension": clean(file_info.get("File Extension")),
                    "title": clean(data_info.get("Title")),
                    "status": clean(data_info.get("Status")),
                    "author": clean(data_info.get("Author Name")),
                    "publisher": clean(data_info.get("Publisher Name (Institution Name)")),
                    "application": clean(file_info.get("Application")),
                    "purpose": clean(file_info.get("Purpose")),
                    "cautions": clean(file_info.get("Cautions")),
                    "source_type": clean(source_info.get("Source")),
                    "token_count": clean(source_info.get("Token Count")),
                    "keywords": clean(ann.get("Main Keywords")),
                    "year": clean(ann.get("year")),
                    "nation": clean(ann.get("nation")),
                    "language": clean(ann.get("language")),
                })
                stats["meta"] += 1
            elif ext == "doc":
                payload = zf.read(name)
                files.append((
                    name, Path(name).name, ext, len(payload),
                    hashlib.sha256(payload).hexdigest(),
                ))
                stats["doc"] += 1
            else:
                stats["etc"] += 1
    return files, metas, stats


def match_key(name: str | None) -> str | None:
    """확장자를 떼고 소문자로 맞춘 파일명. 메타의 File Name 과 실제 파일을 잇는 키."""
    if not name:
        return None
    return Path(name.strip()).stem.lower()


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", type=Path, required=True, help="'3.개방데이터/1.데이터' 폴더")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=15432)
    p.add_argument("--database", default="vishue_db")
    p.add_argument("--user", default="vishue")
    p.add_argument("--apply", action="store_true", help="실제로 기록한다")
    a = p.parse_args()

    assert_local(a.host)
    zip_path = a.data_dir / "Other" / "Other.zip"
    if not zip_path.is_file():
        raise SystemExit(f"Other.zip 을 찾을 수 없습니다: {zip_path}")

    print("Other.zip 을 읽는 중...")
    files, metas, stats = read_other(zip_path)
    unique_hashes = {f[4] for f in files}
    print(f"\n  문서 파일(.doc)   {stats['doc']:>7,}   (기준 6,245)")
    print(f"  내용 고유 문서    {len(unique_hashes):>7,}   (기준 3,108)")
    print(f"  메타 JSON         {stats['meta']:>7,}   (기준 3,122)")
    print(f"  그 밖의 파일      {stats['etc']:>7,}")

    # 파일명 -> 그 이름을 가진 파일들의 내용 해시
    by_key: dict[str, set[str]] = collections.defaultdict(set)
    for path, name, ext, size, digest in files:
        by_key[match_key(name)].add(digest)

    verdict = collections.Counter()
    resolved = {}   # 메타 경로 -> 내용 해시
    for meta in metas:
        key = match_key(meta["file_name"])
        hashes = by_key.get(key or "", set())
        if len(hashes) == 1:
            verdict["matched"] += 1
            resolved[meta["path"]] = next(iter(hashes))
        elif not hashes:
            verdict["unmatched"] += 1
        else:
            # 같은 이름이 여러 내용을 가리키면 사람이 봐야 한다
            verdict["ambiguous"] += 1

    print("\n  메타 JSON 연결 판정")
    for key in ("matched", "unmatched", "ambiguous"):
        print(f"    {key:<12}{verdict[key]:>7,}")

    # 한 문서에 메타가 여럿 붙으면 첫 번째만 쓰고 수를 센다
    meta_by_hash: dict[str, dict] = {}
    conflicts = 0
    for meta in metas:
        digest = resolved.get(meta["path"])
        if digest is None:
            continue
        if digest in meta_by_hash:
            conflicts += 1
            continue
        meta_by_hash[digest] = meta
    print(f"    문서 하나에 메타 중복  {conflicts:>5,}")
    print(f"    메타가 붙는 고유 문서  {len(meta_by_hash):>5,} / {len(unique_hashes):,}")

    pw = os.environ.get("POSTGRES_PASSWORD") or getpass.getpass("Local PostgreSQL password: ")
    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                user=a.user, password=pw, ssl=False)
    try:
        for table in ("knowledge_document", "knowledge_document_file"):
            n = await conn.fetchval(f"SELECT COUNT(*) FROM public.aihub_{table}")
            print(f"\n  적재 전 {table:<26}{n:>8,}행")
        if not a.apply:
            print("\n미리보기입니다. 기록하려면 --apply 를 붙이세요.")
            return

        async with conn.transaction():
            # 1) 고유 문서. 메타가 있으면 함께 넣는다.
            doc_rows = []
            for digest in sorted(unique_hashes):
                m = meta_by_hash.get(digest) or {}
                doc_rows.append((
                    digest, m.get("title"), m.get("author"), m.get("publisher"),
                    m.get("year"), m.get("status"), m.get("source_type"),
                    m.get("language"), m.get("nation"), m.get("application"),
                    m.get("token_count"), m.get("keywords"),
                    m.get("purpose"), m.get("cautions"),
                ))
            await conn.executemany(
                "INSERT INTO public.aihub_knowledge_document "
                "(content_sha256, title_raw, author_raw, publisher_raw, publication_year_raw, "
                " status_raw, source_type_raw, language_raw, country_raw, application_raw, "
                " token_count_raw, main_keywords_raw, purpose_raw, cautions_raw) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) "
                "ON CONFLICT (content_sha256) DO NOTHING",
                doc_rows,
            )
            id_by_hash = {
                r["content_sha256"]: r["document_id"]
                for r in await conn.fetch(
                    "SELECT document_id, content_sha256 FROM public.aihub_knowledge_document"
                )
            }
            # 2) 파일 경로별 레코드. 메타 연결 상태를 파일 단위로 남긴다.
            meta_path_by_hash = {h: m["path"] for h, m in meta_by_hash.items()}
            file_rows = []
            for path, name, ext, size, digest in files:
                hashes = by_key.get(match_key(name), set())
                if len(hashes) > 1:
                    status = "ambiguous"
                    meta_path = None
                elif digest in meta_path_by_hash:
                    status = "matched"
                    meta_path = meta_path_by_hash[digest]
                else:
                    status = "unmatched"
                    meta_path = None
                file_rows.append((
                    id_by_hash[digest], path, name, ext, size, meta_path, status,
                ))
            await conn.executemany(
                "INSERT INTO public.aihub_knowledge_document_file "
                "(document_id, source_file_path, file_name, file_extension, byte_size, "
                " meta_json_path, meta_match_status) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7) "
                "ON CONFLICT (source_file_path) DO NOTHING",
                file_rows,
            )

        print("\n기록 완료")
        for table in ("knowledge_document", "knowledge_document_file"):
            n = await conn.fetchval(f"SELECT COUNT(*) FROM public.aihub_{table}")
            print(f"  {table:<28}{n:>8,}행")
        print("\n== 적재 후 대조 ==")
        rows = await conn.fetch(
            "SELECT meta_match_status, COUNT(*) AS n FROM public.aihub_knowledge_document_file "
            "GROUP BY meta_match_status ORDER BY n DESC"
        )
        for r in rows:
            print(f"  파일 메타연결 {r['meta_match_status']:<14}{r['n']:>8,}")
        titled = await conn.fetchval(
            "SELECT COUNT(*) FROM public.aihub_knowledge_document WHERE title_raw IS NOT NULL"
        )
        rights = await conn.fetchval(
            "SELECT COUNT(*) FROM public.aihub_knowledge_document "
            "WHERE purpose_raw IS NOT NULL OR cautions_raw IS NOT NULL"
        )
        total = await conn.fetchval("SELECT COUNT(*) FROM public.aihub_knowledge_document")
        print(f"  제목이 있는 문서       {titled:>8,} / {total:,}")
        print(f"  이용조건이 있는 문서   {rights:>8,} / {total:,}")
    finally:
        await conn.close()


asyncio.run(main())
