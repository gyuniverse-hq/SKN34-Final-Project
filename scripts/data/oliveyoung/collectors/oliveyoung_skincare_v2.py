"""
스킨케어 전체 수집 v2 — 올리브영 스킨케어 · 마스크팩 · 클렌징 · 선케어 (디바이스 제외 22개 소분류)

- 메이크업 v30(oliveyoung_erd_v30.py)의 성분 전처리와 테이블 · 컬럼을 사용한다
    · 메이크업 전용 4개 테이블(option_color, texture_type, product_texture, image_applied)은 만들지 않음
    · 스킨케어 전용 skincare_attr 1개 추가
- CSV 번호는 수집 폴더 안에서만 사용하며 DB 적재 시 기존 성분·이미지 ID에 맞춰 재연결한다
- 결과: out_skincare_v2/ 안에 테이블별 CSV + 수집가능성_리포트.txt
- 중간에 끊겨도 다시 실행하면 _done.log 기준으로 이어서 수집

실행: collect_load_skincare.py를 사용한다
"""

import csv
import os
import re
import sys
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import oliveyoung_color_poc16 as oy
import oliveyoung_erd_v30 as base

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT_VERSION = "skincare-v2.1"
SAMPLE_TOTAL = (
    None  # None = 소분류별 전체 상품. 숫자를 넣으면 소분류당 그 개수까지만 (시험용)
)
WORKERS = 10  # 차단(403)이 잦으면 6~8로 낮춤

# 중분류 > 소분류 : 카테고리 번호 (올리브영 모바일 카테고리관에서 확인, 2026.10.26)
#   오른쪽 주석 = 확인 시점 상품 수 (총 5,720개, 중분류 간 중복 노출 가능)
#   디바이스 2종(스킨케어 디바이스 100000100010018, 클렌징 디바이스 100000100100009)은 화장품이 아니라 제외
TARGETS = OrderedDict(
    [
        ("스킨케어 > 스킨/토너", "100000100010013"),  # 370
        ("스킨케어 > 에센스/세럼/앰플", "100000100010014"),  # 924
        ("스킨케어 > 크림", "100000100010015"),  # 775 (크림·아이크림)
        ("스킨케어 > 로션", "100000100010016"),  # 283 (로션·올인원)
        ("스킨케어 > 미스트/오일", "100000100010010"),  # 173
        ("스킨케어 > 스킨케어세트", "100000100010017"),  # 101
        ("마스크팩 > 시트팩", "100000100090001"),  # 590
        ("마스크팩 > 패드", "100000100090004"),  # 216
        ("마스크팩 > 페이셜팩", "100000100090002"),  # 220
        ("마스크팩 > 코팩", "100000100090005"),  # 32
        ("마스크팩 > 패치", "100000100090006"),  # 42
        ("클렌징 > 클렌징폼/젤", "100000100100001"),  # 552
        ("클렌징 > 오일/밤", "100000100100004"),  # 242
        ("클렌징 > 워터/밀크", "100000100100005"),  # 110
        ("클렌징 > 필링&스크럽", "100000100100007"),  # 123
        ("클렌징 > 티슈/패드", "100000100100008"),  # 51
        ("클렌징 > 립&아이리무버", "100000100100006"),  # 46
        ("선케어 > 선크림", "100000100110006"),  # 572
        ("선케어 > 선스틱", "100000100110003"),  # 112
        ("선케어 > 선쿠션", "100000100110004"),  # 43 (선쿠션·선파우더)
        ("선케어 > 선스프레이/선패치", "100000100110005"),  # 30
        ("선케어 > 태닝/애프터선", "100000100110002"),  # 24
    ]
)
# 상위 번호(전체 수집 때 참고): 스킨케어 10000010001 / 마스크팩 10000010009 / 클렌징 10000010010 / 선케어 10000010011

# ───────── 출력 테이블 (v30 에서 메이크업 전용 4개 제외 + skincare_attr 추가) ─────────
DROP = {"option_color", "texture_type", "product_texture", "image_applied"}
SCHEMA = OrderedDict((k, v) for k, v in base.SCHEMA.items() if k not in DROP)
SCHEMA["skincare_attr"] = [
    "goods_no",
    "is_functional",
    "functional_types",
    "functional_raw",
    "skin_types",
    "skin_type_raw",
    "spf",
    "pa",
    "collected_at",
]

EXPECTED_BLANK = {k: v for k, v in base.EXPECTED_BLANK.items() if k[0] not in DROP}
EXPECTED_BLANK.update(
    {
        (
            "product_option",
            "shade_code",
        ): "스킨케어 옵션은 대부분 용량·기획세트라 호수가 없음",
        (
            "product_option",
            "shade_name",
        ): "스킨케어 옵션은 대부분 용량·기획세트라 호수가 없음",
        (
            "skincare_attr",
            "functional_types",
        ): "기능성이 아니거나, 상품명·사양·사용법에 기능 문구가 없으면 공란 (식약처 API로 보완 예정)",
        ("skincare_attr", "spf"): "선케어 외 제품은 대부분 공란",
        ("skincare_attr", "pa"): "선케어 외 제품은 대부분 공란",
        ("skincare_attr", "skin_types"): "피부 타입 표기가 없는 제품은 공란",
    }
)

# v30 모듈의 출력 위치·스키마를 이 스크립트 것으로 바꿔 끼운다
OUT_DIR = os.path.join(HERE, "out_skincare_v2")
base.OUT_DIR = OUT_DIR
base.DONE_LOG = os.path.join(OUT_DIR, "_done.log")
base.REPORT = os.path.join(OUT_DIR, "수집가능성_리포트.txt")
base.SCHEMA = SCHEMA
BASE = oy.BASE

# ───────── 스킨케어 전용 판정 ─────────
FUNCTIONAL_KEY = "기능성 화장품 식품의약품안전처 심사필 여부"
FUNC_WORDS = OrderedDict(
    [
        ("미백", r"미백|브라이트닝|멜라닌"),
        ("주름개선", r"주름"),
        ("자외선차단", r"자외선|SPF|선\s*크림"),
        ("여드름완화", r"여드름"),
        ("피부장벽(아토피)", r"아토피|장벽|가려움"),
        ("탈모완화", r"탈모"),
        ("튼살완화", r"튼살"),
    ]
)
SKIN_WORDS = OrderedDict(
    [
        ("모든피부", r"모든|전\s*피부|all"),
        ("건성", r"건성|건조"),
        ("지성", r"지성"),
        ("복합성", r"복합"),
        ("민감성", r"민감"),
        ("중성", r"중성"),
    ]
)
SPF_RE = re.compile(r"SPF\s*(\d{1,2}\s*\+?)", re.IGNORECASE)
SPF_VOLUME_UNIT_RE = re.compile(r"\s*(?:ml|g)\b", re.IGNORECASE)
PA_RE = re.compile(r"PA\s*(\+{1,4})", re.IGNORECASE)


def skincare_attr(goods_no, goods_name, notice, extra, now):
    """기능성 여부는 고시 항목에서, 기능 종류는 상품명·주요 사양·사용방법 문구에서 찾는다.
    (고시 항목에는 '심사(또는 보고)를 필함 / 해당사항 없음'만 적혀 있고 기능 종류는 없음 – v23 확인)
    정확한 기능 종류는 추후 식약처 기능성화장품 보고·심사품목 API와 대조해 보완한다."""
    raw = (extra.get(FUNCTIONAL_KEY) or "").strip()
    if not raw:
        is_func = ""
    elif re.fullmatch(r"\|\s*N|■\s*무", raw, re.IGNORECASE):
        is_func = "N"
    elif re.search(r"필함|필\b|기능성", raw) and not re.search(
        r"없음|해당\s*사항\s*없", raw
    ):
        is_func = "Y"
    elif re.search(r"없음|해당\s*사항\s*없|비해당|^-$|^N$", raw):
        is_func = "N"
    else:
        is_func = "?"
    spec = (notice.get("main_spec") or "").strip()
    text = f"{goods_name} {spec} {notice.get('usage_guide') or ''}"
    types = [
        k
        for k, pat in FUNC_WORDS.items()
        if is_func == "Y" and re.search(pat, text, re.IGNORECASE)
    ]
    skins = [k for k, pat in SKIN_WORDS.items() if re.search(pat, spec, re.IGNORECASE)]
    spf_source = f"{goods_name} {spec}"
    spf = SPF_RE.search(spf_source)
    if spf and SPF_VOLUME_UNIT_RE.match(spf_source, spf.end()):
        spf = None
    pa = PA_RE.search(f"{goods_name} {spec}")
    return {
        "goods_no": goods_no,
        "is_functional": is_func,
        "functional_types": "|".join(types),
        "functional_raw": raw[:300],
        "skin_types": "|".join(skins),
        "skin_type_raw": spec[:200],
        "spf": spf.group(1).replace(" ", "") if spf else "",
        "pa": pa.group(1) if pa else "",
        "collected_at": now,
    }


# ───────── 목록 API (Referer 만 스킨케어용으로) ─────────
def list_goods(cat_no, limit=None):
    """소분류의 상품번호 목록. limit=None 이면 전체 (100개씩 페이지 이동)"""
    goods, offset = [], 0
    while True:
        size = 100 if limit is None else min(100, limit - offset)
        r = oy.request(
            "POST",
            oy.LIST_API,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": BASE,
                "Referer": f"{BASE}/shop/category/{cat_no[:11]}/sub/{cat_no}",
            },
            json={
                "displayCategoryNumber": cat_no,
                "from": offset,
                "size": size,
                "sort": "POPULAR",
            },
        )
        payload = r.json()
        if payload.get("code") in (429, "429"):
            oy.STOP_EVENT.set()
            raise oy.RateLimited("목록 API 429 응답")
        if payload.get("code") not in (200, "200"):
            raise RuntimeError(
                f"목록 API 오류: {payload.get('code')} {payload.get('message', '')}"
            )
        data = payload.get("data") or {}
        products = data.get("products") or []
        for item in products:
            no = (item.get("product") or {}).get("goodsNumber")
            if no and no not in goods:
                goods.append(no)
        offset += len(products)
        total = data.get("totalCount")
        if total is not None and limit is None and offset < int(total) and not products:
            raise RuntimeError(f"목록 API가 {offset}/{total}에서 조기 종료됨")
        if (
            (total is None and len(products) < size)
            or (limit is not None and len(goods) >= limit)
            or (total is not None and offset >= int(total))
        ):
            break
    return goods[:limit] if limit is not None else goods


def init_out():
    """이번 수집 폴더만 연다. CSV 임시 번호는 적재기가 DB 번호로 다시 연결한다."""
    base.OUT_DIR = OUT_DIR
    base.DONE_LOG = os.path.join(OUT_DIR, "_done.log")
    base.REPORT = os.path.join(OUT_DIR, "수집가능성_리포트.txt")
    base.init_out()


# ───────── 상품 1개 → 테이블 행 ─────────
def collect(mid_name, goods_no, run_id):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    url = f"{BASE}/m/goods/getGoodsDetail.do?goodsNo={goods_no}"
    oy._product_thread.review_cache = {}
    resp = oy.get(url)
    html = resp.text
    g = base._enrich_extract(oy.next_data_text(html))
    d = oy.parse_detail(html, goods_no)
    if not g:
        raise RuntimeError("상품 JSON 파싱 실패")

    options, seen_opt = [], set()
    for o in g.get("options") or []:
        if o.get("goodsNumber") == goods_no and o.get("optionNumber") not in seen_opt:
            seen_opt.add(o.get("optionNumber"))
            options.append(o)
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
                "log_id": base.next_id("log"),
                "run_id": run_id,
                "goods_no": goods_no,
                "step": step,
                "http_status": code,
                "status": status,
                "error_message": msg,
                "logged_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

    bc = g.get("onlineBrand") or ""
    if bc and base.once("brand", bc):
        out["brand"].append(
            {
                "brand_code": bc,
                "brand_name_ko": g.get("onlineBrandName", ""),
                "brand_name_en": g.get("onlineBrandEngName", ""),
            }
        )
    sc = g.get("supplier") or ""
    if sc and base.once("supplier", sc):
        out["supplier"].append(
            {"supplier_code": sc, "supplier_name": g.get("supplierName", "")}
        )
    cats, leaf_no = base.category_rows(g.get("displayCategory") or {})
    out["category"] += cats
    std = g.get("standardCategory") or {}
    goods_name = g.get("goodsName") or d["name"]
    out["product"].append(
        {
            "goods_no": goods_no,
            "brand_code": bc,
            "supplier_code": sc,
            "category_no": leaf_no,
            "std_category_code": std.get("lowerCategoryNumber")
            or std.get("lowerCategoryName", ""),
            "goods_name": goods_name,
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

    # 상품정보제공고시 + 전성분
    notice = {}
    try:
        notice, code = base._enrich_notice(goods_no, options)
        log("notice", "success", code=code)
    except oy.RateLimited:
        raise
    except Exception as e:
        log("notice", "fail", str(e)[:200])
    extra = {}
    try:
        extra = __import__("json").loads(notice.get("notice_extra") or "{}")
    except ValueError:
        pass
    notice["volume"] = base.clean_notice_volume(notice.get("volume"))
    notice["goods_no"] = goods_no
    notice["collected_at"] = now
    out["product_notice"].append(notice)
    out["skincare_attr"].append(skincare_attr(goods_no, goods_name, notice, extra, now))

    ingredients_raw = notice.get("ingredients_raw", "")
    dropped_non_ingredients = set()
    unsafe_chars = base.unsafe_ingredient_chars(ingredients_raw)
    if unsafe_chars:
        log(
            "ingredient_parse_review",
            "review",
            f"전성분 원문에 깨진/숨은 문자 포함: {', '.join(unsafe_chars)}; 해당 성분 토큰 연결 보류",
        )
    marked = base.marked_ingredient_blocks(
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
        per_shade, common = base.split_shade_ingredients(
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

    # 이미지 URL (판정 없음)
    img_seen = set()

    def add_image(option_id, itype, iurl, seq):
        iurl = (iurl or "").strip()
        if not iurl or iurl in img_seen:
            return
        img_seen.add(iurl)
        out["image"].append(
            {
                "image_id": base.next_id("image"),
                "goods_no": goods_no,
                "option_id": option_id,
                "image_type": itype,
                "image_url": iurl,
                "sort_seq": seq,
                "collected_at": now,
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
        desc_urls, code = base._enrich_desc_images(goods_no)
        for i, u in enumerate(desc_urls, 1):
            add_image("", "description", u, i)
        log("description", "success", code=code)
    except oy.RateLimited:
        raise
    except Exception as e:
        log("description", "fail", str(e)[:200])

    # 옵션 / 가격 / 전성분
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
        added = set()
        for seq, iname in enumerate(per_shade.get(no) or common, 1):
            ing_id = base.ingredient_id(iname)
            if not ing_id or ing_id in added:
                continue
            added.add(ing_id)
            out["option_ingredient"].append(
                {
                    "option_id": oid,
                    "ingredient_id": ing_id,
                    "seq": seq,
                }
            )
        lp, sp = o.get("salePrice", ""), o.get("finalPrice", "")
        out["price_snapshot"].append(
            {
                "snapshot_id": base.next_id("snapshot"),
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

    # 리뷰 요약 / 통계 / 설문
    summary, stats = {}, {}
    try:
        summary = oy.review_json(f"v1/reviews/{goods_no}/summary", goods_no) or {}
        log("review_summary", "success", code=200)
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
        x.get("rating"): x.get("percentage") for x in (dist.get("ratingStatDtos") or [])
    }
    if summary or stats:
        out["review_summary"].append(
            {
                "summary_id": base.next_id("summary"),
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
        if qc and base.once("survey_question", qc):
            out["survey_question"].append(
                {"question_code": qc, "question_name": q.get("questionName", "")}
            )
        for a in q.get("answerDtos") or []:
            ac = a.get("answerCode", "")
            if ac and base.once("survey_answer", ac):
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


# ───────── 리포트 (채움률 + 스킨케어 요약) ─────────
def write_report(run_id, started, targets, done, failed, skipped):
    lines = []

    def P(s=""):
        lines.append(s)
        print(s)

    def rows(name):
        path = os.path.join(OUT_DIR, f"{name}.csv")
        if not os.path.isfile(path):
            return []
        csv.field_size_limit(10**8)
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    P("=" * 72)
    P("올리브영 스킨케어 전체 수집 가능성 리포트")
    P("=" * 72)
    P(f"실행 ID {run_id} | 스크립트 {SCRIPT_VERSION} | {datetime.now():%Y-%m-%d %H:%M}")
    P(
        f"대상 상품 {targets}개 (소분류별 {SAMPLE_TOTAL or '전체'}) | 성공 {done} | 실패 {failed} | "
        f"소요 {oy.fmt_dur(time.time() - started)}"
    )
    if skipped:
        P(f"번호 미입력으로 건너뛴 소분류: {', '.join(skipped)}")
    P()
    verdict = {"다 모임": [], "일부만": [], "못 모음": []}
    for name, cols in SCHEMA.items():
        rs = rows(name)
        P("─" * 72)
        P(f"[{name}]  {len(rs)}행")
        if not rs:
            P("   (행 없음)")
            verdict["못 모음"].append(name)
            continue
        worst = "다 모임"
        for c in cols:
            n = sum(1 for r in rs if (r.get(c) or "").strip() != "")
            rate = n / len(rs) * 100
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
            P(f"   {mark} {c:<22} {n:>6}/{len(rs):<6} {rate:5.1f}%  {note}")
        verdict[worst].append(name)

    attr = rows("skincare_attr")
    if attr:
        from collections import Counter

        P("─" * 72)
        P("■ 스킨케어 전용 항목 요약")
        P(
            f"   기능성 여부: {dict(Counter(r['is_functional'] or '(빈칸)' for r in attr))}"
        )
        P(
            f"   기능 종류:   {dict(Counter(t for r in attr for t in r['functional_types'].split('|') if t))}"
        )
        P(
            f"   피부 타입:   {dict(Counter(t for r in attr for t in r['skin_types'].split('|') if t))}"
        )
        P(
            f"   SPF 있음 {sum(1 for r in attr if r['spf'])}개 / PA 있음 {sum(1 for r in attr if r['pa'])}개"
        )
    sq = rows("survey_question")
    if sq:
        P(f"   리뷰 설문 문항: {sorted(set(r['question_name'] for r in sq))}")
    P()
    P("■ 결론")
    for k in ("다 모임", "일부만", "못 모음"):
        P(f"   {k}: {', '.join(verdict[k]) or '-'}")
    P()
    P("  * '예상' 표시는 비어 있는 게 정상인 칸입니다 (사유는 오른쪽에).")
    with open(base.REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n리포트 저장: {base.REPORT}")


# ───────── 메인 ─────────
def main():
    init_out()
    run_id = int(time.time())
    started = time.time()
    base.emit(
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

    active = [(name, no) for name, no in TARGETS.items() if no]
    skipped = [name for name, no in TARGETS.items() if not no]
    jobs, seen = [], set()
    for name, no in active:
        try:
            goods = list_goods(no, SAMPLE_TOTAL)
        except oy.RateLimited:
            raise
        except Exception as e:
            print(f"[{name}] 목록 조회 실패: {e}")
            goods = []
        new = [g for g in goods if g not in seen]
        seen.update(new)
        jobs += [(name, g) for g in new]
        print(f"[{name}] 상품 {len(goods)}개 (다른 소분류와 중복 제외 {len(new)}개)")
        time.sleep(oy.THREAD_DELAY)
    done_set = base.load_done()
    jobs = [j for j in jobs if j[1] not in done_set]
    print(
        f"\n총 {len(jobs)}개 수집 시작 (작업자 {WORKERS}, 이미 끝난 {len(done_set)}개 제외)\n"
    )

    pool = ThreadPoolExecutor(max_workers=WORKERS)
    futures = {pool.submit(collect, m, n, run_id): (m, n) for m, n in jobs}
    done = failed = 0
    with open(base.DONE_LOG, "a", encoding="utf-8") as journal:
        for i, (fut, (m, n)) in enumerate(futures.items(), 1):
            try:
                out = fut.result()
            except oy.RateLimited as e:
                print(f"중단: {e}")
                break
            except Exception as e:
                failed += 1
                base.emit(
                    "crawl_log",
                    [
                        {
                            "log_id": base.next_id("log"),
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
            for name, rs in out.items():
                base.emit(name, rs)
            journal.write(n + "\n")
            journal.flush()
            done += 1
            a = out["skincare_attr"][0]
            print(
                f"   {i:03d}/{len(jobs)} [{m}] {n} {out['product'][0]['goods_name'][:24]} → "
                f"옵션 {len(out['product_option'])} / 성분 {len(out['option_ingredient'])} / "
                f"기능성 {a['is_functional'] or '-'} {a['functional_types']} / 피부 {a['skin_types'] or '-'}"
            )
    pool.shutdown(wait=False)

    path = os.path.join(OUT_DIR, "crawl_run.csv")
    base._files["crawl_run"].flush()
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
    write_report(run_id, started, len(jobs), done, failed, skipped)
    for f in base._files.values():
        try:
            f.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
