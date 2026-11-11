"""
v30 — v29 + 성분 파싱 보강(@ 구분자, 듀오밤 [촉촉]/[벨벳] 2단 구조)

v24 기반. 수집 범위·이미지·색·발색판정·로그는 v24 그대로 두고,
성분 파싱만 v25~v28에서 검증한 방식으로 교체:
  ① 안내문 필터(완결 문장 제거)   ② 성분링크 (option,ingredient) 유일성
  ③ 성분명 정규화(ingredient_norm) + norm 기준 중복제거
  ④ 호수 머리글 평문 감지·교정(옵션 2개 이상에서만, 혼입/미연결 해소)
  ⑤ 공백/∙ 구분 블록 파싱
→ 검증: 1-옵션 오탐 0 / 다옵션 진짜 회귀 0 / 혼입 성분80개초과 260→9

(아래는 v23 대비 바뀐 점)
  · 색 추출 때 이미 메모리로 받은 이미지(컬러칩 · 색상비교 · 옵션)로 발린 사진 판정을 같이 함
    → 이미지 서버 요청이 늘지 않음 (계산 시간만 추가)
  · 썸네일은 내려받지 않고 종류 규칙으로 package 처리
  · 여러 호수가 같이 쓰는 세트 사진 · 팔레트 · 상세설명 이미지는 색 추출 때도 받지 않으므로 판정 공란
  · image_applied 의 applied_checked(사람 확인) 칸 삭제
  · 판정 기준값 · 계산은 oliveyoung_applied_judge_v1.py 의 것을 그대로 사용 (한 곳에서만 관리)

(아래는 v23 설명)

목적: "ERD에 그린 정보를 실제로 다 모을 수 있는가"를 확인한다.
      DB가 아직 없으므로 테이블별 CSV로 떨구고, 끝나면 필드별 채움률 리포트를 찍는다.

출력: out_v21/ 안에 테이블 하나당 CSV 하나 (총 20개)
      + 수집가능성_리포트.txt  ← 이게 이번 테스트의 결과물

실행:  python oliveyoung_erd_v23.py
       (oliveyoung_color_poc16.py 와 같은 폴더에 두고 실행)

전체 수집으로 바꾸려면 아래 SAMPLE_PER_CATEGORY 를 None 으로.
"""

import csv
import hashlib
import json
import os
import re
import sys
import threading
import time
import unicodedata
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import lru_cache

import oliveyoung_applied_judge_v1 as judge  # 판정 기준값 · 계산 공용
import oliveyoung_color_poc16 as oy

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(
    HERE, "out_v30"
)  # 새 폴더에서 시작. 이어받기 시 번호가 겹치지 않음
DONE_LOG = os.path.join(OUT_DIR, "_done.log")
REPORT = os.path.join(OUT_DIR, "수집가능성_리포트.txt")

SAMPLE_PER_CATEGORY = None  # 중분류별 표본 수. None 이면 전체 2,491개
WORKERS = 10  # 차단을 겪어 낮춘 값. 더 낮추려면 6~8
SCRIPT_VERSION = "v30.2-observation"
BASE = oy.BASE


# ───────── ERD 테이블 정의 (열 순서 = ERD 순서) ─────────
SCHEMA = OrderedDict(
    [
        (
            "crawl_run",
            ["run_id", "script_version", "started_at", "finished_at", "status"],
        ),
        ("brand", ["brand_code", "brand_name_ko", "brand_name_en"]),
        ("supplier", ["supplier_code", "supplier_name"]),
        (
            "category",
            [
                "category_no",
                "parent_category_no",
                "depth",
                "category_name",
                "category_path",
            ],
        ),
        (
            "product",
            [
                "goods_no",
                "brand_code",
                "supplier_code",
                "category_no",
                "std_category_code",
                "goods_name",
                "product_url",
                "sale_status",
                "is_new",
                "registered_at",
                "modified_at",
                "first_collected_at",
                "last_collected_at",
                "delisted_at",
            ],
        ),
        (
            "product_notice",
            [
                "goods_no",
                "volume",
                "main_spec",
                "shelf_life",
                "usage_guide",
                "manufacturer",
                "origin_country",
                "ingredients_raw",
                "notice_extra",
                "collected_at",
            ],
        ),
        (
            "product_option",
            [
                "option_id",
                "goods_no",
                "option_no",
                "barcode",
                "option_name",
                "shade_code",
                "shade_name",
                "sort_seq",
                "is_representative",
                "collected_at",
            ],
        ),
        (
            "price_snapshot",
            [
                "snapshot_id",
                "option_id",
                "list_price",
                "sale_price",
                "max_benefit_price",
                "is_discount",
                "is_sold_out",
                "is_latest",
                "collected_at",
            ],
        ),
        (
            "option_color",
            [
                "option_id",
                "collected_at",
                "hex_code",
                "lab_l",
                "lab_a",
                "lab_b",
                "color_method",
                "color_image_id",
                "color_confidence",
                "color_note",
                "run_id",
                "is_confirmed",
            ],
        ),
        ("texture_type", ["texture_code", "gloss_axis", "ar_gloss", "ar_matte"]),
        (
            "product_texture",
            ["goods_no", "texture_code", "judge_step", "judge_reason", "collected_at"],
        ),
        (
            "image",
            [
                "image_id",
                "goods_no",
                "option_id",
                "image_type",
                "image_url",
                "sort_seq",
                "collected_at",
            ],
        ),
        # 같은 URL이 여러 상품에 걸쳐 쓰이므로(758건) 판정은 URL 기준으로 1회만 한다
        ("image_applied", ["image_url", "applied_type", "applied_conf", "judged_at"]),
        (
            "review_summary",
            [
                "summary_id",
                "goods_no",
                "review_count",
                "rating_avg",
                "rating_5_pct",
                "rating_4_pct",
                "rating_3_pct",
                "rating_2_pct",
                "rating_1_pct",
                "ai_positive_ratio",
                "ai_negative_ratio",
                "is_latest",
                "collected_at",
            ],
        ),
        (
            "review_ai_feature",
            ["goods_no", "seq", "title", "description", "collected_at"],
        ),
        ("survey_question", ["question_code", "question_name"]),
        ("survey_answer", ["answer_code", "question_code", "answer_name"]),
        ("review_survey", ["goods_no", "answer_code", "percentage", "collected_at"]),
        ("ingredient", ["ingredient_id", "ingredient_name", "ingredient_norm"]),
        ("option_ingredient", ["option_id", "ingredient_id", "seq"]),
        (
            "crawl_log",
            [
                "log_id",
                "run_id",
                "goods_no",
                "step",
                "http_status",
                "status",
                "error_message",
                "logged_at",
            ],
        ),
    ]
)

# 제형 7종 고정표. ar_gloss / ar_matte 는 AR 렌더링에서 쓸 실제 수치라
# 팀에서 정해 채워야 하는 칸이다. (수집으로 얻는 값이 아님)
TEXTURE_TYPE_ROWS = [
    {"texture_code": "matte", "gloss_axis": 1, "ar_gloss": "", "ar_matte": ""},
    {"texture_code": "velvet", "gloss_axis": 2, "ar_gloss": "", "ar_matte": ""},
    {"texture_code": "cream", "gloss_axis": 3, "ar_gloss": "", "ar_matte": ""},
    {"texture_code": "satin", "gloss_axis": 4, "ar_gloss": "", "ar_matte": ""},
    {"texture_code": "sheer", "gloss_axis": 5, "ar_gloss": "", "ar_matte": ""},
    {"texture_code": "glossy", "gloss_axis": 6, "ar_gloss": "", "ar_matte": ""},
    {"texture_code": "shimmer", "gloss_axis": "", "ar_gloss": "", "ar_matte": ""},
]

# 이번 실행에서 값이 비어도 '수집 실패'가 아닌 칸 (리포트에서 따로 표시)
OBSERVATION_VERSION = "oy-occurrences-v1"
SCHEMA["option_ingredient_observation"] = [
    "option_id", "source_version", "collected_at", "source_url", "raw_text",
    "raw_sha256", "parser_version", "ownership_status", "completeness", "entries",
]

EXPECTED_BLANK = {
    ("texture_type", "ar_gloss"): "AR 렌더링 수치 – 팀이 정할 값",
    ("texture_type", "ar_matte"): "AR 렌더링 수치 – 팀이 정할 값",
    ("texture_type", "gloss_axis"): "shimmer는 광택 축 바깥이라 1행만 공란",
    (
        "image_applied",
        "applied_type",
    ): "상세설명 · 세트 사진 · 팔레트는 색 추출 때 받지 않아 판정 공란",
    (
        "image_applied",
        "applied_conf",
    ): "판정한 행 중 계산한 것만 (썸네일 규칙 처리는 공란)",
    ("image_applied", "judged_at"): "applied_type 과 같은 비율",
    ("option_color", "is_confirmed"): "사람이 확정한 행에만 표시",
    ("image", "option_id"): "상품 단위 이미지(썸네일·상세설명)는 호수가 없음",
    ("crawl_run", "finished_at"): "실행 끝날 때 채움",
    ("crawl_log", "error_message"): "성공 행은 공란",
    ("option_color", "hex_code"): "색을 못 뽑은 옵션은 공란 + color_note에 사유",
    ("option_color", "lab_l"): "hex_code와 동일",
    ("option_color", "lab_a"): "hex_code와 동일",
    ("option_color", "lab_b"): "hex_code와 동일",
    ("option_color", "color_image_id"): "색을 못 뽑으면 참조할 이미지도 없음",
    ("product_texture", "texture_code"): "브로우·라이너·마스카라는 제형 축 비해당",
    ("product_option", "shade_code"): "단일상품·세트 옵션은 호수가 없음",
    ("product_option", "shade_name"): "단일상품·세트 옵션은 호수가 없음",
    ("product_notice", "notice_extra"): "NOTICE_MAP에 없는 항목이 있을 때만 참",
    ("category", "parent_category_no"): "최상위('뷰티') 1행만 부모가 없음",
    (
        "option_color",
        "color_confidence",
    ): "색을 뽑은 행에만 있음 (hex_code와 같은 비율)",
    ("option_color", "color_note"): "색을 '못' 뽑은 행에만 사유가 들어감",
    (
        "review_summary",
        "rating_1_pct",
    ): "해당 별점 리뷰가 0건이면 조회 결과에서 항목이 빠짐",
    (
        "review_summary",
        "rating_2_pct",
    ): "해당 별점 리뷰가 0건이면 조회 결과에서 항목이 빠짐",
    (
        "review_summary",
        "rating_3_pct",
    ): "해당 별점 리뷰가 0건이면 조회 결과에서 항목이 빠짐",
    ("product", "is_new"): "신상품이 아니면 False",
    (
        "product",
        "delisted_at",
    ): "판매 중인 상품은 공란. 증분 수집에서 목록에서 사라지면 기록",
    ("price_snapshot", "is_discount"): "할인 없으면 False",
    ("price_snapshot", "is_sold_out"): "품절 아니면 False",
}


# ───────── 출력기 ─────────
_lock = threading.Lock()
_files, _writers = {}, {}
_seen = {
    k: set()
    for k in (
        "brand",
        "supplier",
        "category",
        "ingredient",
        "survey_question",
        "survey_answer",
        "image_url",
    )
}
_ids = {"image": 0, "snapshot": 0, "summary": 0, "log": 0, "ingredient": 0}
_ingredient_id = {}


def load_state():
    """이미 적재된 CSV가 있으면 번호와 코드표를 거기서 이어받는다.
    (v21~v22는 실행할 때마다 번호를 1부터 다시 매겨, 이어받기 후 번호가 겹쳤다)"""

    def rows(name):
        path = os.path.join(OUT_DIR, f"{name}.csv")
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            return []
        csv.field_size_limit(10**8)
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def max_id(name, col):
        return max(
            (int(r[col]) for r in rows(name) if (r.get(col) or "").isdigit()), default=0
        )

    for code_tbl, col in (
        ("brand", "brand_code"),
        ("supplier", "supplier_code"),
        ("category", "category_no"),
        ("survey_question", "question_code"),
        ("survey_answer", "answer_code"),
        ("image_url", None),
    ):
        if code_tbl == "image_url":
            _seen["image_url"].update(r["image_url"] for r in rows("image_applied"))
        else:
            _seen[code_tbl].update(r[col] for r in rows(code_tbl))
    for r in rows("ingredient"):
        key = (r.get("ingredient_norm") or "").strip() or norm(r["ingredient_name"])
        _ingredient_id[key] = int(r["ingredient_id"])  # v29: norm 기준 이어받기
    _ids["ingredient"] = max(_ingredient_id.values(), default=0)
    _ids["image"] = max_id("image", "image_id")
    _ids["snapshot"] = max_id("price_snapshot", "snapshot_id")
    _ids["summary"] = max_id("review_summary", "summary_id")
    _ids["log"] = max_id("crawl_log", "log_id")
    if any(_ids.values()):
        print(
            f"[이어받기] 기존 번호에서 계속: 이미지 {_ids['image']} / 성분 {_ids['ingredient']} / "
            f"가격 {_ids['snapshot']} / 리뷰 {_ids['summary']} / 로그 {_ids['log']}"
        )


def init_out():
    os.makedirs(OUT_DIR, exist_ok=True)
    load_state()
    for name, cols in SCHEMA.items():
        path = os.path.join(OUT_DIR, f"{name}.csv")
        new = not os.path.isfile(path) or os.path.getsize(path) == 0
        f = open(path, "a", newline="", encoding="utf-8-sig")
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if new:
            w.writeheader()
        _files[name], _writers[name] = f, w


def emit(name, rows):
    if not rows:
        return
    with _lock:
        _writers[name].writerows(rows)
        _files[name].flush()


def next_id(kind):
    with _lock:
        _ids[kind] += 1
        return _ids[kind]


def ingredient_id(name):
    key = norm(name)  # v29: 표기 달라도 norm 같으면 같은 성분으로 dedup
    if not key:
        return None
    with _lock:
        if key not in _ingredient_id:
            _ids["ingredient"] += 1
            _ingredient_id[key] = _ids["ingredient"]
            _writers["ingredient"].writerow(
                {
                    "ingredient_id": _ids["ingredient"],
                    "ingredient_name": name,
                    "ingredient_norm": key,
                }
            )
            _files["ingredient"].flush()
        return _ingredient_id[key]


def once(kind, key):
    """코드 테이블에 이미 쓴 키인지. 처음이면 True"""
    with _lock:
        if key in _seen[kind]:
            return False
        _seen[kind].add(key)
        return True


# ───────── 카테고리 트리 ─────────
def category_rows(cat):
    """displayCategory → 상위부터 말단까지의 category 행 목록 + 말단 번호
    category_path 를 같이 적어 두면 '립메이크업 전체'를 재귀 쿼리 없이 LIKE로 찾을 수 있다."""
    rows, parent, leaf, names = [], "", "", []
    for depth, p in enumerate(("upper", "middle", "lower", "leaf"), 1):
        no = str(cat.get(f"{p}CategoryNumber") or cat.get(f"{p}CategoryNo") or "")
        name = cat.get(f"{p}CategoryName") or ""
        if not (no or name):
            continue
        no = no or f"NAME:{name}"  # 번호를 안 주면 이름을 키로 씀
        names.append(name)
        if once("category", no):
            rows.append(
                {
                    "category_no": no,
                    "parent_category_no": parent,
                    "depth": depth,
                    "category_name": name,
                    "category_path": " > ".join(names),
                }
            )
        parent, leaf = no, no
    return rows, leaf


# ───────── 전성분 분해 ─────────
# 전성분 원문은 '상품 단위로 한 번' 받지만 내용은 호수별로 나뉘어 있다.
#   [01 데이지] 탤크, 마이카 ...
#   [1호] 정제수, ...      /  퍼펙트트윈립#901트루피치 ㅣ 아이소도데케인, ...
# 팔레트는 한 호수 안에서 '1. ... 2. ...' 로 색상별로 또 나뉜다(합쳐서 그 호수의 성분으로 본다).
HEADER_RE = re.compile(
    r"(?m)^\s*(?:\[([^\]\n]{1,40})\]|([^\n,]{2,40}?#\s*\d+[^\n,]{0,20}?)\s*[ㅣ|\t])"
)
INGR_SPLIT = re.compile(
    r"[,\n\t·ㅣ|\[\]<>{}@]"
)  # v29: 감싸는 기호 []<>{} 도 경계 (()는 성분 일부라 제외)
BULLET_SPLIT = re.compile(
    r"[\s∙·ㆍ・•\n\t\[\]<>{}ㅣ|@]+"
)  # v29: 쉼표 없는 블록(공백/∙ 구분) 전용
# '1,2-헥산다이올' 처럼 성분명 안에 든 쉼표는 자르면 안 된다
PROTECT_MARK = "\x00"
# v31: 숫자 체인을 통짜로 찾아 쉼표를 판정한다.
# 이전 (\d)\s*,\s*(\d) 방식은 양쪽 숫자를 소비해서, '폴리솔베이트60, 1,2-헥산다이올' 처럼
# 경계 쉼표를 먼저 만나면 바로 뒤의 로칸트(1,2)를 놓치고 '2-헥산다이올' 유령 성분을 만들었다.
THOUSANDS_GROUP = re.compile(r"\d{1,3}(?:\s*,\s*\d{3})+(?!\d)")  # 함량 표기의 천 단위 구분
NUMBER_CHAIN = re.compile(r"\d{1,3}(?:\s*,\s*\d{1,3})+")  # 1,2 / 2,6 / 60,1,2
CHAIN_ATTACHED = re.compile(r"[0-9A-Za-z\uac00-\ud7a3\-]")  # 숫자가 성분명 꼬리에 붙었는지


def protect_number_commas(text):
    """성분명 안의 쉼표(로칸트·천 단위)는 보호하고 성분 경계 쉼표만 남긴다."""
    joiner = PROTECT_MARK.join
    text = THOUSANDS_GROUP.sub(
        lambda m: joiner(re.split(r"\s*,\s*", m.group(0))), text or ""
    )

    def decide(m):
        parts = re.split(r"\s*,\s*", m.group(0))
        prev = text[m.start() - 1] if m.start() else ""
        # 이름 꼬리 숫자 뒤에 로칸트가 이어지는 경우에만 첫 쉼표를 성분 경계로 본다.
        if CHAIN_ATTACHED.match(prev) and len(parts) >= 3:
            return parts[0] + "," + joiner(parts[1:])
        return joiner(parts)

    return NUMBER_CHAIN.sub(decide, text)
NUM_PREFIX = re.compile(r"^\s*\d+\s*[.)]\s*")
ILN_RE = re.compile(r"\s*ILN\s*\d+\s*", re.IGNORECASE)  # v29: ILN 관리번호 제거
CI_ANY = re.compile(
    r"\s*[\(（]\s*(?:CI|씨아이)\s*\d+[^)）]*[\)）]?\s*", re.IGNORECASE
)  # v30: CI/씨아이(한글) 괄호 제거(위치 무관)
JUNK = re.compile(r"^\s*(?:\d+\s*호?|[\d.\s]+|[-–—]+)\s*$")
# 성분이 아니라 구성품·기획 설명인 줄
NOT_INGREDIENT = re.compile(
    r"(\d+\s*(?:ml|g|호재|매|P\b)|기획|단품|퍼프|증정|본품|리필)"
)
NOTICE = re.compile(
    r"(참고|부탁|문의|드립니다|주시기|패키지|포함된\s*성분|성분\s*목록|MAY\s*CONTAIN|함유되어)",
    re.IGNORECASE,
)  # v29: 안내문구
END_SENT = re.compile(r"(다|요|니다|세요)$")  # v29: 완결 문장 종결어미
NON_INGREDIENT_EXACT = frozenset(
    {
        "전성분",
        "전성분명",
        "제품",
        "제품이라도",
        "제품에는 이상이 없습니다",
        "원료 고유의 색 함유로 시간이 지나면서 색이 옅어질 수 있으나",
        "STEP01",
        "STEP02",
    }
)


def unsafe_ingredient_chars(value):
    """Return suspicious code points without guessing their intended spelling."""
    return sorted(
        {
            f"U+{ord(char):04X}"
            for char in (value or "").strip()
            if char == "\ufffd"
            or (
                unicodedata.category(char) in {"Cc", "Cf"}
                and char not in "\r\n\t\u200b"
            )
        }
    )


def clean_notice_volume(value):
    """Render an HTML line break in a notice volume as plain text."""
    return re.sub(r"<br\s*/?>", "\n", value or "", flags=re.IGNORECASE)


def clean_ingredient(tok, on_review=None):
    if unsafe_ingredient_chars(tok):
        return ""
    m = re.search(
        r"\s-\s", tok
    )  # v30: '호수 - 성분' 머리글 글루(왼쪽이 짧은 호수명(<=15)이면 오른쪽 성분만)
    if m and len(tok[: m.start()].strip()) <= 15:
        tok = tok[m.end() :]
    n = tok.replace("\u200b", "").replace("■", "")
    n = ILN_RE.sub(" ", n)  # v29: ILN 관리번호 제거
    n = CI_ANY.sub(" ", n)  # v29: CI 괄호 제거(위치 무관)
    n = re.sub(r"^\s*\d{5,}\s+", "", n)  # v30: 바코드/관리번호 접두 제거
    n = re.sub(r"^\s*[■•▪◆※☆★∙]+\s*", "", n)  # v30: 머리 불릿 제거
    n = re.sub(r"[\(（]\s*(?:CI|씨아이)\s*$", "", n)  # v30: 댕글링 (CI/씨아이 제거
    n = NUM_PREFIX.sub("", n)
    n = n.strip(
        " \u00b7.\u302e[]<>{}\u2605\u2606*_\"'"
    )  # v29: 양끝 기호 제거(가운데 '_'는 유지)
    n = re.sub(r"\s{2,}", " ", n).strip()
    if n in NON_INGREDIENT_EXACT:
        if on_review is not None:
            on_review(n)
        return ""
    if not n or len(n) > 60 or "#" in n:
        return ""
    if ":" in n or "\uff1a" in n:  # '헬로우 스프링:' 같은 소제목 줄
        n = n.split(":")[-1].split("\uff1a")[-1].strip()
        if not n:
            return ""
    if JUNK.match(n) or not re.search(r"[\uac00-\ud7a3A-Za-z]", n):
        return ""
    if n.startswith(("-", "\u2013", "+")) or NOT_INGREDIENT.search(n):
        return ""
    if NOTICE.search(n) or (
        n.count(" ") >= 3 and END_SENT.search(n)
    ):  # v29: 안내문구(완결 문장) 제거
        return ""
    if not norm(n):  # 함량 표기만 남은 토큰은 성분이 아니다.
        return ""
    return n


def observation_version(record):
    """Content-addressed version; CSV serialization and DB IDs are not source identity."""
    payload = {k: record[k] for k in SCHEMA["option_ingredient_observation"] if k != "source_version"}
    if isinstance(payload["entries"], str):
        payload["entries"] = json.loads(payload["entries"])
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


@lru_cache(maxsize=8)
def _source_occurrences(raw):
    """Tokenize each immutable product notice once; never share mutable option entries."""
    raw = raw or ""
    heads, line_offset = [], 0
    for line in raw.splitlines(keepends=True):
        # Bound header matching; \s in the legacy regex can otherwise span thousands
        # of blank lines. Offsets still address the complete, untouched disclosure.
        leading = len(line) - len(line.lstrip())
        prefix = line[leading:leading + 512]
        marked = MARKED_HEADER_RE.match(prefix)
        header = marked or HEADER_RE.match(prefix)
        if header:
            title = header.group(1) if marked else (header.group(1) or header.group(2))
            heads.append((line_offset + leading, line_offset + leading + header.end(), title.strip()))
        line_offset += len(line)
    # Preserve all blocks, including unassigned prefixes and gifts. Never merge their entries.
    blocks = []
    cursor, label = 0, None
    for start, end, title in heads:
        if start > cursor:
            blocks.append((cursor, start, label))
        cursor, label = end, title
    blocks.append((cursor, len(raw), label))
    entries, dropped = [], False
    for block_no, (start, end, title) in enumerate(blocks, 1):
        begin, depth = start, 0
        spans = []
        for i in range(start, end):
            ch = raw[i]
            if ch in "(（":
                depth += 1
            elif ch in ")）":
                depth = max(0, depth - 1)
            decimal_comma = (ch == "," and i > start and i + 1 < end
                             and raw[i-1].isdigit() and raw[i+1].isdigit())
            if depth == 0 and ch in ",;\n\rㆍ•" and not decimal_comma:
                spans.append((begin, i))
                begin = i + 1
        spans.append((begin, end))
        for left, right in spans:
            token = raw[left:right]
            lo = left + len(token) - len(token.lstrip())
            hi = right - len(token) + len(token.rstrip())
            name = raw[lo:hi]
            if not name:
                continue
            if len(name) > 256:
                dropped = True
                continue  # Keep raw_text; oversized unresolved spans require manual review.
            clean = clean_ingredient(name)
            if not clean:
                dropped = True
                continue
            # Cleaning may identify an ingredient but never replaces its displayed source.
            dropped |= clean != name
            entries.append(dict(name=name, ingredient_norm=norm(clean), sequence=len(entries)+1,
                                block=block_no, component=title, source_start=lo, source_end=hi))
    return heads, blocks, entries, dropped


def ingredient_observation(raw, options, option, collected_at, source_url, volume=""):
    """Preserve occurrences BEFORE normalization/dedup; ambiguous ownership stays unknown.

    Positions are Unicode code-point offsets [start,end) in the unmodified raw_text.
    A shared product notice is not proof of ownership for a multi-option/set product.
    """
    raw = raw or ""
    heads, blocks, source_entries, dropped = _source_occurrences(raw)
    entries = [dict(entry) for entry in source_entries]
    composite = bool(re.search(r"세트|증정|기획|교차|묶음|본품|\+|/", str(option.get("optionName") or "") + " " + str(volume)))
    ownership = "option" if len(options) == 1 and not heads and not composite and raw else "unknown"
    # Ingredient normalization removes amounts/CI codes; it must not identify an option.
    def option_label(value):
        return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()

    exact_blocks = [i for i, (_, _, title) in enumerate(blocks, 1)
                    if title and option_label(title) == option_label(str(option.get("optionName") or "").strip("[]"))]
    exact = len(exact_blocks) == 1 and not composite
    if exact:
        entries = [e for e in entries if e["block"] == exact_blocks[0]]
        for sequence, entry in enumerate(entries, 1):
            entry["sequence"] = sequence
        ownership = "option"
    record = dict(option_id=str(option.get("goodsNumber") or "") + "-" + str(option.get("optionNumber") or ""),
                  collected_at=str(collected_at), source_url=source_url, raw_text=raw,
                  raw_sha256=hashlib.sha256(raw.encode()).hexdigest(), parser_version=OBSERVATION_VERSION,
                  ownership_status=ownership,
                  completeness="complete" if entries and not dropped and (not heads or exact) else "partial" if raw else "unknown",
                  entries=entries)
    record["source_version"] = observation_version(record)
    record["entries"] = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
    return record


def ingredient_list(text, exclude=None, on_review=None):
    """exclude: 이 상품의 옵션명·호수명(정규화). '01 웜베이지' 같은 호수 줄이 성분으로 들어가는 걸 막는다."""
    out, seen = [], set()
    text = protect_number_commas(text)
    # v29: 쉼표 없는 블록(공백/∙ 나열)은 공백 기준으로 쪼갠다(공백 없는 단일 성분명은 그대로 보존)
    toks = (
        BULLET_SPLIT.split(text)
        if ("," not in text and len(text) > 40)
        else INGR_SPLIT.split(text)
    )
    for tok in toks:
        tok = tok.replace(PROTECT_MARK, ",")
        n = clean_ingredient(tok, on_review=on_review)
        if n and exclude and norm(n) in exclude:
            continue
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


# v29: 비교 전용 정규화 (NFKC + 공백/CI/ILN/함량 제거 + 대문자). 표기만 다른 같은 성분을 합친다.
AMOUNT_N = re.compile(
    r"\s*[\(\uff08]\s*[\d.,]+\s*(?:ppm|ppb|%|iu)[^)\uff09]*[\)\uff09]", re.IGNORECASE
)
CI_N = re.compile(
    r"\s*[\(\uff08]\s*(?:CI|\uc528\uc544\uc774)\s*\d+[^)\uff09]*[\)\uff09]",
    re.IGNORECASE,
)
ILN_N = re.compile(r"[\[\<]?\s*ILN\s*\d+\s*[\]\>]?", re.IGNORECASE)


def norm(s_):
    if not s_:
        return ""
    n = unicodedata.normalize("NFKC", s_)
    n = n.replace("\u200b", "").replace("\xa0", "").replace("\u3000", "")
    n = AMOUNT_N.sub("", n)
    n = CI_N.sub("", n)
    n = ILN_N.sub("", n)
    n = re.sub(r"\s+", "", n)
    return n.upper()


def _match_block(blocks, shade, shade_name, oname):
    """호수 ↔ 블록 매칭. 느슨하게 붙으면 엉뚱한 성분이 들어가므로 우선순위를 둔다."""
    titles = [(i, norm(t)) for i, (t, _) in enumerate(blocks)]
    n_name, n_shade, n_opt = norm(shade_name), norm(shade), norm(oname)
    # 1순위: 호수명이 제목 안에 그대로 ('리본타이' ⊂ '19리본타이')
    if len(n_name) >= 2:
        for i, t in titles:
            if n_name and n_name in t:
                return i
    # 2순위: 제목이 그 호수 번호로 시작 ('01데이지' ← 호수 01 / 1)
    if n_shade.isdigit():
        want = {n_shade, n_shade.lstrip("0") or "0", n_shade.zfill(2)}
        for i, t in titles:
            m = re.match(r"^(\d+)", t)
            if m and (m.group(1) in want or (m.group(1).lstrip("0") or "0") in want):
                return i
    # 3순위: 제목이 옵션명 안에 통째로 (제목이 충분히 길 때만)
    for i, t in titles:
        if len(t) >= 4 and t in n_opt:
            return i
    return None


def plain_header_spans(raw, options):
    """v29: 옵션 호수(코드+이름) 기반 평문 머리글 위치 감지(브래킷/'#' 외). 그 상품 자기 옵션 기준이라 오탐이 적다."""
    name_pats, codes = [], set()
    for o in options:
        shade, name = oy.split_hosu(o.get("optionName", ""))
        code = (shade or "").strip()
        name = (name or "").strip()
        nnorm = norm(name)
        if code:
            codes.add(code.lstrip("0") or code)
        if name and len(nnorm) >= 2:
            namep = re.escape(name).replace("\\ ", r"\s*")
            if code:
                codep = r"0*" + re.escape(code.lstrip("0") or code)
                name_pats.append(
                    (
                        re.compile(
                            r"^([^,\n]{0,40}?(?<![0-9A-Za-z])"
                            + codep
                            + r"(?![0-9])[^,\n]{0,25}?"
                            + namep
                            + r"[)\]]?)(?=[\s,)\]]|$)"
                        ),
                        True,
                    )
                )
            elif len(nnorm) >= 3:
                name_pats.append(
                    (
                        re.compile(
                            r"^([^,\n]{0,40}?" + namep + r"[)\]]?)(?=[\s,)\]]|$)"
                        ),
                        False,
                    )
                )
    code_pat = None
    if codes:
        alt = "|".join(sorted((re.escape(c) for c in codes), key=len, reverse=True))
        code_pat = re.compile(
            r"^([^,\n]{0,20}?(?<![0-9A-Za-z])0*(?:"
            + alt
            + r")(?![0-9])\s+\S[^,\n]{0,30})$"
        )
    spans, pos = [], 0
    for line in raw.split("\n"):
        ln_start = pos
        pos += len(line) + 1
        best = None
        for pat, has_code in name_pats:
            m = pat.match(line)
            if m:
                L = len(m.group(1))
                key = (2 if has_code else 1, -L)
                if best is None or key > best[0]:
                    best = (key, L)
        if (
            best is None
            and code_pat
            and line.count(",") == 0
            and len(line.strip()) < 50
        ):
            if code_pat.match(line.strip()):
                spans.append((ln_start, ln_start + len(line.strip()), line.strip()))
                continue
        if best:
            spans.append((ln_start, ln_start + best[1], line[: best[1]].strip()))
    return spans


MARKED_HEADER_RE = re.compile(r"■{2,}\s*([^■\r\n]{1,80}?)\s*■{2,}")


def marked_ingredient_blocks(raw, options, on_review=None):
    """명시적인 ■■■호수■■■ 구획을 먼저 읽는다. 불명확한 호수는 연결하지 않는다."""
    heads = list(MARKED_HEADER_RE.finditer(raw or ""))
    if not heads:
        return None
    blocks = []
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(raw)
        blocks.append(
            (
                head.group(1).strip(),
                ingredient_list(raw[head.end() : end], on_review=on_review),
            )
        )
    result, issues = {}, []
    used = set()
    for option in options:
        no = str(option.get("optionNumber") or "")
        label = str(option.get("optionName") or "")
        shade, shade_name = oy.split_hosu(label)
        # 세트/교차 옵션은 여러 구성품을 품을 수 있으므로 단일 호수로 추정하지 않는다.
        if re.search(r"교차|세트|묶음|1\s*\+\s*1|\+", label):
            issues.append(f"{no}: 구성품이 여러 개일 수 있어 성분 연결 보류")
            continue
        normalized_name = norm(shade_name)
        normalized_no = (shade or "").lstrip("0") or "0"
        matches = []
        for i, (title, items) in enumerate(blocks):
            m = re.match(r"^\s*0*(\d+)\s*호?\s*(.*)$", title)
            if not m or not normalized_name or len(items) < 1:
                continue
            title_no = m.group(1).lstrip("0") or "0"
            title_name = norm(m.group(2))
            if title_no == normalized_no and title_name == normalized_name:
                matches.append(i)
        if len(matches) == 1:
            result[no] = blocks[matches[0]][1]
            used.add(matches[0])
        else:
            issues.append(f"{no}: 명시적 호수 구획과 1:1 대응하지 않음")
    if raw[: heads[0].start()].strip():
        issues.append("첫 번째 호수 구획 앞의 전성분 텍스트 검토 필요")
    for i, (title, _) in enumerate(blocks):
        if i not in used:
            issues.append(f"구획 {title}: 대응 옵션 없음")
    return result, [], issues


def split_shade_ingredients(raw, options, on_review=None):
    """전성분 원문 → ({optionNumber: [성분...]}, 공통성분)
    원문에 호수 구분이 없으면 공통 목록 하나를 모든 호수가 함께 쓴다.
    해당 호수의 전성분이 아예 안 적혀 있으면 그 호수는 비워 둔다(추측하지 않음)."""
    if not raw:
        return {}, []
    marked = marked_ingredient_blocks(raw, options, on_review=on_review)
    if marked is not None:
        return marked[0], marked[1]
    exclude = set()
    for o in options:
        oname = o.get("optionName", "")
        shade, shade_name = oy.split_hosu(oname)
        for x in (oname, shade_name, f"{shade}{shade_name}", f"{shade} {shade_name}"):
            if norm(x):
                exclude.add(norm(x))
    heads = [
        (m.start(), m.end(), (m.group(1) or m.group(2) or "").strip())
        for m in HEADER_RE.finditer(raw)
    ]
    if (
        len(options) >= 2
    ):  # v29: 호수 2개 이상일 때만 평문 머리글 교정(1-옵션은 무변경→무회귀)
        br = [(s0, e0) for s0, e0, _ in heads]
        for s0, e0, t in plain_header_spans(raw, options):
            if any(not (e0 <= bs or s0 >= be) for bs, be in br):
                continue
            heads.append((s0, e0, t))
        heads.sort(key=lambda x: x[0])
    if not heads:
        return {}, ingredient_list(raw, exclude, on_review=on_review)
    # v30: 듀오밤 등 '호수 > 제형' 2단 구조 — [촉촉]/[벨벳] 같은 제형 서브헤더는
    #      직전 호수 머리글에 성분을 합친다(앞에 호수 머리글이 있을 때만). 매트/글로시를
    #      별도 호수로 파는 상품은 독립 블록으로 둬(오판 방지).
    FINISH_WORDS = {
        "촉촉",
        "벨벳",
        "매트",
        "글로시",
        "시스루",
        "크리미",
        "쉬머",
        "펄",
        "사틴",
        "글리터",
        "무광",
        "유광",
        "크림",
        "윤광",
        "물광",
        "세미매트",
    }
    blocks = []  # [title, items]
    cur_shade = None  # 직전 '비-finish(호수)' 머리글 index
    for i, (s0, e0, title) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(raw)
        items = ingredient_list(raw[e0:end], exclude, on_review=on_review)
        is_finish = re.sub(r"[\[\]\s]+", "", title) in FINISH_WORDS
        if is_finish and cur_shade is not None:
            seen = set(blocks[cur_shade][1])
            blocks[cur_shade][1].extend(x for x in items if x not in seen)
        else:
            blocks.append([title, items])
            if not is_finish:
                cur_shade = len(blocks) - 1
    blocks = [(t, it) for t, it in blocks if t and len(it) >= 3]
    if not blocks:
        return {}, ingredient_list(raw, exclude, on_review=on_review)

    result = {}
    for o in options:
        shade, shade_name = oy.split_hosu(o.get("optionName", ""))
        idx = _match_block(blocks, shade, shade_name, o.get("optionName", ""))
        if idx is not None:
            result[o.get("optionNumber", "")] = blocks[idx][1]
    # 블록이 하나고 그걸 어느 호수도 집어가지 않았을 때만 '공통 전성분'으로 본다.
    # (어떤 호수가 가져갔다면 그건 그 호수 전용이므로 다른 호수에 붙이면 안 된다)
    common = blocks[0][1] if (len(blocks) == 1 and not result) else []
    return result, common


# ───────── 판정 근거 → 단계 코드 ─────────
def judge_step(reason):
    if not reason:
        return "none"
    if reason.startswith("제형 축 비해당"):
        return "not_applicable"
    if reason.startswith("상품명"):
        return "product_name"
    if reason.startswith("리뷰 언급"):
        return "review_ai"
    if "설문" in reason or "리뷰" in reason:
        return "review_survey"
    return "none"


def color_method(source):
    if not source:
        return "none"
    if "같은 호수" in source:
        return "same_shade"
    if "펜슬" in source:
        return "pencil_tip"
    if "컬러칩 방식" in source:
        return "color_chip"
    if "스와치 방식" in source:
        return "swatch"
    return "none"


# ───────── 상품 1개 → 모든 테이블 행 ─────────
def collect(mid_name, goods_no, run_id, image_pool):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    url = f"{BASE}/m/goods/getGoodsDetail.do?goodsNo={goods_no}"
    oy._product_thread.cache = {}
    oy._product_thread.errors = {}
    oy._product_thread.review_cache = {}  # 상품마다 리뷰 캐시 초기화
    oy._product_thread.image_pool = image_pool

    resp = oy.get(url)
    html = resp.text
    g = _enrich_extract(oy.next_data_text(html))
    d = oy.parse_detail(html, goods_no)
    oy.require_product_json(resp, g)

    options = []
    seen_opt = set()
    for o in g.get("options") or []:
        if o.get("goodsNumber") == goods_no and o.get("optionNumber") not in seen_opt:
            seen_opt.add(o.get("optionNumber"))
            options.append(o)
    # 호수가 없는 단일상품도 가격·전성분·이미지를 매달 자리가 필요하므로
    # 상품 자체를 옵션 1개처럼 취급한다 (option_no = 000)
    if not options:
        options = [
            {
                "optionNumber": "000",
                "optionName": "단일상품(옵션없음)",
                "standardCode": g.get("standardCode", ""),
                "sortSeq": 1,
                "representFlag": True,
                "soldOutFlag": g.get("soldOutFlag", ""),
                "salePrice": g.get("salePrice", ""),
                "finalPrice": g.get("finalPrice", ""),
                "maxBenefitPrice": g.get("maxBenefitPrice", ""),
            }
        ]

    out = {k: [] for k in SCHEMA}
    logs = []

    def log(step, status, msg="", code=""):
        logs.append(
            {
                "log_id": next_id("log"),
                "run_id": run_id,
                "goods_no": goods_no,
                "step": step,
                "http_status": code,
                "status": status,
                "error_message": msg,
                "logged_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

    # ── brand / supplier / category / product ──────────────────
    bc = g.get("onlineBrand") or ""
    if bc and once("brand", bc):
        out["brand"].append(
            {
                "brand_code": bc,
                "brand_name_ko": g.get("onlineBrandName", ""),
                "brand_name_en": g.get("onlineBrandEngName", ""),
            }
        )
    sc = g.get("supplier") or ""
    if sc and once("supplier", sc):
        out["supplier"].append(
            {"supplier_code": sc, "supplier_name": g.get("supplierName", "")}
        )

    cats, leaf_no = category_rows(g.get("displayCategory") or {})
    out["category"] += cats
    std = g.get("standardCategory") or {}
    out["product"].append(
        {
            "goods_no": goods_no,
            "brand_code": bc,
            "supplier_code": sc,
            "category_no": leaf_no,
            "std_category_code": std.get("lowerCategoryNumber")
            or std.get("lowerCategoryName", ""),
            "goods_name": g.get("goodsName") or d["name"],
            "product_url": url,
            "sale_status": g.get("statusName", ""),
            "is_new": g.get("flags", {}).get("newGoodsFlag", ""),
            "registered_at": g.get("registeredDate", ""),
            "modified_at": g.get("modifiedDate", ""),
            "first_collected_at": now,
            "last_collected_at": now,
            "delisted_at": "",
        }
    )
    log("detail", "success", code=resp.status_code)

    # ── 제공고시 + 전성분 ──────────────────────────────────────
    notice = {}
    try:
        notice, code = _enrich_notice(goods_no, options)
        log("notice", "success", code=code)
    except oy.RateLimited:
        raise
    except Exception as e:
        log("notice", "fail", str(e)[:200])
    notice["volume"] = clean_notice_volume(notice.get("volume"))
    notice["goods_no"] = goods_no
    notice["collected_at"] = now
    out["product_notice"].append(notice)

    ingredients_raw = notice.get("ingredients_raw", "")
    dropped_non_ingredients = set()
    unsafe_chars = unsafe_ingredient_chars(ingredients_raw)
    if unsafe_chars:
        log(
            "ingredient_parse_review",
            "review",
            f"전성분 원문에 깨진/숨은 문자 포함: {', '.join(unsafe_chars)}; 해당 성분 토큰 연결 보류",
        )
    marked = marked_ingredient_blocks(
        ingredients_raw, options, on_review=dropped_non_ingredients.add
    )
    if "■" in ingredients_raw and marked is None:
        per_shade, common = {}, []
        log(
            "ingredient_parse_review",
            "review",
            "표시 문자의 구획을 판별할 수 없어 성분 연결 보류",
        )
    else:
        per_shade, common = split_shade_ingredients(
            ingredients_raw, options, on_review=dropped_non_ingredients.add
        )
    for dropped in sorted(dropped_non_ingredients):
        log(
            "ingredient_parse_review",
            "review",
            f"독립된 비성분 문구 자동 제외: {dropped}",
        )
    if marked:
        for issue in marked[2]:
            log("ingredient_parse_review", "review", issue[:300])

    # ── 제형 ──────────────────────────────────────────────────
    rule = oy.item_rule(mid_name, d["sub_cat"], d["name"])
    if rule in oy.TEXTURE_SKIP:
        texture, reason = "", "제형 축 비해당 (브로우·라이너·마스카라)"
    else:
        try:
            texture, reason = oy.judge_texture(goods_no, d["name"])
        except oy.RateLimited:
            raise
        except Exception as e:
            texture, reason = "", f"판정 불가 ({e})"
    out["product_texture"].append(
        {
            "goods_no": goods_no,
            "texture_code": texture,
            "judge_step": judge_step(reason),
            "judge_reason": reason,
            "collected_at": now,
        }
    )

    # ── 이미지 (URL만. applied_type 은 별도 패스) ─────────────
    img_id_of = {}

    def add_image(option_id, itype, iurl, seq):
        iurl = (iurl or "").strip()
        if not iurl or iurl in img_id_of:
            return
        iid = next_id("image")
        img_id_of[iurl] = iid
        out["image"].append(
            {
                "image_id": iid,
                "goods_no": goods_no,
                "option_id": option_id,
                "image_type": itype,
                "image_url": iurl,
                "sort_seq": seq,
                "collected_at": now,
            }
        )
        # 같은 URL이 다른 상품에도 쓰이므로 판정 자리는 URL당 한 줄만 만든다
        if once("image_url", iurl):
            out["image_applied"].append(
                {
                    "image_url": iurl,
                    "image_type": itype,
                    "applied_type": "",
                    "applied_conf": "",
                    "judged_at": "",
                }
            )

    for i, th in enumerate(g.get("thumbnailImage") or [], 1):
        add_image(
            "", "thumbnail", (th.get("url", "") + th.get("path", "")).split("?")[0], i
        )
    for o in options:
        oid = f"{goods_no}-{o.get('optionNumber', '')}"
        for key, itype in (
            ("colorChipImage", "color_chip"),
            ("colorCompareImage", "color_compare"),
            ("optionImage", "option"),
        ):
            add_image(oid, itype, oy.image_url(o, key), o.get("sortSeq", ""))
    try:
        desc_urls, code = _enrich_desc_images(goods_no)
        for i, u in enumerate(desc_urls, 1):
            add_image("", "description", u, i)
        log("description", "success", code=code)
    except oy.RateLimited:
        raise
    except Exception as e:
        log("description", "fail", str(e)[:200])

    # ── 옵션 / 가격 / 색 ──────────────────────────────────────
    is_palette = "팔레트" in d["name"]
    det_opts = d["options"] or []
    users = {}
    for o in det_opts:
        hosu, _ = oy.split_hosu(o.get("optionName", ""))
        for u in oy.candidates(o, rule):
            users.setdefault(u, set()).add(hosu or o.get("optionName", ""))
    shared = {u for u, who in users.items() if len(who) >= 2}
    if not is_palette:
        try:
            oy.prefetch_images(det_opts, shared, rule, image_pool)
        except oy.RateLimited:
            raise
        except Exception:
            pass

    colors = {}
    for o in det_opts:
        key = o.get("optionName", "")
        if is_palette:
            colors[key] = (
                None,
                next(iter(oy.candidates(o)), ""),
                "팔레트(여러 색) – 대표색 1개로 표현 불가",
                0.0,
            )
            continue
        try:
            if rule == "mascara":
                colors[key] = oy.mascara_color(o, shared)
            else:
                r = oy.best_color(o, shared, rule)
                if rule == "line" and not r[0]:
                    r = (
                        r[0],
                        r[1],
                        f"브로우·라이너 – 발색(그은 선) 없음 / {r[2]}",
                        r[3],
                    )
                colors[key] = r
        except oy.RateLimited:
            raise
        except Exception as e:
            colors[key] = (None, "", f"이미지 오류: {e}", 0.0)
    log("color", "success", code=200)

    # ── 발린 사진 판정 (색 추출 때 받아 둔 이미지로만, 추가 요청 없음) ──
    cache, _errors = oy.product_images()
    jnow = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for row in out["image_applied"]:
        itype, iurl = row.pop("image_type", ""), row["image_url"]
        if (
            itype in judge.RULE_TYPES
            and itype not in judge.COMPUTE_TYPES
            and itype != "color_chip"
        ):
            row.update(applied_type=judge.RULE_TYPES[itype], judged_at=jnow)  # 썸네일
            continue
        raw = cache.get(iurl)
        if raw is None:
            continue  # 받지 않은 이미지(세트 사진 · 팔레트 · 상세설명) → 공란
        try:
            m = judge.measure(oy.open_rgb(raw))
            t, conf = judge.decide(*m)
            row.update(applied_type=t, applied_conf=conf, judged_at=jnow)
        except Exception:
            pass

    for o in options:
        no = o.get("optionNumber", "")
        oid = f"{goods_no}-{no}"
        oname = o.get("optionName", "")
        shade, shade_name = oy.split_hosu(oname)
        out["product_option"].append(
            {
                "option_id": oid,
                "goods_no": goods_no,
                "option_no": no,
                "barcode": o.get("standardCode", ""),
                "option_name": oname,
                "shade_code": shade,
                "shade_name": shade_name,
                "sort_seq": o.get("sortSeq", ""),
                "is_representative": o.get("representFlag", ""),
                "collected_at": now,
            }
        )
        out["option_ingredient_observation"].append(
            ingredient_observation(
                ingredients_raw, options, dict(o, goodsNumber=goods_no), now,
                out["product"][0].get("product_url") or "",
                notice.get("volume") or "",
            )
        )
        added = set()  # v29: (option,ingredient) 유일성
        for seq, iname in enumerate(per_shade.get(no) or common, 1):
            ing_id = ingredient_id(iname)
            if ing_id and ing_id not in added:
                added.add(ing_id)
                out["option_ingredient"].append(
                    {"option_id": oid, "ingredient_id": ing_id, "seq": seq}
                )
        lp, sp = o.get("salePrice", ""), o.get("finalPrice", "")
        out["price_snapshot"].append(
            {
                "snapshot_id": next_id("snapshot"),
                "option_id": oid,
                "list_price": lp,
                "sale_price": sp,
                "max_benefit_price": o.get("maxBenefitPrice", ""),
                "is_discount": (str(lp) != str(sp)) if (lp and sp) else "",
                "is_sold_out": o.get("soldOutFlag", ""),
                "is_latest": True,
                "collected_at": now,
            }
        )

        rgb, iurl, source, conf = colors.get(oname, (None, "", "옵션 매칭 실패", 0.0))
        hexv, lab = "", ("", "", "")
        if rgb:
            hexv = "#%02X%02X%02X" % tuple(round(c) for c in rgb)
            lab = oy.to_lab(rgb)
        out["option_color"].append(
            {
                "option_id": oid,
                "collected_at": now,
                "hex_code": hexv,
                "lab_l": lab[0],
                "lab_a": lab[1],
                "lab_b": lab[2],
                "color_method": color_method(source) if rgb else "none",
                "color_image_id": img_id_of.get(iurl, "") if rgb else "",
                "color_confidence": round(conf, 3) if rgb else "",
                "color_note": "" if rgb else source,
                "run_id": run_id,
                "is_confirmed": "",
            }
        )

    # ── 리뷰 ──────────────────────────────────────────────────
    summary, stats = {}, {}
    try:
        summary = oy.review_json(f"v1/reviews/{goods_no}/summary", goods_no) or {}
    except oy.RateLimited:
        raise
    except Exception as e:
        log("review_summary", "fail", str(e)[:200])
    try:
        stats = oy.review_json(f"v2/reviews/{goods_no}/stats", goods_no) or {}
        log("review_stats", "success", code=200)
    except oy.RateLimited:
        raise
    except Exception as e:
        log("review_stats", "fail", str(e)[:200])

    dist = stats.get("ratingDistribution") or {}
    pct = {
        d_.get("rating"): d_.get("percentage")
        for d_ in (dist.get("ratingStatDtos") or [])
    }
    if summary or stats:
        out["review_summary"].append(
            {
                "summary_id": next_id("summary"),
                "goods_no": goods_no,
                "review_count": stats.get("reviewCount", ""),
                "rating_avg": dist.get("averageRating", ""),
                "rating_5_pct": pct.get(5, ""),
                "rating_4_pct": pct.get(4, ""),
                "rating_3_pct": pct.get(3, ""),
                "rating_2_pct": pct.get(2, ""),
                "rating_1_pct": pct.get(1, ""),
                "ai_positive_ratio": summary.get("positiveRatio", ""),
                "ai_negative_ratio": summary.get("negativeRatio", ""),
                "is_latest": True,
                "collected_at": now,
            }
        )
    for i in (1, 2, 3):
        t = summary.get(f"feature{i}Title")
        if t:
            out["review_ai_feature"].append(
                {
                    "goods_no": goods_no,
                    "seq": i,
                    "title": t,
                    "description": summary.get(f"feature{i}Description", ""),
                    "collected_at": now,
                }
            )
    for q in stats.get("satisfactionStats") or []:
        qc = q.get("questionCode", "")
        if qc and once("survey_question", qc):
            out["survey_question"].append(
                {"question_code": qc, "question_name": q.get("questionName", "")}
            )
        for a in q.get("answerDtos") or []:
            ac = a.get("answerCode", "")
            if ac and once("survey_answer", ac):
                out["survey_answer"].append(
                    {
                        "answer_code": ac,
                        "question_code": qc,
                        "answer_name": a.get("answerName", ""),
                    }
                )
            out["review_survey"].append(
                {
                    "goods_no": goods_no,
                    "answer_code": ac,
                    "percentage": a.get("answerPercentage", ""),
                    "collected_at": now,
                }
            )

    out["crawl_log"] = logs
    return out


# v15 에서 검증된 추출기 재사용 (이름만 가져옴)
def _enrich_extract(txt):
    i = txt.find('"saleableFlag"')
    if i < 0:
        return {}
    start = txt.rfind("{", 0, i)
    depth, in_str, k = 0, False, start
    while k < len(txt):
        c = txt[k]
        if in_str:
            if c == "\\":
                k += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
            if depth == 0:
                break
        k += 1
    try:
        return json.loads(txt[start : k + 1])
    except ValueError:
        return {}


NOTICE_MAP = {
    "내용물의 용량 또는 중량": "volume",
    "제품 주요 사양": "main_spec",
    "사용기한(또는 개봉 후 사용기간)": "shelf_life",
    "사용방법": "usage_guide",
    "화장품제조업자,화장품책임판매업자 및 맞춤형화장품판매업자": "manufacturer",
    "제조국": "origin_country",
}
INGREDIENT_TITLE = "화장품법에 따라 기재해야 하는 모든 성분"


def _enrich_notice(goods_no, options):
    body = {
        "goodsNumber": goods_no,
        "liquorFlag": False,
        "goodsOptionInfoList": [
            {
                "standardCode": o.get("standardCode", ""),
                "optionName": o.get("optionName", ""),
            }
            for o in options
        ],
    }
    r = oy.request(
        "POST",
        f"{BASE}/goods/api/v1/article",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": f"{BASE}/m/goods/getGoodsDetail.do?goodsNo={goods_no}",
        },
        json=body,
    )
    data = (r.json() or {}).get("data") or {}
    out, extra = {}, {}
    for block in data.get("articleInfoList") or []:
        for item in block.get("items") or []:
            title, content = item.get("title", ""), item.get("content", "")
            if title == INGREDIENT_TITLE:
                out["ingredients_raw"] = content
            elif title in NOTICE_MAP:
                out[NOTICE_MAP[title]] = content
            elif title:
                extra[title] = content
    out["notice_extra"] = json.dumps(extra, ensure_ascii=False) if extra else ""
    return out, r.status_code


IMG_SRC_RE = re.compile(
    r'(?:data-src|src)\s*=\s*"(https://[^"]+?\.(?:jpg|jpeg|png|gif|webp)(?:\?[^"]*)?)"',
    re.IGNORECASE,
)


def _enrich_desc_images(goods_no):
    r = oy.get(f"{BASE}/goods/api/v1/description?goodsNumber={goods_no}")
    html = ((r.json() or {}).get("data") or {}).get("descriptionContents") or ""
    seen, urls = set(), []
    for m in IMG_SRC_RE.finditer(html):
        u = m.group(1).split("?")[0]
        if u not in seen:
            seen.add(u)
            urls.append(u)
    return urls, r.status_code


# ───────── 리포트 ─────────
def write_report(run_id, started, targets, done, failed):
    lines = []

    def P(s=""):
        lines.append(s)
        print(s)

    P("=" * 72)
    P("올리브영 ERD 수집 가능성 테스트 리포트")
    P("=" * 72)
    P(f"실행 ID {run_id} | 스크립트 {SCRIPT_VERSION} | {datetime.now():%Y-%m-%d %H:%M}")
    P(
        f"대상 상품 {targets}개 (중분류별 표본 {SAMPLE_PER_CATEGORY or '전체'})"
        f" | 성공 {done} | 실패 {failed} | 소요 {oy.fmt_dur(time.time() - started)}"
    )
    P()

    verdict = {"다 모임": [], "일부만": [], "못 모음": []}
    for name, cols in SCHEMA.items():
        path = os.path.join(OUT_DIR, f"{name}.csv")
        rows = []
        if os.path.isfile(path):
            with open(path, encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
        P("─" * 72)
        P(f"[{name}]  {len(rows)}행")
        if not rows:
            P("   (행 없음)")
            verdict["못 모음"].append(name)
            continue
        worst = "다 모임"
        for c in cols:
            n = sum(1 for r in rows if (r.get(c) or "").strip() != "")
            rate = n / len(rows) * 100
            note = EXPECTED_BLANK.get((name, c), "")
            if rate == 100:
                mark = "OK  "
            elif note:
                mark = "예상"
            elif rate == 0:
                mark = "없음"
                worst = "못 모음"
            else:
                mark = "일부"
                worst = "일부만" if worst == "다 모임" else worst
            P(f"   {mark} {c:<22} {n:>6}/{len(rows):<6} {rate:5.1f}%  {note}")
        verdict[worst].append(name)

    P("─" * 72)
    P()
    P("■ 결론")
    for k in ("다 모임", "일부만", "못 모음"):
        P(f"   {k}: {', '.join(verdict[k]) or '-'}")
    P()
    P("  * '예상' 표시는 비어 있는 게 정상인 칸입니다 (사유는 오른쪽에).")
    P("  * texture_type 의 ar_gloss / ar_matte 는 수집 대상이 아니라")
    P("    AR 렌더링에서 쓸 수치라서 팀이 직접 정해 채워야 합니다.")

    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n리포트 저장: {REPORT}")


# ───────── 메인 ─────────
def load_done():
    if not os.path.isfile(DONE_LOG):
        return set()
    with open(DONE_LOG, encoding="utf-8") as f:
        return {l.strip() for l in f if l.strip()}


def main():
    init_out()
    run_id = int(time.time())
    started = time.time()
    emit(
        "crawl_run",
        [
            {
                "run_id": run_id,
                "script_version": SCRIPT_VERSION,
                "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "finished_at": "",
                "status": "running",
            }
        ],
    )
    emit("texture_type", TEXTURE_TYPE_ROWS)

    jobs = []
    for mid_name, cat_no in oy.TARGETS.items():
        goods = oy.list_goods(cat_no, SAMPLE_PER_CATEGORY)
        jobs += [(mid_name, no) for no in goods]
        print(f"[{mid_name}] 상품 {len(goods)}개")
    # 같은 상품이 두 중분류 목록에 동시에 걸리는 경우가 있어(예: 립틴트가 아이 목록에도 노출) 1번만 수집
    seen_goods, uniq = set(), []
    for j in jobs:
        if j[1] not in seen_goods:
            seen_goods.add(j[1])
            uniq.append(j)
    jobs = uniq
    done_set = load_done()
    jobs = [j for j in jobs if j[1] not in done_set]
    print(f"\n총 {len(jobs)}개 수집 시작 (작업자 {WORKERS})\n")

    image_pool = ThreadPoolExecutor(max_workers=oy.IMAGE_WORKERS)
    pool = ThreadPoolExecutor(max_workers=WORKERS)
    futures = {pool.submit(collect, m, n, run_id, image_pool): (m, n) for m, n in jobs}
    done = failed = 0
    with open(DONE_LOG, "a", encoding="utf-8") as journal:
        for i, (fut, (m, n)) in enumerate(futures.items(), 1):
            try:
                out = fut.result()
            except oy.RateLimited as e:
                print(f"중단: {e}")
                break
            except Exception as e:
                failed += 1
                emit(
                    "crawl_log",
                    [
                        {
                            "log_id": next_id("log"),
                            "run_id": run_id,
                            "goods_no": n,
                            "step": "product",
                            "http_status": "",
                            "status": "fail",
                            "error_message": str(e)[:300],
                            "logged_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        }
                    ],
                )
                print(f"   {i:03d}/{len(jobs)} [{m}] {n} 실패: {str(e)[:90]}")
                continue
            for name, rows in out.items():
                emit(name, rows)
            journal.write(n + "\n")
            journal.flush()
            done += 1
            nhex = sum(1 for r in out["option_color"] if r["hex_code"])
            print(
                f"   {i:03d}/{len(jobs)} [{m}] {n} {out['product'][0]['goods_name'][:24]} → "
                f"옵션 {len(out['product_option'])} / HEX {nhex} / 성분 {len(out['option_ingredient'])} / "
                f"이미지 {len(out['image'])}"
            )
    pool.shutdown(wait=False)

    # crawl_run 마무리
    path = os.path.join(OUT_DIR, "crawl_run.csv")
    _files["crawl_run"].flush()
    with open(path, encoding="utf-8-sig", newline="") as f:
        runs = list(csv.DictReader(f))
    for r in runs:
        if r["run_id"] == str(run_id):
            r["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            r["status"] = "done" if not failed else f"done({failed} 실패)"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SCHEMA["crawl_run"])
        w.writeheader()
        w.writerows(runs)

    print()
    write_report(run_id, started, len(jobs), done, failed)
    for f in _files.values():
        try:
            f.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
