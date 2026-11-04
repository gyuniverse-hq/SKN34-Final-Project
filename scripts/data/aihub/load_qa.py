"""AI-Hub QA 원본을 aihub 스키마에 적재한다. 미리보기가 기본이며 --apply 로만 기록한다.

적재 대상
  dataset_release   배포본과 이용권한 1행
  qa_case_raw       QA 원문 9,031행 (raw_json 보존, 파일 경로와 해시 기록)
  qa_case           조회용 정규화 9,031행
  qa_source_link    실제 참조가 있는 자리만 9,181행

추천·주의 성분 문자열은 qa_case 에 원문으로 보존하고 분해하지 않는다. 구분자를 측정한
뒤 extract_mentions.py 가 따로 처리한다.

공용(원격) DB 에는 접속하지 않는다(docs/AIHUB_DATA_RIGHTS.md).
재실행해도 중복이 늘지 않는다. backend/api 에서 uv run python 으로 실행.
"""
import argparse, asyncio, collections, getpass, hashlib, ipaddress, json, os, re, socket, zipfile
from datetime import date
from pathlib import Path

import asyncpg

SEQ_CODE = re.compile(r"^(?P<subject>[^_]+)_(?P<code>\d{2})_")
EMPTY_VALUES = {"", "0", "-", "없음", "none", "null", "n/a"}
DATASET_ID = "71961"
DATASET_NAME = "문제성 피부 메이크업 추천 데이터"


def clean(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def meaningful(value) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return bool(text) and text.lower() not in EMPTY_VALUES


def pick(block: dict, part: str):
    """Source_info 블록에서 이름에 part 가 들어가는 첫 값을 꺼낸다(1~5 접미사 대응)."""
    for key, value in block.items():
        if part in key and meaningful(value):
            return str(value).strip()
    return None


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


def read_qa(data_dir: Path):
    """ZIP 을 풀지 않고 읽어 적재할 행을 만든다."""
    raw_rows, case_rows, link_rows = [], [], []
    stats = collections.Counter()
    for split, sub in (("train", "Training"), ("validation", "Validation")):
        zips = sorted((data_dir / sub / "2.라벨링데이터").glob("*.zip"))
        if not zips:
            raise SystemExit(f"{sub} 라벨링 ZIP 을 찾지 못했습니다")
        for zp in zips:
            with zipfile.ZipFile(zp) as zf:
                for name in zf.namelist():
                    if not name.lower().endswith(".json"):
                        continue
                    payload = zf.read(name)
                    doc = json.loads(payload.decode("utf-8-sig"))
                    data_info = doc.get("Data_info") or {}
                    human = doc.get("Human_info") or {}
                    skin = doc.get("Skin_info") or {}
                    ann = doc.get("Annotation_info") or {}
                    seq = str(data_info.get("SEQ") or "").strip()
                    if not seq:
                        stats["seq_missing"] += 1
                        continue
                    m = SEQ_CODE.match(seq)
                    if not m:
                        stats["seq_unparsed"] += 1
                        continue
                    raw_rows.append((
                        seq, split, zp.name, name,
                        hashlib.sha256(payload).hexdigest(),
                        json.dumps(doc, ensure_ascii=False),
                    ))
                    skin_type = skin.get("Skin condition category")
                    skin_type = str(skin_type).strip() if meaningful(skin_type) else None
                    case_rows.append((
                        seq, m.group("subject"), m.group("code"),
                        str(human.get("Skin Problem Type") or "").strip() or None,
                        skin_type,
                        str(skin.get("Skin Brightness") or "").strip() or None,
                        str(human.get("Makeup focus areas") or "").strip() or None,
                        str(ann.get("User Question") or "").strip() or None,
                        str(ann.get("Makeup Response") or "").strip() or None,
                        str(ann.get("Recommended Ingredients") or "").strip() or None,
                        str(ann.get("Ingredients to Avoid") or "").strip() or None,
                    ))
                    stats[f"split_{split}"] += 1
                    for i in range(1, 6):
                        block = doc.get(f"Source_info{i}")
                        if not isinstance(block, dict):
                            continue
                        title = pick(block, "Title")
                        quote = pick(block, "Knowledge Data")
                        fname = clean(block.get(f"File Name{i}_1"))
                        if not (title or quote or fname):
                            continue  # 참조가 없는 자리는 행을 만들지 않는다
                        link_rows.append((
                            seq, i, quote, title,
                            pick(block, "Author Name"),
                            pick(block, "Publisher Name"),
                            pick(block, "Year of Publication"),
                            fname,
                            clean(block.get(f"File Extension{i}_1")),
                            clean(block.get(f"File Name{i}_2")),
                            clean(block.get(f"File Extension{i}_2")),
                            pick(block, "Status"),
                        ))
    return raw_rows, case_rows, link_rows, stats


def archive_digest(data_dir: Path) -> tuple[str, str]:
    """받은 ZIP 들의 해시를 하나로 묶는다. 바깥 ZIP 이 없으므로 내부 ZIP 들로 계산한다."""
    h = hashlib.sha256()
    names = []
    for sub in ("Training/2.라벨링데이터", "Validation/2.라벨링데이터", "Other"):
        for zp in sorted((data_dir / sub).glob("*.zip")):
            names.append(zp.name)
            h.update(zp.name.encode("utf-8"))
            with zp.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
    return f"{len(names)}개 ZIP", h.hexdigest()


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", type=Path, required=True, help="'3.개방데이터/1.데이터' 폴더")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=15432)
    p.add_argument("--database", default="vishue_db")
    p.add_argument("--user", default="vishue")
    p.add_argument("--received-at", default=str(date.today()), help="원본 수령일 (YYYY-MM-DD)")
    p.add_argument("--release-version", default="v1.2")
    p.add_argument("--apply", action="store_true", help="실제로 기록한다")
    a = p.parse_args()

    assert_local(a.host)
    try:
        # asyncpg 는 date 컬럼에 문자열을 받지 않는다.
        received_at = date.fromisoformat(a.received_at)
    except ValueError:
        raise SystemExit(f"--received-at 는 YYYY-MM-DD 형식이어야 합니다: {a.received_at!r}")
    print("원본을 읽는 중...")
    raw_rows, case_rows, link_rows, stats = read_qa(a.data_dir)
    archive_label, digest = archive_digest(a.data_dir)

    print(f"\n  qa_case_raw     {len(raw_rows):>7,}행   (기준 9,031)")
    print(f"  qa_case         {len(case_rows):>7,}행   (기준 9,031)")
    print(f"  qa_source_link  {len(link_rows):>7,}행   (기준 9,181)")
    print(f"  train / validation  {stats['split_train']:,} / {stats['split_validation']:,}")
    if stats["seq_missing"] or stats["seq_unparsed"]:
        print(f"  건너뜀: SEQ 없음 {stats['seq_missing']}, SEQ 해석 실패 {stats['seq_unparsed']}")
    print(f"  원본 해시({archive_label}) {digest[:16]}...")

    pw = os.environ.get("POSTGRES_PASSWORD") or getpass.getpass("Local PostgreSQL password: ")
    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                user=a.user, password=pw, ssl=False)
    try:
        for table in ("dataset_release", "qa_case_raw", "qa_case", "qa_source_link"):
            n = await conn.fetchval(f"SELECT COUNT(*) FROM public.aihub_{table}")
            print(f"\n  적재 전 {table:<18}{n:>8,}행" if table == "dataset_release"
                  else f"  적재 전 {table:<18}{n:>8,}행")
        if not a.apply:
            print("\n미리보기입니다. 기록하려면 --apply 를 붙이세요.")
            return

        async with conn.transaction():
            release_id = await conn.fetchval(
                "INSERT INTO public.aihub_dataset_release "
                "(dataset_id, dataset_name, release_version, received_at, source_archive, "
                " source_sha256, rights_status, storage_region, rights_note) "
                "VALUES ($1, $2, $3, $4, $5, $6, 'local_only', 'kr-local', $7) "
                "RETURNING release_id",
                DATASET_ID, DATASET_NAME, a.release_version, received_at,
                archive_label, digest,
                "국외 반출 합의 없음. 국내 로컬 보관만 허용. docs/AIHUB_DATA_RIGHTS.md 참조",
            )
            await conn.executemany(
                "INSERT INTO public.aihub_qa_case_raw "
                "(seq, split, source_archive, source_file_path, sha256, raw_json, release_id) "
                "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7) "
                "ON CONFLICT (seq) DO NOTHING",
                [row + (release_id,) for row in raw_rows],
            )
            await conn.executemany(
                "INSERT INTO public.aihub_qa_case "
                "(seq, subject_id, concern_code, concern_label_raw, skin_type_raw, "
                " skin_brightness_raw, area_raw, question_text, answer_text, "
                " recommended_raw, avoid_raw) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) "
                "ON CONFLICT (seq) DO NOTHING",
                case_rows,
            )
            await conn.executemany(
                "INSERT INTO public.aihub_qa_source_link "
                "(seq, source_position, quote_raw, source_title_raw, author_raw, publisher_raw, "
                " publication_year_raw, file_name_raw, file_extension_raw, "
                " file_name_raw_2, file_extension_raw_2, status_raw) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12) "
                # 재실행하면 원문 필드는 갱신하되 연결 결과(document_id, match_status)는 보존한다.
                "ON CONFLICT (seq, source_position) DO UPDATE SET "
                "  quote_raw = EXCLUDED.quote_raw, "
                "  source_title_raw = EXCLUDED.source_title_raw, "
                "  author_raw = EXCLUDED.author_raw, "
                "  publisher_raw = EXCLUDED.publisher_raw, "
                "  publication_year_raw = EXCLUDED.publication_year_raw, "
                "  file_name_raw = EXCLUDED.file_name_raw, "
                "  file_extension_raw = EXCLUDED.file_extension_raw, "
                "  file_name_raw_2 = EXCLUDED.file_name_raw_2, "
                "  file_extension_raw_2 = EXCLUDED.file_extension_raw_2, "
                "  status_raw = EXCLUDED.status_raw",
                link_rows,
            )
        print(f"\n기록 완료 (release_id {release_id})")
        for table in ("dataset_release", "qa_case_raw", "qa_case", "qa_source_link"):
            n = await conn.fetchval(f"SELECT COUNT(*) FROM public.aihub_{table}")
            print(f"  {table:<20}{n:>8,}행")
        print("\n== 적재 후 대조 ==")
        for label, sql, expect in (
            ("고민 코드 13종", "SELECT COUNT(DISTINCT concern_code) FROM public.aihub_qa_case", 13),
            ("피부 타입 4종", "SELECT COUNT(DISTINCT skin_type_raw) FROM public.aihub_qa_case", 4),
            ("고유 대상자", "SELECT COUNT(DISTINCT subject_id) FROM public.aihub_qa_case", None),
            ("출처 미연결", "SELECT COUNT(*) FROM public.aihub_qa_source_link "
                          "WHERE match_status = 'not_attempted'", len(link_rows)),
        ):
            n = await conn.fetchval(sql)
            mark = "" if expect is None or n == expect else f"   <- 기대 {expect:,}"
            print(f"  {label:<16}{n:>8,}{mark}")
    finally:
        await conn.close()


asyncio.run(main())
