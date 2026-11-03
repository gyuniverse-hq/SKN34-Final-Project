"""
발린 사진 자동 판정 v1 — 이미 수집해 둔 이미지 URL로 판정 (상품 재수집 없음)

흐름
  1. 수집 결과 폴더의 image.csv 에서 판정 대상 URL을 고른다 (URL당 1번)
  2. 종류만으로 정해지는 이미지는 내려받지 않고 바로 기록
       · thumbnail  → package (대표 제품 사진)
       · color_chip → chip    (올리브영이 컬러칩으로 등록한 이미지)
       · description → 판정 안 함 (여러 장면을 이어 붙인 긴 이미지라 정확도 낮음)
  3. 색상비교(color_compare) · 옵션(option) 이미지만 이미지 서버에서 300px로 받아 메모리에서 계산
       · 배경 제거 → 피부 픽셀 비율 · 제품색 픽셀 비율 · 균일도 · 무늬 밀도 → 규칙으로 판정
       · 이미지는 저장하지 않음 (계산 후 버림)
  4. 결과
       · image_applied_metrics.csv : URL별 계산값 + 판정 (중간 저장, 끊겨도 이어서 진행)
       · image_applied.csv         : 판정 결과를 채운 ERD 테이블 (원본은 image_applied_v23_backup.csv 로 보관)

실행 예
  python oliveyoung_applied_judge_v1.py --sample 300     # 기준값 조정용: 색상비교 300장만 판정 + 미리보기 HTML
  python oliveyoung_applied_judge_v1.py                  # 전체 판정 후 image_applied.csv 갱신
  python oliveyoung_applied_judge_v1.py --dir out_v23 --types color_compare,option,color_chip

실제 DB 적재 시에도 같은 방식: 수집 스크립트는 URL만 적재 → 적재 완료 후 이 판정 스크립트를 따로 실행
"""

import argparse
import csv
import html
import os
import random
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import oliveyoung_color_poc16 as oy

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT_VERSION = "applied-judge-v1.3"
WORKERS = 3  # 동시에 받는 이미지 수 (8에서 연결 끊김이 잦아 낮춤)
RETRY_WAITS = [5, 15, 45]  # 연결이 끊기면 이 간격(초)으로 다시 시도

# ───────── 판정 기준값 (v1.1: 표본 300장 검토 결과 반영) ─────────
SKIN_CR = (133, 173)  # 피부 '후보'로 보는 Cr 범위 (YCrCb)
SKIN_CB = (77, 127)  # 피부 '후보'로 보는 Cb 범위
CHROMA_MIN = 25  # 유채색 기준 (RGB 최댓값-최솟값) – 색 추출과 같은 값
SKIN_TONE_DIST = 30  # 대표 피부색과 RGB 거리 이 이내 = 진짜 피부
PRODUCT_DIST = 40  # 대표 피부색과 RGB 거리 이 초과 + 유채색 = 제품색
APPLIED_SKIN = 0.25  # 진짜 피부 비율이 이 이상이고
APPLIED_PRODUCT = 0.03  #   제품색 비율이 이 이상이고
SKIN_BORDER_MIN = 0.05  #   테두리에 피부가 닿아 있거나(또는 배경이 피부색이거나)
SKIN_ALONE = 0.40  #   테두리에 안 닿아도 피부가 이만큼 크면 applied
WHITE_BG_LUM = 200  # 배경 밝기가 이 이상 + 무채색이면 '흰 배경'
PACKAGE_EDGE = 0.12  # (v1.2부터 판정에 안 씀, 기록용)
CHIP_UNIFORM = 0.60  # (v1.2부터 판정에 안 씀, 기록용)
DARK_LUM = 70  # 밝기 이 미만 = 어두운 픽셀 (눈동자 · 속눈썹 · 입술 선 · 머리카락)
NO_DARK = 0.001  # 어두운 픽셀이 이 미만이면 '사람 사진 아님' 쪽으로 봄
APPLIED_FLAT_MAX = (
    0.40  #   + 거의 같은 색 비율이 이 이상이면 applied 대신 chip (제품 질감 클로즈업)
)
PHOTO_FLAT_MAX = (
    0.15  # 배경 없는 사진에서 거의 같은 색 비율이 이 미만 = 입술 · 얼굴 사진 → applied
)
GRAY_CHROMA = 20  # 이 미만 = 무채색 (용기의 검정 · 회색 · 은색 · 흰색)
GRAY_LUM_MAX = 200  # 무채색 중 밝기 이 미만 = 회색 · 검정 (흰색 제외)
PACKAGE_GRAY = 0.07  # 흰 배경 + 제품 영역 중 회색 · 검정 비율 이 이상 → package (v1.3: 0.10 → 0.07)
PACKAGE_ACHRO = 0.30  # 또는 무채색(흰색 포함) 이 이상이면서 (v1.3: 0.35 → 0.30)
PACKAGE_GRAY_MIN = 0.01  #   회색 · 검정이 이 이상 → package (흰 용기 · 투명 튜브 · 쿠션) (v1.3: 0.03 → 0.01)
FLAT_DIST = 12  # 대표색과 RGB 거리 이 이내 = 거의 같은 색
SKIN_CHIP_FLAT = 0.60  # 피부색으로 꽉 찬 사진인데 거의 같은 색이 이 이상 → 베이지 컬러칩 (실제 피부는 그늘 · 주름으로 낮음)

COMPUTE_TYPES = ("color_compare", "option")
RULE_TYPES = {"thumbnail": "package", "color_chip": "chip"}

METRIC_COLS = [
    "image_url",
    "image_type",
    "method",
    "applied_type",
    "applied_conf",
    "skin_frac",
    "product_frac",
    "uniformity",
    "edge_density",
    "skin_border",
    "white_bg",
    "flat",
    "dark",
    "achro",
    "gray",
    "note",
    "judged_at",
]


def ycrcb(p):
    r, g, b = p[:3]
    cr = 128 + 0.5 * r - 0.4187 * g - 0.0813 * b
    cb = 128 - 0.1687 * r - 0.3313 * g + 0.5 * b
    return cr, cb


def is_skin(p):
    cr, cb = ycrcb(p)
    return SKIN_CR[0] <= cr <= SKIN_CR[1] and SKIN_CB[0] <= cb <= SKIN_CB[1]


def measure(im):
    """반환: 진짜 피부 비율, 제품색 비율, 균일도, 무늬 밀도, 테두리 피부 비율, 흰 배경 여부, 배경이 피부색인지

    v1 → v1.1 바뀐 점 (표본 300장 오판 원인)
      · 누드 · 코랄 · 핑크 립과 베이지 컬러칩이 피부색 범위에 들어가 '전부 피부'로 잡힘
        → 피부 후보 중 가장 흔한 색을 '대표 피부색'으로 정하고,
          대표 피부색과 가까운 픽셀만 진짜 피부, 충분히 다른 유채색 픽셀은 제품색으로 셈
      · 흰 종이 위에 바른 스와치가 applied 로 오판 (제품색이 피부 후보로 잡힘)
        → 피부가 이미지 테두리에 닿아 있는지(손 · 얼굴은 화면 밖으로 이어짐)를 같이 봄
      · 무늬 있는 컬러칩(펄 · 텍스처)이 package 로 오판
        → package 는 흰 배경 위 사진일 때만, 배경 없이 꽉 찬 색 · 텍스처 사진은 chip"""
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
    n = len(allp) or 1
    dist = lambda a, b: sum((a[k] - b[k]) ** 2 for k in range(3)) ** 0.5

    cand = [p for p in allp if is_skin(p)]
    if cand:
        tone = [
            sorted(p[k] for p in cand)[len(cand) // 2] for k in range(3)
        ]  # 대표 피부색
        skin = [p for p in allp if dist(p, tone) <= SKIN_TONE_DIST]
        skin_border = sum(1 for p in border if dist(p, tone) <= SKIN_TONE_DIST) / len(
            border
        )
    else:
        tone, skin, skin_border = None, [], 0.0
    bg_is_skin = tone is not None and dist(bg, tone) <= SKIN_TONE_DIST
    white_bg = max(bg) - min(bg) < CHROMA_MIN and sum(bg) / 3 >= WHITE_BG_LUM
    product = sum(
        1
        for p in allp
        if max(p) - min(p) >= CHROMA_MIN
        and (tone is None or dist(p, tone) > PRODUCT_DIST)
        and (bg_is_skin or dist(p, bg) > oy.SWATCH_BG_DIST)
    )
    _, uniform = oy.score_swatch(im)
    edge = oy.inner_edge_density(im)
    med = [sorted(p[k] for p in allp)[len(allp) // 2] for k in range(3)]
    flat = (
        sum(1 for p in allp if dist(p, med) <= FLAT_DIST) / n
    )  # 거의 같은 색인 픽셀 비율 (컬러칩은 높고 실제 피부는 낮음)
    lum = lambda p: 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]
    dark = sum(1 for p in allp if lum(p) < DARK_LUM) / n
    fg = [
        p for p in allp if dist(p, bg) > oy.SWATCH_BG_DIST
    ] or allp  # 배경을 뺀 제품 영역
    achro = sum(1 for p in fg if max(p) - min(p) < GRAY_CHROMA) / len(fg)
    gray = sum(
        1 for p in fg if max(p) - min(p) < GRAY_CHROMA and lum(p) < GRAY_LUM_MAX
    ) / len(fg)
    return (
        len(skin) / n,
        product / n,
        uniform,
        edge,
        skin_border,
        white_bg,
        bg_is_skin,
        flat,
        dark,
        achro,
        gray,
    )


def decide(
    skin,
    product,
    uniform,
    edge,
    skin_border=0.0,
    white_bg=False,
    bg_is_skin=False,
    flat=0.0,
    dark=1.0,
    achro=0.0,
    gray=0.0,
):
    """규칙 판정 + 확신도(기준을 얼마나 넉넉히 넘었는지, 0~1)

    v1.1 → v1.2 바뀐 점 (표본 300장 2차 검토 결과)
      · 흰 배경 위 스와치(제품을 가운데에만 바른 사진)가 package 로 오판
        → 스와치도 결 · 그늘 때문에 무늬 밀도가 높게 나옴. 무늬 밀도 대신
          '제품 영역에 회색 · 검정(용기 · 뚜껑 · 글자)이 얼마나 있는지'로 package 판정
      · 입술 · 얼굴 클로즈업이 chip 으로 오판 (피부가 화면에 적어 applied 조건 미달)
        → 배경 없는 사진 중 '거의 같은 색' 비율이 아주 낮으면(그늘 · 입술 선 · 눈) applied
      · 파운데이션 질감 · 립 질감 클로즈업이 applied 로 오판 (피부색과 비슷)
        → 어두운 픽셀(눈 · 속눈썹 · 입술 선)이 거의 없고 색이 고르면 chip"""
    clip = lambda v: round(max(0.0, min(1.0, v)), 3)
    touches = bg_is_skin or skin_border >= SKIN_BORDER_MIN or skin >= SKIN_ALONE
    if skin >= APPLIED_SKIN and product >= APPLIED_PRODUCT and touches:
        if dark < NO_DARK and flat >= APPLIED_FLAT_MAX:
            return "chip", clip(
                (flat - APPLIED_FLAT_MAX) / (1 - APPLIED_FLAT_MAX) * 0.5 + 0.5
            )
        conf = min(
            (skin - APPLIED_SKIN) / (1 - APPLIED_SKIN) + 0.5,
            (product - APPLIED_PRODUCT) / 0.3 + 0.5,
        )
        return "applied", clip(conf)
    if white_bg:
        if gray >= PACKAGE_GRAY or (
            achro >= PACKAGE_ACHRO and gray >= PACKAGE_GRAY_MIN
        ):
            return "package", clip(max(gray / 0.3, achro) * 0.5 + 0.5)
        return "chip", clip((1 - achro) * 0.5 + 0.5)  # 흰 배경 위 스와치
    if skin >= APPLIED_SKIN and skin_border >= 0.5:
        if flat >= SKIN_CHIP_FLAT:
            return "chip", clip(
                (flat - SKIN_CHIP_FLAT) / (1 - SKIN_CHIP_FLAT) * 0.5 + 0.5
            )  # 베이지 · 누드 컬러칩
        return (
            "applied",
            0.4,
        )  # 피부 사진인데 제품색이 피부색과 비슷함 (누드 · 연한 립 등)
    if flat < PHOTO_FLAT_MAX:
        return "applied", clip(
            (PHOTO_FLAT_MAX - flat) / PHOTO_FLAT_MAX * 0.5 + 0.4
        )  # 입술 · 얼굴 클로즈업
    return "chip", clip(flat * 0.5 + 0.5)  # 배경 없이 꽉 찬 색 · 텍스처 사진


def judge_url(url):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    last = ""
    for wait in [0] + RETRY_WAITS:
        if wait:
            time.sleep(wait)
        try:
            im = oy.open_rgb(oy.download_img(url))
            m = measure(im)
            (
                skin,
                product,
                uniform,
                edge,
                skin_border,
                white_bg,
                bg_is_skin,
                flat,
                dark,
                achro,
                gray,
            ) = m
            t, conf = decide(*m)
            return {
                "applied_type": t,
                "applied_conf": conf,
                "skin_frac": round(skin, 3),
                "product_frac": round(product, 3),
                "uniformity": round(uniform, 3),
                "edge_density": round(edge, 3),
                "skin_border": round(skin_border, 3),
                "white_bg": int(white_bg),
                "flat": round(flat, 3),
                "dark": round(dark, 3),
                "achro": round(achro, 3),
                "gray": round(gray, 3),
                "note": "",
                "judged_at": now,
                "method": "computed",
            }
        except oy.RateLimited:
            raise
        except Exception as e:
            last = str(e)[:120]
    return {
        "applied_type": "",
        "applied_conf": "",
        "note": f"이미지 오류: {last}",
        "judged_at": now,
        "method": "computed",
    }


def read_csv(path):
    if not os.path.isfile(path):
        return []
    csv.field_size_limit(10**8)
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def pick_targets(out_dir, types):
    """URL → 이미지 종류 (같은 URL이 여러 종류로 쓰이면 계산 대상 종류를 우선)"""
    rank = {
        t: i
        for i, t in enumerate(
            ("color_compare", "option", "color_chip", "thumbnail", "description")
        )
    }
    url_type = {}
    for r in read_csv(os.path.join(out_dir, "image.csv")):
        u, t = r["image_url"], r["image_type"]
        if t not in types:
            continue
        if u not in url_type or rank.get(t, 9) < rank.get(url_type[u], 9):
            url_type[u] = t
    return url_type


def write_preview(path, rows):
    groups = {}
    for r in rows:
        groups.setdefault(r["applied_type"] or "error", []).append(r)
    parts = [
        "<meta charset='utf-8'><style>body{font-family:sans-serif}div.c{display:inline-block;"
        "width:170px;margin:4px;font-size:11px;vertical-align:top}img{width:160px;height:160px;"
        "object-fit:contain;background:#eee}</style><h1>발린 사진 판정 미리보기</h1>"
    ]
    for t in ("applied", "chip", "package", "other", "error"):
        items = groups.get(t, [])
        parts.append(f"<h2>{t} ({len(items)})</h2>")
        for r in items:
            parts.append(
                f"<div class='c'><img src='{html.escape(r['image_url'])}?RS=300x0'><br>"
                f"conf {r.get('applied_conf', '')} · skin {r.get('skin_frac', '')} · "
                f"prod {r.get('product_frac', '')}<br>uni {r.get('uniformity', '')} · "
                f"edge {r.get('edge_density', '')} · flat {r.get('flat', '')} · dark {r.get('dark', '')} · gray {r.get('gray', '')} · border {r.get('skin_border', '')} · white {r.get('white_bg', '')} "
                f"{html.escape(r.get('note', ''))}</div>"
            )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="out_v23", help="수집 결과 폴더 (image.csv 위치)")
    ap.add_argument(
        "--types",
        default="color_compare,option,color_chip,thumbnail",
        help="판정할 이미지 종류 (쉼표 구분). color_chip 을 계산하려면 --compute-chip",
    )
    ap.add_argument(
        "--compute-chip", action="store_true", help="컬러칩도 내려받아 계산"
    )
    ap.add_argument(
        "--sample",
        type=int,
        default=0,
        help="색상비교 이미지 N장만 판정 + 미리보기 HTML",
    )
    args = ap.parse_args()

    out_dir = os.path.join(HERE, args.dir)
    types = [t.strip() for t in args.types.split(",") if t.strip()]
    compute_types = set(COMPUTE_TYPES) | (
        {"color_chip"} if args.compute_chip else set()
    )
    url_type = pick_targets(out_dir, types)

    if args.sample:
        cands = [u for u, t in url_type.items() if t == "color_compare"]
        random.seed(42)
        url_type = {
            u: "color_compare"
            for u in random.sample(cands, min(args.sample, len(cands)))
        }
        metrics_path = os.path.join(out_dir, f"image_applied_sample{args.sample}.csv")
    else:
        metrics_path = os.path.join(out_dir, "image_applied_metrics.csv")

    if args.sample and os.path.isfile(metrics_path):
        os.remove(
            metrics_path
        )  # 표본은 기준값을 바꿔 다시 돌리는 용도라 매번 새로 계산
    done = {r["image_url"] for r in read_csv(metrics_path) if r.get("applied_type")}
    todo_rule = [
        (u, t) for u, t in url_type.items() if u not in done and t not in compute_types
    ]
    todo_calc = [
        (u, t) for u, t in url_type.items() if u not in done and t in compute_types
    ]
    print(
        f"대상 {len(url_type)}개 | 이미 판정 {len(done)} | 규칙 처리 {len(todo_rule)} | 내려받아 계산 {len(todo_calc)}"
    )

    new_file = not os.path.isfile(metrics_path) or os.path.getsize(metrics_path) == 0
    f = open(metrics_path, "a", encoding="utf-8-sig", newline="")
    w = csv.DictWriter(f, fieldnames=METRIC_COLS, extrasaction="ignore")
    if new_file:
        w.writeheader()
    lock = threading.Lock()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for u, t in todo_rule:
        w.writerow(
            {
                "image_url": u,
                "image_type": t,
                "method": "type_rule",
                "applied_type": RULE_TYPES.get(t, ""),
                "applied_conf": "",
                "note": "" if t in RULE_TYPES else "판정 제외 종류",
                "judged_at": now,
            }
        )
    f.flush()

    started = time.time()
    n_ok = n_err = 0
    pool = ThreadPoolExecutor(max_workers=WORKERS)
    futs = {pool.submit(judge_url, u): (u, t) for u, t in todo_calc}
    try:
        for i, fut in enumerate(as_completed(futs), 1):
            u, t = futs[fut]
            res = fut.result()
            res.update({"image_url": u, "image_type": t})
            with lock:
                w.writerow(res)
                f.flush()
            if res["applied_type"]:
                n_ok += 1
            else:
                n_err += 1
            if i % 200 == 0 or i == len(futs):
                print(
                    f"   {i}/{len(futs)} 완료 (오류 {n_err}) · {oy.fmt_dur(time.time() - started)}"
                )
    except oy.RateLimited as e:
        print(f"중단: {e} — 다시 실행하면 이어서 진행합니다")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        f.close()

    latest = {}
    for r in read_csv(metrics_path):  # 같은 URL을 다시 시도한 경우 마지막 결과만 사용
        latest[r["image_url"]] = r
    rows = list(latest.values())
    from collections import Counter

    print(
        "\n판정 결과:",
        dict(
            Counter(
                r["applied_type"] or "(오류)" for r in rows if r["method"] == "computed"
            )
        ),
    )

    if args.sample:
        prev = os.path.join(out_dir, f"applied_preview_sample{args.sample}.html")
        write_preview(prev, [r for r in rows if r["method"] == "computed"])
        print(
            f"미리보기: {prev}  (브라우저로 열어 판정이 맞는지 확인 → 위쪽 기준값 조정)"
        )
        return 0

    # ERD 테이블 image_applied.csv 갱신 (원본 백업)
    target = os.path.join(out_dir, "image_applied.csv")
    if os.path.isfile(target):
        backup = os.path.join(out_dir, "image_applied_v23_backup.csv")
        if not os.path.isfile(backup):
            shutil.copyfile(target, backup)
        base_rows = read_csv(target)
        cols = (
            list(base_rows[0].keys())
            if base_rows
            else ["image_url", "applied_type", "applied_conf", "judged_at"]
        )
    else:
        base_rows, cols = [], ["image_url", "applied_type", "applied_conf", "judged_at"]
    cols = [c for c in cols if c != "applied_checked"]  # 사람 확인 칸은 쓰지 않음
    judged = {r["image_url"]: r for r in rows if r.get("applied_type")}
    urls = [r["image_url"] for r in base_rows] or list(judged)
    with open(target, "w", encoding="utf-8-sig", newline="") as g:
        ww = csv.DictWriter(g, fieldnames=cols, extrasaction="ignore")
        ww.writeheader()
        for u in urls:
            j = judged.get(u, {})
            ww.writerow(
                {
                    "image_url": u,
                    "applied_type": j.get("applied_type", ""),
                    "applied_conf": j.get("applied_conf", ""),
                    "judged_at": j.get("judged_at", ""),
                }
            )
    filled = sum(1 for u in urls if u in judged)
    print(
        f"image_applied.csv 갱신: {filled}/{len(urls)} 행 판정 ({filled / max(len(urls), 1) * 100:.1f}%)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
