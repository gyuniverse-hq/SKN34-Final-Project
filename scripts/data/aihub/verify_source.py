"""AI-Hub 원본 ZIP의 구조와 수량을 전수 확인한다. 읽기 전용, DB 접속 없음.

인수인계 문서의 수치를 실물과 대조하기 위한 스크립트다. 요청서의 기준 문서 신뢰
순서에서 실물 ZIP 이 1위이므로, 문서와 다르면 문서가 아니라 이 결과를 따르고 차이를
기록한다.

출력은 건수·분포·필드 존재 여부 같은 집계뿐이다. 질문·답변·인용문 등 원문 내용은
출력하지 않는다. AI-Hub 원본은 국외로 내보내지 않는다(docs/AIHUB_DATA_RIGHTS.md).

ZIP 을 풀지 않고 그대로 읽는다. 결과는 UTF-8 파일로 쓴다.
"""
import argparse, collections, hashlib, json, re, zipfile
from pathlib import Path

SEQ_CODE = re.compile(r"^[^_]+_(\d{2})_")
TOP_LEVEL = ("Data_info", "Human_info", "Skin_info", "Annotation_info",
             "Source_info1", "Source_info2", "Source_info3", "Source_info4", "Source_info5")
CONCERN_LABEL = {
    "01": "염증성 / 화농성 여드름", "02": "염증성 / 면포성 여드름",
    "03": "염증성 / 지루성 피부염", "04": "염증성 / 주사 피부",
    "05": "민감성 / 홍조", "06": "민감성 / 모세혈관 확장",
    "07": "민감성 / 민감성 피부", "08": "민감성 / 아토피",
    "09": "색소문제 / 색소침착", "10": "색소문제 / 기미·주근깨",
    "11": "조직변화 / 모공확장", "12": "조직변화 / 노화",
    "13": "조직변화 / 켈로이드성",
}


EMPTY_VALUES = {"", "0", "-", "없음", "none", "null", "n/a"}


def meaningful(value) -> bool:
    """빈 값과 0 을 내용으로 세지 않는다."""
    if value is None:
        return False
    text = str(value).strip()
    return bool(text) and text.lower() not in EMPTY_VALUES


def load_json(raw: bytes):
    return json.loads(raw.decode("utf-8-sig"))


def scan_qa(zip_paths, split, stats):
    for zp in sorted(zip_paths):
        with zipfile.ZipFile(zp) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".json")]
            stats["zip_files"][zp.name] = len(names)
            for name in names:
                stats["qa_total"] += 1
                stats["split"][split] += 1
                try:
                    doc = load_json(zf.read(name))
                except Exception as exc:
                    stats["parse_error"].append(f"{zp.name}:{name}: {type(exc).__name__}")
                    continue
                stats["parsed"] += 1
                for key in TOP_LEVEL:
                    if key in doc:
                        stats["top_level"][key] += 1
                extra = set(doc) - set(TOP_LEVEL)
                for key in extra:
                    stats["unexpected_top_level"][key] += 1

                seq = str((doc.get("Data_info") or {}).get("SEQ") or "")
                if not seq:
                    stats["seq_missing"] += 1
                else:
                    stats["seq_values"][seq] += 1
                    stem = Path(name).stem
                    if stem != seq:
                        stats["seq_filename_mismatch"] += 1
                    m = SEQ_CODE.match(seq)
                    if m:
                        code = m.group(1)
                        stats["concern"][code] += 1
                        # 교차검증 1: ZIP(폴더) 하나에 코드가 하나씩만 들어 있나
                        stats["zip_codes"].setdefault(zp.name, set()).add(code)
                        stats["code_zips"].setdefault(code, set()).add(zp.name)
                        # 교차검증 2: 코드 하나에 원문 라벨이 하나씩만 대응되나
                        label = str((doc.get("Human_info") or {}).get("Skin Problem Type") or "").strip()
                        if label:
                            stats["code_labels"].setdefault(code, set()).add(label)
                            stats["label_codes"].setdefault(label, set()).add(code)
                        else:
                            stats["label_missing"] += 1
                    else:
                        stats["seq_code_unparsed"] += 1

                skin = (doc.get("Skin_info") or {}).get("Skin condition category")
                stats["skin_type"][str(skin).strip() if skin is not None else "(없음)"] += 1

                for i in range(1, 6):
                    block = doc.get(f"Source_info{i}")
                    if not isinstance(block, dict):
                        continue
                    stats["source_block"][i] += 1
                    # 참조가 '실제로' 있는지는 제목·인용문·파일명으로 판정한다.
                    # Year of Publication 의 0 처럼 빈 값을 내용으로 세면 안 된다.
                    def has(part):
                        for key, value in block.items():
                            if part in key and meaningful(value):
                                return True
                        return False
                    if has("Title"):
                        stats["source_title"][i] += 1
                    if has("Knowledge Data"):
                        stats["source_quote"][i] += 1
                    if has("File Name"):
                        stats["source_file"][i] += 1
                    if has("Title") or has("Knowledge Data") or has("File Name"):
                        stats["source_ref"][i] += 1


def scan_other(zp: Path, stats):
    with zipfile.ZipFile(zp) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            ext = Path(info.filename).suffix.lower().lstrip(".") or "(없음)"
            stats["other_ext"][ext] += 1
            if ext == "json":
                stats["other_meta_json"] += 1
            elif ext == "doc":
                stats["other_doc"] += 1
                digest = hashlib.sha256(zf.read(info.filename)).hexdigest()
                stats["doc_hash"][digest] += 1
            else:
                stats["other_etc"] += 1


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", type=Path, required=True,
                   help="'3.개방데이터/1.데이터' 폴더")
    p.add_argument("--out", type=Path, required=True, help="결과를 쓸 파일")
    a = p.parse_args()

    stats = {
        "qa_total": 0, "parsed": 0, "seq_missing": 0,
        "seq_filename_mismatch": 0, "seq_code_unparsed": 0,
        "other_doc": 0, "other_meta_json": 0, "other_etc": 0,
        "split": collections.Counter(), "concern": collections.Counter(),
        "skin_type": collections.Counter(), "source_ref": collections.Counter(),
        "source_block": collections.Counter(), "source_title": collections.Counter(),
        "source_quote": collections.Counter(), "source_file": collections.Counter(),
        "top_level": collections.Counter(), "unexpected_top_level": collections.Counter(),
        "seq_values": collections.Counter(), "zip_files": {},
        "other_ext": collections.Counter(), "doc_hash": collections.Counter(),
        "parse_error": [], "label_missing": 0,
        "zip_codes": {}, "code_zips": {}, "code_labels": {}, "label_codes": {},
    }

    for split, sub in (("train", "Training"), ("validation", "Validation")):
        zips = list((a.data_dir / sub / "2.라벨링데이터").glob("*.zip"))
        if not zips:
            raise SystemExit(f"{sub} 라벨링 ZIP 을 찾지 못했습니다")
        scan_qa(zips, split, stats)

    other = a.data_dir / "Other" / "Other.zip"
    if other.is_file():
        scan_other(other, stats)

    dup_seq = {s: n for s, n in stats["seq_values"].items() if n > 1}

    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", encoding="utf-8") as fh:
        w = lambda s="": fh.write(s + "\n")
        w("# AI-Hub 원본 구조 검증 (실물 ZIP 전수)")
        w(f"\n데이터 폴더: {a.data_dir}")

        w("\n## 수량")
        w(f"  QA 파일          {stats['qa_total']:>7,}   (문서 기준 9,031)")
        w(f"  파싱 성공        {stats['parsed']:>7,}")
        w(f"  Training         {stats['split']['train']:>7,}   (문서 기준 8,031)")
        w(f"  Validation       {stats['split']['validation']:>7,}   (문서 기준 1,000)")
        w(f"  고유 SEQ         {len(stats['seq_values']):>7,}")
        w(f"  SEQ 중복         {len(dup_seq):>7,}")
        w(f"  SEQ 없음         {stats['seq_missing']:>7,}")
        w(f"  파일명≠SEQ       {stats['seq_filename_mismatch']:>7,}")
        w(f"  SEQ 코드 해석 실패 {stats['seq_code_unparsed']:>5,}")
        w(f"  파싱 오류        {len(stats['parse_error']):>7,}")

        w("\n## 고민 코드 13종")
        w(f"  {'코드':<6}{'분류':<24}{'건수':>8}")
        for code in sorted(CONCERN_LABEL):
            w(f"  {code:<6}{CONCERN_LABEL[code]:<24}{stats['concern'][code]:>8,}")
        unknown = {c: n for c, n in stats["concern"].items() if c not in CONCERN_LABEL}
        if unknown:
            w(f"  문서에 없는 코드: {unknown}")
        w(f"  합계 {sum(stats['concern'].values()):,}")

        w("\n## 교차검증 — SEQ 코드 x 폴더 x 원문 라벨")
        multi_zip = {z: c for z, c in stats["zip_codes"].items() if len(c) > 1}
        multi_label = {c: l for c, l in stats["code_labels"].items() if len(l) > 1}
        cross_label = {l: c for l, c in stats["label_codes"].items() if len(c) > 1}
        w(f"  코드가 섞인 ZIP          {len(multi_zip):>5}  (0 이어야 정상)")
        w(f"  라벨이 여럿인 코드        {len(multi_label):>5}  (0 이어야 정상)")
        w(f"  코드에 걸친 라벨          {len(cross_label):>5}  (0 이어야 정상)")
        w(f"  원문 라벨이 빈 QA        {stats['label_missing']:>5}")
        if multi_zip:
            w("\n  코드가 섞인 ZIP:")
            for z, codes in sorted(multi_zip.items()):
                w(f"    {z}  -> {sorted(codes)}")
        if multi_label:
            w("\n  라벨이 여럿인 코드:")
            for c, labels in sorted(multi_label.items()):
                w(f"    {c}  -> {sorted(labels)}")
        if cross_label:
            w("\n  코드에 걸친 라벨:")
            for l, codes in sorted(cross_label.items()):
                w(f"    {l!r}  -> {sorted(codes)}")
        w("\n  코드별 ZIP 과 원문 라벨")
        w(f"    {'코드':<6}{'ZIP 수':>7}  원문 라벨")
        for code in sorted(stats["code_labels"]):
            labels = sorted(stats["code_labels"][code])
            w(f"    {code:<6}{len(stats['code_zips'].get(code, [])):>7}  "
              + (labels[0] if len(labels) == 1 else str(labels)))

        w("\n## 기본 피부 타입")
        for value, n in stats["skin_type"].most_common():
            w(f"  {value:<12}{n:>8,}")

        w("\n## 출처 참조")
        w("  블록 존재 여부가 아니라 제목·인용문·파일명에 실제 값이 있는지로 센다.")
        w(f"  {'':<14}{'블록존재':>9}{'제목':>8}{'인용문':>8}{'파일명':>8}{'참조있음':>9}")
        for i in range(1, 6):
            w(f"  Source_info{i} {stats['source_block'][i]:>9,}{stats['source_title'][i]:>8,}"
              f"{stats['source_quote'][i]:>8,}{stats['source_file'][i]:>8,}"
              f"{stats['source_ref'][i]:>9,}")
        w(f"  참조있음 합계 {sum(stats['source_ref'].values()):,}   (문서 기준 9,181)")

        w("\n## 최상위 객체 존재 건수")
        for key in TOP_LEVEL:
            w(f"  {key:<16}{stats['top_level'][key]:>8,}")
        if stats["unexpected_top_level"]:
            w("  문서에 없는 최상위 키:")
            for key, n in stats["unexpected_top_level"].most_common():
                w(f"    {key:<24}{n:>8,}")

        w("\n## Other.zip")
        w(f"  DOC(.doc) 파일   {stats['other_doc']:>7,}   (문서 기준 6,245)")
        w(f"  메타 JSON        {stats['other_meta_json']:>7,}   (문서 기준 3,122)")
        w(f"  DOC 내용 고유    {len(stats['doc_hash']):>7,}   (문서 기준 3,108)")
        w(f"  그 밖의 파일     {stats['other_etc']:>7,}   (문서는 '기타 메타 파일 등 별도')")
        w("  확장자 분포:")
        for ext, n in stats["other_ext"].most_common():
            w(f"    {ext:<10}{n:>8,}")

        w("\n## ZIP 별 JSON 수")
        for name in sorted(stats["zip_files"]):
            w(f"  {stats['zip_files'][name]:>6,}  {name}")

        if stats["parse_error"]:
            w("\n## 파싱 오류 목록")
            for line in stats["parse_error"][:50]:
                w(f"  {line}")

    print("wrote", a.out)


if __name__ == "__main__":
    main()
