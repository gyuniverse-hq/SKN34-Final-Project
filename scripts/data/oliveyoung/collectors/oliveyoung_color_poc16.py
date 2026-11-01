"""
올리브영 메이크업(립/베이스/아이) 옵션별 대표 색상 수집 PoC  (v14)
- 비로그인, API key 없음, requests + Pillow, Selenium/Playwright 없음
- 카테고리 전체 상품을 목록 API에서 100개씩 페이지네이션, 상품 작업자 40개, 이미지 다운로드 전체 80개 병렬
- 모바일 상품 목록 API에서 상품번호를 받고, 상세 페이지 HTML의 Next.js 데이터에서 옵션/브랜드/소분류를 읽음
  (화면의 옵션 목록은 JS가 그리기 때문에 HTML 태그 셀렉터로는 비어 보임)
- 옵션별 이미지(컬러칩/색상비교/옵션이미지)를 모두 분석해 '신뢰도 점수'가 가장 높은 색을 채택
  · 컬러칩 방식: 이미지 전체 유채색 비율 (제품 사진을 잘 걸러냄, 꽉 찬 컬러칩에 강함)
  · 스와치 방식: 배경 제거 후 남은 영역의 색 균일도 (흰 배경 스와치, 저채도 색에 강함)
  · 여러 호수가 같은 이미지를 쓰면(세트 사진) 제외 → 같은 호수의 다른 옵션 색을 가져옴
- 이미지는 메모리에서만 열어 색을 뽑고 저장하지 않음
- 결과: 상품 완료 즉시 누적되는 19열 CSV와 재개용 완료 로그

pip install requests pillow
"""

import csv
import io
import json
import math
import os
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from datetime import datetime

import requests
from PIL import Image

BASE = "https://m.oliveyoung.co.kr"
LIST_API = f"{BASE}/shop-around/api/display-category/v1/goods"
TARGETS = {
    "립메이크업": "100000100020006",
    "베이스메이크업": "100000100020001",
    "아이메이크업": "100000100020007",
}
PER_CATEGORY = None  # None이면 카테고리의 전체 상품; 정수를 넣으면 해당 개수까지만
PRODUCT_WORKERS = 10  # 동시에 수집할 상품 수 (40 → 10: 403 차단을 겪어 낮춤)
IMAGE_WORKERS = 24  # 전체 상품을 통틀어 동시에 다운로드할 이미지 수 (80 → 24)
THREAD_DELAY = 0.4  # 작업자별 요청 간격(초). 차단을 피하려고 다시 넣음
IMG_SIZE = 300  # 분석용 컬러칩 크기
MIN_COLOR_FRAC = 0.5  # 유채색 비율이 이보다 낮으면 제품 사진으로 보고 HEX 제외 (테스트 스크립트와 동일)
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_CSV = os.path.join(HERE, "oliveyoung_makeup_colors_full.csv")
DONE_LOG = os.path.join(HERE, "oliveyoung_makeup_colors_full.done")

COLUMNS = [
    "상품번호",
    "중분류",
    "제품유형(소분류)",
    "브랜드명",
    "상품명",
    "호수",
    "호수이름",
    "올리브영 옵션명",
    "올리브영 HEX",
    "색상(배경)",
    "L*",
    "a*",
    "b*",
    "옵션 이미지 URL",
    "수집일시",
    "제형",
    "판정 근거",
    "색 출처",
    "색 신뢰도",
]


# ───────── 모바일 세션 ─────────
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)
BROWSER_HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Referer": f"{BASE}/",
}
PAGE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
}
IMAGE_HEADERS = {
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
}
_page_thread = threading.local()
STOP_EVENT = threading.Event()


class RateLimited(RuntimeError):
    pass


def page_session():
    if not hasattr(_page_thread, "session"):
        _page_thread.session = requests.Session()
        _page_thread.session.headers.update(BROWSER_HEADERS)
    return _page_thread.session


# ───────── 차단(403) 대응 ─────────
# 403은 IP 단위 일시 차단이라 잠시 쉬면 풀리는 경우가 많다.
# 한 스레드가 403을 만나면 '언제까지 쉴지'를 정하고, 모든 스레드가 그때까지 멈춘다.
# 쉬는 시간을 1분 → 3분 → 10분으로 늘리고, 그래도 안 풀리면 깔끔하게 중단한다.
BLOCK_WAITS = [60, 180, 600]  # 초
MAX_BLOCK_RETRY = 3  # 요청 1건당 재시도 횟수
_block_lock = threading.Lock()
_block_until = 0.0  # 이 시각까지 전체 대기
_block_round = 0  # 몇 번째 차단인지


def wait_if_blocked():
    while True:
        with _block_lock:
            remain = _block_until - time.monotonic()
        if remain <= 0 or STOP_EVENT.is_set():
            return
        time.sleep(min(remain, 5))


def note_block(where):
    """403을 만났을 때. 대기 시각을 잡고, 한도를 넘으면 전체 중단."""
    global _block_until, _block_round
    with _block_lock:
        if time.monotonic() < _block_until:
            return  # 이미 다른 스레드가 대기를 잡아둠
        if _block_round >= len(BLOCK_WAITS):
            STOP_EVENT.set()
            print(
                "\n   차단이 계속되어 수집을 중단합니다. "
                "잠시 후(또는 접속 환경을 바꾼 뒤) 다시 실행하면 이어서 진행됩니다."
            )
            return
        wait = BLOCK_WAITS[_block_round]
        _block_round += 1
        _block_until = time.monotonic() + wait
        print(
            f"\n   차단(403) 감지 – {wait // 60}분 {wait % 60}초 쉬었다가 다시 시도합니다. "
            f"({_block_round}/{len(BLOCK_WAITS)}회째) {where}"
        )


def note_ok():
    """요청이 성공하면 차단 횟수를 초기화한다."""
    global _block_round
    if _block_round:
        with _block_lock:
            _block_round = 0


def throttle(local):
    wait = THREAD_DELAY - (time.monotonic() - getattr(local, "last_request", 0.0))
    if wait > 0:
        time.sleep(wait)
    local.last_request = time.monotonic()


def request(method, url, **kw):
    headers = {**PAGE_HEADERS, **kw.pop("headers", {})}
    for _ in range(MAX_BLOCK_RETRY + 1):
        if STOP_EVENT.is_set():
            raise RateLimited("수집 중단됨")
        wait_if_blocked()
        if STOP_EVENT.is_set():
            raise RateLimited("수집 중단됨")
        throttle(_page_thread)
        r = page_session().request(method, url, timeout=20, headers=headers, **kw)
        if r.status_code == 429:
            STOP_EVENT.set()
            raise RateLimited(f"429 응답: {url.split('?')[0]}")
        if r.status_code == 403:
            note_block(url.split("?")[0])
            continue  # 대기한 뒤 같은 요청을 다시 보냄
        note_ok()
        r.raise_for_status()
        return r
    raise RuntimeError(f"차단(403)이 계속됨: {url.split('?')[0]}")


def get(url, **kw):
    return request("GET", url, **kw)


# ───────── 1. 모바일 목록 API → 상품번호 ─────────
def list_goods(cat_no, limit):
    if limit is not None and limit <= 0:
        return []
    goods = []
    seen = set()
    offset = 0
    while True:
        size = min(100, limit - offset) if limit is not None else 100
        r = request(
            "POST",
            LIST_API,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": BASE,
                "Referer": f"{BASE}/shop/category/10000010002/sub/{cat_no}",
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
            STOP_EVENT.set()
            raise RateLimited("목록 API 429 응답")
        if payload.get("code") not in (200, "200"):
            raise RuntimeError(
                f"목록 API 오류: {payload.get('code')} {payload.get('message', '')}"
            )
        data = payload.get("data") or {}
        products = data.get("products") or []
        if not products and offset == 0:
            raise RuntimeError("목록 API에 상품이 없습니다")
        for item in products:
            no = (item.get("product") or {}).get("goodsNumber")
            if no and no not in seen:
                seen.add(no)
                goods.append(no)
        offset += len(products)
        total_count = data.get("totalCount")
        if (
            total_count is not None
            and limit is None
            and offset < int(total_count)
            and not products
        ):
            raise RuntimeError(f"목록 API가 {offset}/{total_count}에서 조기 종료됨")
        if (
            (limit is not None and len(goods) >= limit)
            or (total_count is None and len(products) < size)
            or (total_count is not None and offset >= int(total_count))
        ):
            break
    return goods[:limit] if limit is not None else goods


# ───────── 2. 상세 페이지 → Next.js 데이터 파싱 ─────────
PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')


def next_data_text(html):
    """self.__next_f.push([1,"..."]) 조각들을 이어 붙여 하나의 텍스트로 복원"""
    return "".join(json.loads(m.group(1)) for m in PUSH_RE.finditer(html))


def json_after(txt, key):
    """txt 안에서 "key": 바로 뒤의 JSON 값(배열/객체)을 파싱"""
    i = txt.find(f'"{key}":')
    if i < 0:
        return None
    try:
        return json.JSONDecoder().raw_decode(txt, i + len(key) + 3)[0]
    except ValueError:
        return None


def str_after(txt, key):
    m = re.search(rf'"{key}":"((?:[^"\\]|\\.)*)"', txt)
    return json.loads(f'"{m.group(1)}"') if m else ""


def parse_detail(html, goods_no):
    txt = next_data_text(html)
    cat = json_after(txt, "displayCategory") or {}
    options = [
        o
        for o in (json_after(txt, "options") or [])
        if o.get("goodsNumber") == goods_no
    ]
    seen, uniq = set(), []
    for o in options:  # 같은 옵션이 두 번 나오는 경우 제거
        if o.get("optionNumber") not in seen:
            seen.add(o.get("optionNumber"))
            uniq.append(o)
    name = (uniq[0].get("goodsName") if uniq else "") or str_after(txt, "goodsName")
    return {
        "sub_cat": cat.get("leafCategoryName") or cat.get("lowerCategoryName", ""),
        "brand": str_after(txt, "onlineBrandName"),
        "name": name,
        "options": uniq,
    }


# ───────── 3. 호수 분리 / 색 추출 / Lab ─────────
HOSU_RE = re.compile(r"^#?([A-Za-z]{0,3}\d+[A-Za-z0-9.\-]*)[\s._)\]:-]*(.*)$")


def split_hosu(option_name):
    s = re.sub(
        r"\[[^\]]*\]|\([^)]*\)", " ", option_name
    ).strip()  # [기획], (단품) 태그 제거
    m = HOSU_RE.match(s)
    return (m.group(1), m.group(2).strip()) if m else ("", s)


MIN_CONF = 0.5  # 신뢰도가 이보다 낮으면 색으로 채택하지 않음
SWATCH_BG_DIST = 20  # 스와치 방식: 테두리 색(배경)과 이 거리 이내면 배경
SWATCH_NEAR = 45  # 스와치 방식: 대표색과 RGB 거리 45 이내인 픽셀 비율 = 균일도
MIN_OBJECT_FRAC = 0.02  # 배경 제거 후 남은 부분이 2% 미만이면 전체를 색 영역으로 사용


def _lum(p):
    return 0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]


def open_rgb(img_bytes, max_side=200):
    im = Image.open(io.BytesIO(img_bytes))
    if im.mode in ("RGBA", "LA", "P"):  # 투명 배경은 흰색으로 합성
        im = Image.alpha_composite(
            Image.new("RGBA", im.size, (255, 255, 255, 255)), im.convert("RGBA")
        )
    im = im.convert("RGB")
    im.thumbnail((max_side, max_side))
    return im


def score_chip(im):
    """컬러칩 방식 (v4 원래 방식): 이미지 전체 중 유채색 픽셀 비율 = 신뢰도
    제품 사진(흰 배경·검정 용기)은 비율이 낮아 자동으로 걸러짐"""
    px = list(im.getdata())[::4]
    col = [p + (_lum(p),) for p in px if max(p) - min(p) >= 25]
    frac = len(col) / len(px) if px else 0
    if len(col) < 50:
        return None, 0.0
    col.sort(key=lambda p: p[3])
    sel = col[int(len(col) * 0.3) : int(len(col) * 0.7)] or col
    return [sum(p[j] for p in sel) / len(sel) for j in range(3)], frac


def score_swatch(im):
    """스와치 방식: 테두리 색을 배경으로 보고 제거 → 남은 영역의 대표색(밝기 30~70% 평균)
    신뢰도 = 남은 영역 중 대표색과 비슷한 픽셀 비율(균일도). 제품 사진·팔레트는 낮게 나옴"""
    w, h = im.size
    pix = im.load()
    border = (
        [pix[x, 0] for x in range(w)]
        + [pix[x, h - 1] for x in range(w)]
        + [pix[0, y] for y in range(h)]
        + [pix[w - 1, y] for y in range(h)]
    )
    bg = [sorted(p[k] for p in border)[len(border) // 2] for k in range(3)]
    allp = [pix[x, y] for y in range(0, h, 2) for x in range(0, w, 2)]
    obj = [
        p
        for p in allp
        if sum((p[k] - bg[k]) ** 2 for k in range(3)) ** 0.5 > SWATCH_BG_DIST
    ]
    if len(obj) < len(allp) * MIN_OBJECT_FRAC:  # 화면 전체가 한 색인 컬러칩
        obj = allp
    s = sorted(obj, key=_lum)
    sel = s[int(len(s) * 0.3) : int(len(s) * 0.7)] or s
    rgb = [sum(p[j] for p in sel) / len(sel) for j in range(3)]
    near = sum(
        1
        for p in obj
        if sum((p[k] - rgb[k]) ** 2 for k in range(3)) ** 0.5 < SWATCH_NEAR
    )
    return rgb, near / len(obj)


COMPARE_PENALTY = 0.9  # 색상비교 이미지만 있는 경우 점수 ×0.9


TIP_BG_DIST = 40  # 펜슬 심: 배경과 이 거리 넘으면 제품 픽셀
TIP_END_FRAC = 0.08  # 펜슬 심: 가장 가는 끝에서 제품 길이의 8% 구간을 심으로 봄
TIP_NARROW_RATIO = (
    0.6  # 심 쪽 끝 폭이 다른 끝들보다 이 비율 이하로 가늘어야 펜슬 사진으로 인정
)
TIP_MIN_ASPECT = (
    2.5  # 제품 영역이 가로·세로 중 한쪽으로 2.5배 이상 길어야 펜슬 사진으로 인정
)


def score_pencil_tip(im):
    """브로우·라이너 펜슬 사진에서 '심 끝'만 측정
    1) 배경 제거 후 제품 영역의 상하좌우 끝 폭 비교 → 이미지 테두리에 닿지 않은 가장 가는 끝 = 심
    2) 그 끝에서 제품 길이의 8% 구간 픽셀을 밝기 30~70% 평균
    신뢰도 = 그 구간 픽셀이 대표색과 비슷한 비율(균일도)"""
    w, h = im.size
    pix = im.load()
    border = (
        [pix[x, 0] for x in range(w)]
        + [pix[x, h - 1] for x in range(w)]
        + [pix[0, y] for y in range(h)]
        + [pix[w - 1, y] for y in range(h)]
    )
    bg = [sorted(p[k] for p in border)[len(border) // 2] for k in range(3)]
    obj = [
        [
            sum((pix[x, y][k] - bg[k]) ** 2 for k in range(3)) ** 0.5 > TIP_BG_DIST
            for x in range(w)
        ]
        for y in range(h)
    ]
    ys = [y for y in range(h) if any(obj[y])]
    xs = [x for x in range(w) if any(obj[y][x] for y in range(h))]
    if not ys or not xs:
        return None, 0.0
    x0, x1, y0, y1 = xs[0], xs[-1], ys[0], ys[-1]
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    if max(bw, bh) < TIP_MIN_ASPECT * min(bw, bh):  # 길쭉하지 않으면 펜슬 사진 아님
        return None, 0.0

    def band(side, frac):
        ext = (y1 - y0 + 1) if side in ("top", "bottom") else (x1 - x0 + 1)
        n = max(3, round(ext * frac))
        pts = []
        for i in range(n):
            if side == "top":
                pts += [pix[x, y0 + i] for x in range(x0, x1 + 1) if obj[y0 + i][x]]
            elif side == "bottom":
                pts += [pix[x, y1 - i] for x in range(x0, x1 + 1) if obj[y1 - i][x]]
            elif side == "left":
                pts += [pix[x0 + i, y] for y in range(y0, y1 + 1) if obj[y][x0 + i]]
            else:
                pts += [pix[x1 - i, y] for y in range(y0, y1 + 1) if obj[y][x1 - i]]
        return pts, n

    touches = {
        "top": y0 == 0,
        "bottom": y1 == h - 1,
        "left": x0 == 0,
        "right": x1 == w - 1,
    }
    widths = {s: len(band(s, 0.1)[0]) / band(s, 0.1)[1] for s in touches}
    free = [s for s in touches if not touches[s] and widths[s] > 0]
    if not free:
        return None, 0.0
    tip = min(free, key=lambda s: widths[s])
    others = [widths[s] for s in widths if s != tip]
    if not others or widths[tip] > TIP_NARROW_RATIO * max(
        others
    ):  # 뾰족한 끝이 없으면 펜슬 사진 아님
        return None, 0.0
    pts, _ = band(tip, TIP_END_FRAC)
    if len(pts) < 30:
        return None, 0.0
    s = sorted(pts, key=_lum)
    sel = s[int(len(s) * 0.3) : int(len(s) * 0.7)] or s
    rgb = [sum(p[j] for p in sel) / len(sel) for j in range(3)]
    near = sum(
        1
        for p in pts
        if sum((p[k] - rgb[k]) ** 2 for k in range(3)) ** 0.5 < SWATCH_NEAR
    )
    return rgb, near / len(pts)


PALE_CHROMA = (
    25  # 립 패키지 판별: 결과 색의 (R,G,B 최댓값-최솟값)이 이 값 미만 = 거의 무채색
)
PACKAGE_EDGE = 0.12  # 립 패키지 판별: 내부 무늬 밀도가 이 값 초과면 패키지 사진


def inner_edge_density(im):
    """배경을 뺀 제품 영역 안에서 밝기가 급하게 바뀌는 픽셀 비율
    (패키지 사진: 글자·캐릭터·모서리로 0.18~0.52 / 매끈한 스와치: 0.01~0.08 – 실측)"""
    w, h = im.size
    pix = im.load()
    border = (
        [pix[x, 0] for x in range(w)]
        + [pix[x, h - 1] for x in range(w)]
        + [pix[0, y] for y in range(h)]
        + [pix[w - 1, y] for y in range(h)]
    )
    bg = [sorted(p[k] for p in border)[len(border) // 2] for k in range(3)]
    is_obj = lambda p: (
        sum((p[k] - bg[k]) ** 2 for k in range(3)) ** 0.5 > SWATCH_BG_DIST
    )
    inner = edges = 0
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            p = pix[x, y]
            if not is_obj(p):
                continue
            nb = (pix[x + 1, y], pix[x - 1, y], pix[x, y + 1], pix[x, y - 1])
            if not all(is_obj(q) for q in nb):
                continue
            inner += 1
            lp = _lum(p)
            if max(abs(_lum(q) - lp) for q in nb) > 18:
                edges += 1
    return edges / inner if inner else 0.0


def conf_label(c):
    return f"{c:.2f} " + ("높음" if c >= 0.8 else "보통" if c >= 0.6 else "낮음(검수)")


# ───────── 품목별 규칙 ─────────
# 립메이크업: v8 규칙 그대로 (v8 결과가 Aside보다 정확했음 – 바꾸지 않음)
# 브로우·라이너: 색상비교는 얼굴에 바른 사진(피부가 대부분)이라 제외, 옵션 이미지(그은 선 스와치 등)로만 실측
# 마스카라: 옵션 이미지가 패키지 사진이라 패키지 색과 실제 색을 구분할 수 없음 → 비우고 검수 대상
def item_rule(mid_name, sub_cat, goods_name):
    text = f"{sub_cat or ''} {goods_name or ''}"
    if mid_name == "립메이크업":
        return "lip"
    # '브로우 마스카라'처럼 두 말이 같이 있으면 브로우가 우선이다.
    # (눈썹 제품이므로 색상비교=얼굴 사진을 빼는 line 규칙을 타야 한다)
    if "브로우" in text or "라이너" in text:
        return "line"
    if "마스카라" in text:
        return "mascara"
    return "default"


# ───────── 마스카라: "아주 확실한 것만" 채택하는 검증 규칙 ─────────
# 배경: 마스카라 옵션 이미지는 대부분 튜브(패키지) 사진이다.
#   - 신뢰도만으로는 못 거른다. (흰 배경 세트컷 0.76, 분홍 패키지 0.60 vs 진짜 스와치 0.38)
#   - 모양(가로세로비·채움률·에지밀도)으로도 못 거른다. 패키지와 붓자국이 겹친다.
#   - 밝기(L*)만으로도 못 거른다. 검정 튜브는 검정 마스카라만큼 어둡다.
# 그래서 ①스와치 방식 결과만 ②신뢰도 하한 ③호수명이 가리키는 색과 측정값이 일치
# 이 세 가지를 모두 통과할 때만 채택한다. (저장값은 어디까지나 '실측값'이고,
#  호수명은 값을 만들어내는 데 쓰지 않고 통과/탈락 판정에만 쓴다.)
MASCARA_MIN_CONF = 0.30  # 진짜 스와치도 0.38까지 내려감 → 일반 기준(0.5)보다 낮게
# (키워드, L* 상한, C* 상한, 허용 색상각 범위(도) | None)
MASCARA_BANDS = [
    (["블랙", "BLACK", "먹색", "흑색"], 35, 12, None),
    (["그레이지", "그레이", "애쉬", "회색", "GRAY", "GREY"], 45, 14, None),
    (
        [
            "브라운",
            "갈색",
            "초코",
            "쇼콜라",
            "카카오",
            "코코아",
            "모카",
            "토프",
            "카멜",
            "밤색",
            "BROWN",
        ],
        45,
        45,
        (15, 110),
    ),
    (["버건디", "와인", "플럼", "체리", "로지", "레드", "적갈"], 42, 50, (330, 45)),
    (["네이비", "블루", "BLUE", "코발트"], 48, 50, (200, 310)),
    (["카키", "올리브", "그린", "GREEN"], 48, 45, (90, 190)),
    (["퍼플", "바이올렛", "라벤더", "보라"], 48, 50, (275, 345)),
]


def mascara_band(option_name):
    """호수명에서 색 표기를 찾아 허용 범위를 돌려준다. 색 표기가 없으면 None"""
    up = (option_name or "").upper()
    for words, l_max, c_max, hue in MASCARA_BANDS:
        for w in words:
            if w.upper() in up:
                return w, l_max, c_max, hue
    return None


def mascara_check(rgb, option_name):
    """실측값이 호수명과 맞는지 검증 → (통과여부, 설명)"""
    band = mascara_band(option_name)
    if not band:
        return False, "호수명에 색 표기가 없어 검증 불가"
    word, l_max, c_max, hue = band
    L, a, b = (float(v) for v in to_lab(rgb))
    chroma = math.hypot(a, b)
    hexv = "#%02X%02X%02X" % tuple(round(c) for c in rgb)
    if L > l_max:
        return False, f"'{word}'인데 측정값이 너무 밝음 {hexv} (L* {L:.0f} > {l_max})"
    if chroma > c_max:
        return (
            False,
            f"'{word}'인데 측정값이 너무 선명함 {hexv} (C* {chroma:.0f} > {c_max})",
        )
    if hue is not None:
        ang = math.degrees(math.atan2(b, a)) % 360
        lo, hi = hue
        ok = lo <= ang <= hi if lo <= hi else (ang >= lo or ang <= hi)
        if not ok:
            return False, f"'{word}'와 색상 계열이 다름 {hexv} (색상각 {ang:.0f}°)"
    return True, f"호수명 '{word}'와 일치"


def mascara_color(o, shared_urls):
    """마스카라 전용. 스와치 방식만 쓰고, 검증을 통과할 때만 값을 돌려준다."""
    cands = candidates(o, "mascara")
    if not cands:
        return None, "", "마스카라 – 색 이미지 없음", 0.0
    name = o.get("optionName", "")
    best = (None, next(iter(cands)), "", 0.0)
    for url, label in cands.items():
        if url in shared_urls:
            continue
        rgb, conf = score_swatch(open_rgb(fetch_img(url)))
        if rgb and conf > best[3]:
            best = (rgb, url, label, conf)
    if not best[0]:
        return (
            None,
            best[1],
            "마스카라 – 옵션 이미지가 패키지/세트 사진 (발색 영역 없음)",
            0.0,
        )
    if best[3] < MASCARA_MIN_CONF:
        return (
            None,
            best[1],
            f"마스카라 – 신뢰도 부족 ({best[3]:.2f} < {MASCARA_MIN_CONF})",
            best[3],
        )
    ok, why = mascara_check(best[0], name)
    if not ok:
        return None, best[1], f"마스카라 – 패키지 사진으로 판단: {why}", best[3]
    return best[0], best[1], f"{best[2]}(스와치 방식, {why})", best[3]


TEXTURE_SKIP = {"line", "mascara"}


def to_lab(rgb):
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    R, G, B = (lin(c) for c in rgb)
    X = (R * 0.4124 + G * 0.3576 + B * 0.1805) / 0.95047
    Y = R * 0.2126 + G * 0.7152 + B * 0.0722
    Z = (R * 0.0193 + G * 0.1192 + B * 0.9505) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    return (
        round(116 * f(Y) - 16, 1),
        round(500 * (f(X) - f(Y)), 1),
        round(200 * (f(Y) - f(Z)), 1),
    )


IMG_KEYS = [
    ("colorChipImage", "컬러칩"),
    ("colorCompareImage", "색상비교"),
    ("optionImage", "옵션이미지"),
]
_product_thread = threading.local()
_image_thread = threading.local()


def image_url(o, key="colorChipImage"):
    img = o.get(key) or {}
    return (img.get("url", "") + img.get("path", "")) if img.get("path") else ""


def candidates(o, rule="default"):
    """옵션의 이미지 후보 {url: '컬러칩·옵션이미지' 같은 라벨} (같은 파일은 1번만)
    rule='line'(브로우·라이너)이면 색상비교(얼굴 사진) 제외"""
    out = {}
    for key, label in IMG_KEYS:
        if rule == "line" and key == "colorCompareImage":
            continue
        u = image_url(o, key)
        if u:
            out[u] = f"{out[u]}·{label}" if u in out else label
    return out


def image_session():
    """이미지 세션은 스레드마다 따로 두고 페이지 쿠키는 CDN에 보내지 않는다."""
    if not hasattr(_image_thread, "session"):
        _image_thread.session = requests.Session()
        _image_thread.session.headers.update(BROWSER_HEADERS)
    return _image_thread.session


def download_img(url):
    """CDN 이미지를 받는다. 429면 전체 중단, 403이면 쉬었다가 다시 시도."""
    for _ in range(MAX_BLOCK_RETRY + 1):
        if STOP_EVENT.is_set():
            raise RateLimited("수집 중단됨")
        wait_if_blocked()
        if STOP_EVENT.is_set():
            raise RateLimited("수집 중단됨")
        throttle(_image_thread)
        r = image_session().get(
            f"{url}?RS={IMG_SIZE}x0&QT=100", timeout=20, headers=IMAGE_HEADERS
        )
        if r.status_code == 429:
            STOP_EVENT.set()
            raise RateLimited("이미지 CDN 429 응답")
        if r.status_code == 403:
            note_block("이미지 CDN")
            continue
        note_ok()
        r.raise_for_status()
        return r.content
    raise RuntimeError("이미지 CDN 차단(403)이 계속됨")


def product_images():
    if not hasattr(_product_thread, "cache"):
        _product_thread.cache = {}
        _product_thread.errors = {}
    return _product_thread.cache, _product_thread.errors


def prefetch_images(opts, shared_urls, rule, image_pool):
    """상품별 캐시에 이미지를 보관하고, 전체 공용 풀에서 내려받는다."""
    if STOP_EVENT.is_set():
        raise RateLimited("429 발생으로 수집 중단")
    cache, errors = product_images()
    urls = list(
        dict.fromkeys(
            url
            for o in opts
            for url in candidates(o, rule)
            if url not in shared_urls and url not in cache
        )
    )
    if not urls:
        return
    tasks = {image_pool.submit(download_img, url): url for url in urls}
    for task in as_completed(tasks):
        url = tasks[task]
        try:
            cache[url] = task.result()
            errors.pop(url, None)
        except RateLimited:
            raise
        except Exception as e:
            if STOP_EVENT.is_set():
                raise RateLimited("429 발생으로 수집 중단") from e
            errors[url] = str(e)


def fetch_img(url):
    if STOP_EVENT.is_set():
        raise RateLimited("429 발생으로 수집 중단")
    cache, errors = product_images()
    if url in errors:
        raise RuntimeError(errors[url])
    if url not in cache:
        pool = getattr(_product_thread, "image_pool", None)
        cache[url] = (
            pool.submit(download_img, url).result() if pool else download_img(url)
        )
    return cache[url]


def best_color(o, shared_urls, rule="default"):
    """후보 이미지마다 두 방식으로 점수를 매겨 가장 높은 것을 채택
    반환: (rgb|None, 사용한 url, 출처 설명, 신뢰도)"""
    cands = candidates(o, rule)
    if not cands:
        return None, "", "색 이미지 없음", 0.0
    best = (None, next(iter(cands)), "", 0.0)
    skipped, rejected_pkg = [], []
    for url, label in cands.items():
        if url in shared_urls:
            skipped.append(label)
            continue
        im = open_rgb(fetch_img(url))
        # 컬러칩 방식: 립은 v8대로 컬러칩 이미지에만,
        #   그 외(베이스·아이)는 옵션이미지에도 적용 (화면 가득 찬 텍스처 사진 – 클리오 리필 사례)
        # 색상비교 이미지에는 적용하지 않음 (모델 사진은 피부까지 유채색이라 피부색이 섞임)
        methods = [("스와치 방식", score_swatch)]
        if "컬러칩" in label or (rule != "lip" and "옵션이미지" in label):
            methods.insert(0, ("컬러칩 방식", score_chip))
        only_compare = label == "색상비교" and rule != "lip"
        for method, fn in methods:
            rgb, conf = fn(im)
            if only_compare:
                conf *= COMPARE_PENALTY  # 베이스·아이: 모델 사진일 수 있어 한 단계 낮게 평가
            # 립: 스와치 방식 결과가 거의 무채색인데 내부 무늬(글자·캐릭터·모서리)가 많으면 패키지 사진 → 제외
            #     (포켓몬 에디션 파우치, 이니미니 상자 사례 / 핑크링·유리멘탈·강철멘탈 같은 연한 스와치는 무늬가 적어 유지)
            if (
                rgb
                and rule == "lip"
                and method == "스와치 방식"
                and max(rgb) - min(rgb) < PALE_CHROMA
                and inner_edge_density(im) > PACKAGE_EDGE
            ):
                rejected_pkg.append(label)
                continue
            if rgb and conf > best[3]:
                best = (rgb, url, f"{label}({method})", conf)
    if best[0] and best[3] >= MIN_CONF:
        return best
    if rejected_pkg:
        return (
            None,
            next(iter(cands)),
            f"패키지 사진으로 판단해 제외 ({'/'.join(rejected_pkg)}), 다른 색 이미지 없음",
            0.0,
        )
    # 브로우·라이너: 그은 선 스와치가 없으면 펜슬 사진의 '심 끝'만 측정
    if rule == "line":
        for url, label in cands.items():
            if url in shared_urls:
                continue
            rgb, conf = score_pencil_tip(open_rgb(fetch_img(url)))
            if rgb:  # 펜슬 모양이 확인되면 기준값과 관계없이 실측값 사용, 신뢰도는 그대로 표시
                return rgb, url, f"{label}(펜슬 심 측정 – 몸체 색이 섞일 수 있음)", conf
    if skipped and not best[2]:
        return (
            None,
            best[1],
            f"여러 호수가 같은 이미지 사용(세트 사진) – {'/'.join(skipped)} 제외",
            0.0,
        )
    return (
        None,
        best[1],
        f"제품 사진·다색 이미지로 판단 (최고 점수 {best[3]:.2f})",
        best[3],
    )


# ───────── 4. 제형 판정 (1차 상품명 → 2차 리뷰 AI 요약 → 3차 리뷰 설문 통계) ─────────
REVIEW_API = f"{BASE}/review/api"

# 7종: matte / velvet / cream / satin / sheer / glossy / shimmer   (제형.md 기준)
# '글로우·윤광·촉촉'은 7종 중 어디인지 단정할 수 없어 일부러 키워드에서 뺌 → 다음 단계로 넘어감
TEXTURE_WORDS = [
    ("shimmer", ["쉬머", "글리터", "스파클", "메탈릭", "펄"]),
    (
        "matte",
        ["세미매트", "매트", "마뜨", "무광", "보송"],
    ),  # '세미매트'는 아래에서 velvet으로 바꿈
    ("velvet", ["벨벳", "블러"]),
    ("cream", ["크리미", "크림"]),
    ("satin", ["새틴"]),
    ("sheer", ["시어", "쉬어", "워터리", "워터"]),
    ("glossy", ["글로시", "글로스", "물광", "유리알", "유광", "광택"]),
]
NAME_EXCLUDE = ["워터프루프", "크림치즈"]  # 제형이 아닌데 키워드를 포함하는 말
NEGATION = re.compile(r"^.{0,6}(없|않|아닌|안 )")  # '펄감이 없어요', '매트하지 않고'


def find_texture(text, exclude=()):
    """텍스트에서 가장 먼저 나오는 제형 키워드 → (제형, 키워드)"""
    for w in exclude:
        text = text.replace(w, " ")
    best = None
    for tex, words in TEXTURE_WORDS:
        for w in words:
            for m in re.finditer(re.escape(w), text):
                if NEGATION.match(text[m.end() :]):
                    continue
                if best is None or m.start() < best[0]:
                    best = (m.start(), "velvet" if w == "세미매트" else tex, w)
                break
    return (best[1], best[2]) if best else (None, None)


def review_json(path, goods_no):
    """같은 상품의 같은 리뷰 주소는 한 번만 부른다.
    (제형 판정과 리뷰 테이블 적재가 같은 주소를 쓰기 때문에 중복 호출이 생겼었음)"""
    cache = getattr(_product_thread, "review_cache", None)
    if cache is None:
        cache = _product_thread.review_cache = {}
    key = (goods_no, path)
    if key in cache:
        return cache[key]
    r = get(
        f"{REVIEW_API}/{path}",
        headers={
            "Accept": "application/json",
            "Origin": BASE,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Referer": f"{BASE}/m/goods/getGoodsDetail.do?goodsNo={goods_no}",
        },
    )
    cache[key] = (r.json() or {}).get("data") or {}
    return cache[key]


# 3차 기준값 (필요하면 조정)
def texture_from_stats(stats):
    q = {
        s.get("questionName"): {
            a.get("answerName", ""): a.get("answerPercentage", 0)
            for a in s.get("answerDtos", [])
        }
        for s in stats.get("satisfactionStats") or []
    }
    pearl, pearl_note = q.get("펄감"), None
    if pearl:
        strong = sum(v for k, v in pearl.items() if "강해" in k)
        none_ = sum(v for k, v in pearl.items() if "없어" in k)
        note = (
            f"리뷰 펄감(강함 {strong}/보통 {pearl.get('보통이에요', 0)}/없음 {none_}%)"
        )
        if strong >= 40:
            return "shimmer", note
        if none_ >= 60:
            return "matte", note
        pearl_note = note
    moist = q.get("수분감")
    if moist:
        wet = sum(v for k, v in moist.items() if "촉촉" in k)
        mat = sum(v for k, v in moist.items() if "매트" in k)
        note = f"리뷰 수분감(촉촉 {wet}/보통 {moist.get('보통이에요', 0)}/매트 {mat}%)"
        if mat >= 50:
            return "matte", note
        if mat >= 25:
            return "velvet", note
        if wet >= 60:
            return "glossy", note
        if wet >= 40:
            return "satin", note
        return "cream", note
    return None, pearl_note


def judge_texture(goods_no, goods_name):
    # 1차: 상품명
    tex, word = find_texture(goods_name, NAME_EXCLUDE)
    if tex:
        return tex, f"상품명 '{word}'"
    # 2차: 리뷰 AI 요약에 제형이 명시된 경우
    try:
        s = review_json(f"v1/reviews/{goods_no}/summary", goods_no)
        for i in (1, 2, 3):
            title = s.get(f"feature{i}Title") or ""
            desc = s.get(f"feature{i}Description") or ""
            tex, word = find_texture(f"{title} {desc}")
            if tex:
                return tex, f"리뷰 언급 '{title.strip()}' ('{word}')"
    except RateLimited:
        raise
    except Exception as e:
        print(f"      리뷰 요약 실패: {e}")
    # 3차: 리뷰 설문 통계(수분감 / 아이섀도우는 펄감)
    try:
        tex, note = texture_from_stats(
            review_json(f"v2/reviews/{goods_no}/stats", goods_no)
        )
        if tex:
            return tex, note
        if note:
            return "", f"판정 불가 ({note})"
    except RateLimited:
        raise
    except Exception as e:
        print(f"      리뷰 통계 실패: {e}")
        return "", "판정 불가 (리뷰 API 실패)"
    return "", "판정 불가 (근거 없음)"


# ───────── 5. 상품 1개 → 행 목록 ─────────
def crawl_goods(mid_name, goods_no, image_pool):
    if STOP_EVENT.is_set():
        raise RateLimited("429 발생으로 수집 중단")
    _product_thread.cache = {}
    _product_thread.errors = {}
    _product_thread.review_cache = {}
    _product_thread.image_pool = image_pool
    d = parse_detail(
        get(f"{BASE}/m/goods/getGoodsDetail.do?goodsNo={goods_no}").text, goods_no
    )
    rule = item_rule(mid_name, d["sub_cat"], d["name"])
    # 브로우·라이너·마스카라는 매트/글로시 같은 광택 축으로 설명되는 품목이 아니다.
    # (AR에서 쓰는 광택 값이 애초에 성립하지 않음) → 제형을 아예 수집하지 않는다.
    if rule in TEXTURE_SKIP:
        texture, reason = "", "제형 축 비해당 (브로우·라이너·마스카라)"
    else:
        texture, reason = judge_texture(goods_no, d["name"])
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    base = [goods_no, mid_name, d["sub_cat"], d["brand"], d["name"]]
    tail = [texture, reason]
    if not d["options"]:
        return [
            base
            + ["", "", "단일상품(옵션없음)", "", "", "", "", "", "", now]
            + tail
            + ["", ""]
        ]
    opts = d["options"]
    is_palette = "팔레트" in d["name"]

    # (1) 여러 호수가 함께 쓰는 이미지 찾기 → 세트/대표 사진이라 색 근거로 쓰지 않음
    users = {}
    for o in opts:
        hosu, _ = split_hosu(o.get("optionName", ""))
        for u in candidates(o, rule):
            users.setdefault(u, set()).add(hosu or o.get("optionName", ""))
    shared = {u for u, who in users.items() if len(who) >= 2}

    if not is_palette:
        prefetch_images(opts, shared, rule, image_pool)

    # (2) 옵션별 최고 점수 색  (팔레트는 옵션 1개에 여러 색이라 대표색을 만들지 않음)
    results = []
    for o in opts:
        if is_palette:
            results.append(
                (
                    None,
                    next(iter(candidates(o)), ""),
                    "팔레트(여러 색) – 대표색 1개로 표현 불가, 별도 처리 필요",
                    0.0,
                )
            )
            continue
        try:
            if rule == "mascara":
                results.append(mascara_color(o, shared))
                continue
            r = best_color(o, shared, rule)
            if rule == "line" and not r[0]:
                r = (
                    r[0],
                    r[1],
                    f"브로우·라이너 – 옵션 이미지에 발색(그은 선) 없음, 얼굴 사진은 제외 / {r[2]}",
                    r[3],
                )
            results.append(r)
        except RateLimited:
            raise
        except Exception as e:
            print(f"\n      이미지 실패({o.get('optionName', '')}): {e}")
            results.append((None, "", f"이미지 오류: {e}", 0.0))

    # (3) 같은 호수의 다른 옵션 색을 가져옴 (예: 세트 기획 옵션 ← 본품 옵션)
    #     - 색이 없는 옵션, 또는
    #     - 같은 호수 옵션의 점수(×0.9)가 더 높은 경우 (예: 입술 모델 사진에서 뽑은 색 → 같은 호수 컬러칩 색으로 교체)
    by_hosu = {}
    for o, r in zip(opts, results):
        hosu, _ = split_hosu(o.get("optionName", ""))
        if (
            hosu
            and r[0]
            and (hosu.upper() not in by_hosu or r[3] > by_hosu[hosu.upper()][1][3])
        ):
            by_hosu[hosu.upper()] = (o.get("optionName", ""), r)
    for i, (o, r) in enumerate(zip(opts, results)):
        name = o.get("optionName", "")
        hosu, _ = split_hosu(name)
        if not hosu or hosu.upper() not in by_hosu:
            continue
        src_name, src = by_hosu[hosu.upper()]
        # 립은 v8대로 '색이 없을 때만' 가져옴 / 베이스·아이는 점수가 더 높으면 교체
        if src_name != name and (not r[0] or (rule != "lip" and src[3] * 0.9 > r[3])):
            results[i] = (
                src[0],
                src[1],
                f"같은 호수 옵션 '{src_name}'에서 가져옴 ← {src[2]}",
                src[3] * 0.9,
            )

    rows = []
    for o, (rgb, url, source, conf) in zip(opts, results):
        opt = o.get("optionName", "")
        hosu, hosu_name = split_hosu(opt)
        hexv, lab = "", ("", "", "")
        if rgb:
            hexv = "#%02X%02X%02X" % tuple(round(c) for c in rgb)
            lab = to_lab(rgb)
        rows.append(
            base
            + [hosu, hosu_name, opt, hexv, "", *lab, url, now]
            + tail
            + [source, conf_label(conf) if rgb else ""]
        )
    if STOP_EVENT.is_set():
        raise RateLimited("429 발생으로 수집 중단")
    return rows


def fmt_dur(sec):
    sec = int(max(sec, 0))
    return (
        f"{sec // 3600}시간 {sec % 3600 // 60}분"
        if sec >= 3600
        else f"{sec // 60}분 {sec % 60}초"
    )


def eta_line(done, total, started):
    """병렬 실행 중 현재 처리량을 기준으로 남은 시간을 추정한다."""
    elapsed = time.time() - started
    remain = elapsed / done * (total - done)
    end = datetime.fromtimestamp(time.time() + remain)
    return (
        f"진행 {done}/{total} | 경과 {fmt_dur(elapsed)} | "
        f"남은 시간 약 {fmt_dur(remain)} (예상 완료 {end:%H:%M})"
    )


def load_completed(allowed):
    """완료 로그를 기준으로 CSV를 검사하고 미완성 상품 행을 제거한다."""
    completed = set()
    if os.path.isfile(DONE_LOG):
        with open(DONE_LOG, newline="", encoding="utf-8") as source:
            for row in csv.reader(source):
                if len(row) == 2 and tuple(row) in allowed:
                    completed.add(tuple(row))
    if not os.path.isfile(OUT_CSV):
        if completed:
            raise RuntimeError("완료 로그는 있으나 CSV가 없습니다")
        return completed, 0, 0

    repaired = OUT_CSV + ".repair.tmp"
    row_count = hex_count = 0
    with (
        open(OUT_CSV, newline="", encoding="utf-8-sig") as source,
        open(repaired, "w", newline="", encoding="utf-8-sig") as target,
    ):
        reader = csv.reader(source)
        writer = csv.writer(target)
        if next(reader, None) != COLUMNS:
            raise ValueError("기존 CSV의 열 구성이 현재 코드와 다릅니다")
        writer.writerow(COLUMNS)
        for row in reader:
            if len(row) == len(COLUMNS) and (row[1], row[0]) in completed:
                writer.writerow(row)
                row_count += 1
                hex_count += bool(row[8])
    os.replace(repaired, OUT_CSV)
    return completed, row_count, hex_count


def main():
    STOP_EVENT.clear()
    print(
        f"HTTP: requests | 상품 작업자 {PRODUCT_WORKERS}개 | 이미지 작업자 {IMAGE_WORKERS}개 | "
        f"작업자별 요청 간격 {THREAD_DELAY}초"
    )
    started = time.time()

    # 세 카테고리의 전체 상품 목록을 100개씩 끝까지 받는다.
    jobs = []
    for mid_name, cat_no in TARGETS.items():
        try:
            goods = list_goods(cat_no, PER_CATEGORY)
            jobs += [(mid_name, no) for no in goods]
            print(f"[{mid_name}] 상품 {len(goods)}개 확인")
        except RateLimited as e:
            print(f"목록 수집 중단: {e}")
            return 2
        except Exception as e:
            print(f"[{mid_name}] 목록 실패: {e}")
            return 1

    allowed = set(jobs)
    completed, total_rows, hex_count = load_completed(allowed)
    pending = iter(
        (i, mid_name, no)
        for i, (mid_name, no) in enumerate(jobs, 1)
        if (mid_name, no) not in completed
    )
    print(
        f"\n총 {len(jobs)}개 상품 | 이전 완료 {len(completed)}개 | CSV {total_rows}행"
    )

    new_done = failures = 0
    rate_limited = False
    if not os.path.isfile(OUT_CSV):
        with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as target:
            csv.writer(target).writerow(COLUMNS)

    image_pool = ThreadPoolExecutor(max_workers=IMAGE_WORKERS)
    product_pool = ThreadPoolExecutor(max_workers=PRODUCT_WORKERS)
    inflight = {}
    with (
        open(OUT_CSV, "a", newline="", encoding="utf-8") as target,
        open(DONE_LOG, "a", newline="", encoding="utf-8") as journal,
    ):
        journal_writer = csv.writer(journal)

        def record(i, mid_name, no, rows):
            nonlocal new_done, total_rows, hex_count
            key = (mid_name, no)
            if key in completed:
                return
            buffer = io.StringIO(newline="")
            csv.writer(buffer).writerows(rows)
            target.write(buffer.getvalue())
            target.flush()
            journal_writer.writerow(key)
            journal.flush()
            completed.add(key)
            new_done += 1
            total_rows += len(rows)
            nhex = sum(bool(row[8]) for row in rows)
            hex_count += nhex
            print(
                f"   {i:04d}. [{mid_name}] {no} {rows[0][4][:28]} → "
                f"옵션 {len(rows)}개, HEX {nhex}개"
            )

        def refill():
            while len(inflight) < PRODUCT_WORKERS and not STOP_EVENT.is_set():
                try:
                    i, mid_name, no = next(pending)
                except StopIteration:
                    break
                task = product_pool.submit(crawl_goods, mid_name, no, image_pool)
                inflight[task] = (i, mid_name, no)

        try:
            refill()
            while inflight:
                done, _ = wait(inflight, return_when=FIRST_COMPLETED)
                for task in done:
                    i, mid_name, no = inflight.pop(task)
                    try:
                        record(i, mid_name, no, task.result())
                    except RateLimited as e:
                        rate_limited = True
                        STOP_EVENT.set()
                        print(
                            f"\n[429 중단] {e} | CSV 완료 {len(completed)}/{len(jobs)}개"
                        )
                    except Exception as e:
                        failures += 1
                        print(f"   {i:04d}. [{mid_name}] {no} 실패: {e}")
                if new_done and new_done % 25 == 0:
                    print(
                        f"       진행 {len(completed)}/{len(jobs)} | CSV {total_rows}행, HEX {hex_count}개 "
                        f"| 경과 {fmt_dur(time.time() - started)}"
                    )
                if rate_limited:
                    break
                refill()
        finally:
            product_pool.shutdown(wait=True, cancel_futures=rate_limited)
            image_pool.shutdown(wait=True, cancel_futures=rate_limited)
            # 429 직전에 완료된 상품도 CSV에 기록한다.
            for task, (i, mid_name, no) in inflight.items():
                if task.cancelled() or not task.done():
                    continue
                try:
                    rows = task.result()
                except Exception:
                    continue
                record(i, mid_name, no, rows)

    print(
        f"\n총 소요 시간: {fmt_dur(time.time() - started)} | 완료 {len(completed)}/{len(jobs)}개 "
        f"| CSV {total_rows}행, HEX {hex_count}개 | 파일 {OUT_CSV}"
    )
    if failures:
        print(f"이번 실행 실패 상품: {failures}개 (재실행 시 재시도)")
    if rate_limited:
        print(
            "429로 즉시 중단했습니다. IP 변경 후 같은 스크립트를 실행하면 CSV에서 이어집니다."
        )
        return 2
    if len(completed) != len(jobs):
        print(
            f"미완료 상품 {len(jobs) - len(completed)}개. 재실행하면 CSV에서 이어집니다."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
