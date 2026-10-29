"""Normalize reviewed YouTube candidates without writing to the database.

uv run python -m app.jobs.normalize_youtube_candidates \
  seed/source/youtube_candidates_with_products.csv
"""

import argparse
import csv
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

DEFAULT_INPUT = Path("seed/source/youtube_candidates_with_products.csv")
DEFAULT_OUTPUT_DIR = Path("seed/source/normalized")

SUBJECT_OVERRIDES = {
    "aaYar3I6yQA": "",
    "8XM7WDyqqVU": "",
    "ju33PTn20CA": "",
    "ksFyMbfJcww": "유정",
    "mcA6C14VuTU": "",
    "9p0SKbMRhDc": "리아",
    "m_Jz_alzHQM": "리아",
    "yWzg365rzMw": "아오이 유우",
}

STYLE_OVERRIDES = {
    "aaYar3I6yQA": "웜톤이 하는 쿨 그레이 메이크업",
    "8XM7WDyqqVU": "시크릿 투톤 헤어 메이크업",
    "ju33PTn20CA": "2023 하반기 추천템 총정리 메이크업",
    "ksFyMbfJcww": "",
    "mcA6C14VuTU": "다이소 개강 메이크업",
    "9p0SKbMRhDc": "",
    "m_Jz_alzHQM": "",
    "yWzg365rzMw": "",
}

ADDITIONAL_SUBJECTS = {"CTfQ92mhnfA": "한소희"}

REQUIRED_COLUMNS = {
    "순서",
    "검토 상태",
    "영상 제목",
    "채널명",
    "게시일",
    "재생 시간",
    "영상 ID",
    "YouTube 링크",
    "인물명 / 룩 스타일",
    "제품명",
    "썸네일 링크",
}

STATUS_MAP = {"후보": "candidate", "승인": "approved", "제외": "rejected"}

NOISE_PATTERNS = re.compile(
    r"(youtube channel|soundcloud|나눔뮤직|music by|music playlist|"
    r"\btrack\b|bgm|구독자\s*이벤트|bit\.ly|https?[: ]|tv\.naver\.com)",
    re.IGNORECASE,
)
TOOL_PATTERNS = re.compile(
    r"(브러쉬|브러시|속눈썹|가닥\s*속눈썹|렌즈|오렌즈|렌즈미|렌즈랑|"
    r"가발|헤어\s*마스카라|헤어\s*섀도)",
    re.IGNORECASE,
)
SKINCARE_PATTERNS = re.compile(
    r"(토너|패드|세럼|앰플|크림|선크림|선\s*세럼|"
    r"선\s*스틱|립\s*마스크|필오프\s*팩|마스크\s*팩|미스트)",
    re.IGNORECASE,
)
LIP_PATTERNS = re.compile(r"(립|틴트|글로스|루즈|플럼퍼|촉촉바)", re.IGNORECASE)
CHEEK_PATTERNS = re.compile(r"(블러셔|블러시|블러쉬|치크)", re.IGNORECASE)
EYE_COLOR_PATTERNS = re.compile(
    r"(아이\s*팔레트|아이팔레트|아이섀도|아이\s*섀도|섀도우|섀도\s*팔레트|"
    r"글리터|프로타주)",
    re.IGNORECASE,
)
EYE_OTHER_PATTERNS = re.compile(
    r"(아이라이너|라이너|마스카라|브로우|아이브로우|애교살)", re.IGNORECASE
)
BASE_PATTERNS = re.compile(
    r"(쿠션|파운데이션|컨실러|파우더|팩트|프라이머|베이스|쉐딩|"
    r"셰이딩|컨투어|하이라이터|톤업)",
    re.IGNORECASE,
)
COMMENTARY_PATTERNS = re.compile(
    r"(직접구매|제품제공|광고|출시\s*예정|개발\s*중|단종|사용\s*컬러|"
    r"구매처|할인|원대|가격)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ProductClassification:
    category: str
    makeup_zone: str
    review_status: str
    exclusion_reason: str


def classify_product(label: str) -> ProductClassification:
    if NOISE_PATTERNS.search(label):
        return ProductClassification("unknown", "", "needs_review", "non_product_content")
    if LIP_PATTERNS.search(label):
        return ProductClassification("lip", "lip", "needs_review", "")
    if CHEEK_PATTERNS.search(label):
        return ProductClassification("cheek", "blush", "needs_review", "")
    if EYE_COLOR_PATTERNS.search(label):
        return ProductClassification("eye", "eyeshadow", "needs_review", "")
    if EYE_OTHER_PATTERNS.search(label):
        return ProductClassification("eye", "", "needs_review", "")
    if BASE_PATTERNS.search(label):
        return ProductClassification("base", "", "needs_review", "")
    if SKINCARE_PATTERNS.search(label):
        return ProductClassification("skincare", "", "needs_review", "")
    if TOOL_PATTERNS.search(label):
        return ProductClassification("accessory", "", "needs_review", "accessory_or_tool")
    return ProductClassification("unknown", "", "needs_review", "category_unknown")


def normalize_label(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" \t\r\n-–—|")
    return re.sub(r"^[•·]+\s*", "", value)


def split_products(value: str) -> list[str]:
    return [label for part in re.split(r"\s+/\s+", value) if (label := normalize_label(part))]


def parse_subject_and_style(video_id: str, value: str) -> tuple[str, str, str]:
    subject = ""
    style = ""
    if value.startswith("인물:"):
        subject = normalize_label(value.removeprefix("인물:"))
    elif value.startswith("룩 스타일:"):
        style = normalize_label(value.removeprefix("룩 스타일:"))
    else:
        style = normalize_label(value)

    corrected = video_id in SUBJECT_OVERRIDES or video_id in STYLE_OVERRIDES
    subject = SUBJECT_OVERRIDES.get(video_id, subject)
    style = STYLE_OVERRIDES.get(video_id, style)
    return subject, style, "corrected" if corrected else "source_reviewed"


def read_source(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"missing columns: {', '.join(sorted(missing))}")
        rows = list(reader)
    video_ids = [row["영상 ID"].strip() for row in rows]
    duplicates = [video_id for video_id, count in Counter(video_ids).items() if count > 1]
    if duplicates:
        raise ValueError(f"duplicate video ids: {', '.join(sorted(duplicates))}")
    return rows


def write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def normalize(source: Path, output_dir: Path) -> tuple[int, int, Counter]:
    videos: list[dict] = []
    products: list[dict] = []
    issues: list[dict] = []
    for row in read_source(source):
        video_id = row["영상 ID"].strip()
        subject, style, classification_status = parse_subject_and_style(
            video_id, row["인물명 / 룩 스타일"].strip()
        )
        review_status = STATUS_MAP.get(row["검토 상태"].strip(), "needs_review")
        videos.append(
            {
                "playlistPosition": int(row["순서"]),
                "reviewStatus": review_status,
                "videoId": video_id,
                "youtubeUrl": row["YouTube 링크"].strip(),
                "title": row["영상 제목"].strip(),
                "channelName": row["채널명"].strip(),
                "publishedAt": row["게시일"].strip(),
                "durationISO8601": row["재생 시간"].strip(),
                "subjectName": subject,
                "additionalSubjectNames": ADDITIONAL_SUBJECTS.get(video_id, ""),
                "lookStyle": style,
                "classificationStatus": classification_status,
                "thumbnailUrl": row["썸네일 링크"].strip(),
            }
        )
        for index, label in enumerate(split_products(row["제품명"]), start=1):
            classification = classify_product(label)
            has_commentary = bool(COMMENTARY_PATTERNS.search(label))
            product_row = {
                "videoId": video_id,
                "sourceOrder": index,
                "rawProductText": label,
                "brand": "",
                "productName": label,
                "shadeName": "",
                "category": classification.category,
                "makeupZone": classification.makeup_zone,
                "evidenceSource": "youtube_description",
                "mappingStatus": "unverified",
                "reviewStatus": classification.review_status,
                "reviewReason": (
                    classification.exclusion_reason
                    or ("contains_commentary" if has_commentary else "brand_and_shade_unparsed")
                ),
            }
            products.append(product_row)
            if classification.exclusion_reason or has_commentary:
                issues.append(
                    {
                        "videoId": video_id,
                        "sourceOrder": index,
                        "rawProductText": label,
                        "issue": product_row["reviewReason"],
                    }
                )

    write_csv(
        output_dir / "youtube_videos_normalized.csv",
        (
            "playlistPosition",
            "reviewStatus",
            "videoId",
            "youtubeUrl",
            "title",
            "channelName",
            "publishedAt",
            "durationISO8601",
            "subjectName",
            "additionalSubjectNames",
            "lookStyle",
            "classificationStatus",
            "thumbnailUrl",
        ),
        videos,
    )
    write_csv(
        output_dir / "youtube_video_products_normalized.csv",
        (
            "videoId",
            "sourceOrder",
            "rawProductText",
            "brand",
            "productName",
            "shadeName",
            "category",
            "makeupZone",
            "evidenceSource",
            "mappingStatus",
            "reviewStatus",
            "reviewReason",
        ),
        products,
    )
    write_csv(
        output_dir / "youtube_normalization_issues.csv",
        ("videoId", "sourceOrder", "rawProductText", "issue"),
        issues,
    )
    return len(videos), len(products), Counter(row["reviewStatus"] for row in products)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?", default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    video_count, product_count, statuses = normalize(args.source, args.output_dir)
    print(f"videos={video_count} products={product_count}")
    for status, count in sorted(statuses.items()):
        print(f"products[{status}]={count}")
    print(f"output_dir={args.output_dir}")


if __name__ == "__main__":
    main()
