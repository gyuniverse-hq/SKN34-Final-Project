"""Build the Sullyoon look status PDF (same layout as VISHUE_AR_look6_status): HTML with local images -> Chrome PDF.

Internal document: it embeds frames of a public video and user captures, so it is written only under the ignored
research/data/look6/report/ and must not be committed or distributed.
"""
from __future__ import annotations

import html
from pathlib import Path

import cv2
from mediapipe.tasks.python import BaseOptions, vision
from playwright.sync_api import sync_playwright

from blend_modes import DATA, ROOT, landmarks

VIDEO = DATA / 'e1gSkUdG6Bo'
OUT = DATA / 'report'
IMG = OUT / 'img'
CHROME = r'C:\Program Files\Google\Chrome\Application\chrome.exe'

STAGES = [
    ('bare', VIDEO / 'photos/front_bare.png', '맨얼굴'),
    ('d1109', VIDEO / 'photos/front_app.png', '11-09 제품 색 그대로'),
    ('d1113', VIDEO / 'photos_prev/front_shown.png', '11-13 룩 모드 1차'),
    ('d1114a', VIDEO / 'natural_before/front_shown.png', '11-14 6항목 보강'),
    ('d1114b', VIDEO / 'photos_faint/front_shown.png', '11-14 실기기 후 약하게'),
    ('d1114c', VIDEO / 'photos/front_shown.png', '11-14 지금 (강도 100%)'),
]
FINAL = DATA / 'manual/e1gSkUdG6Bo_0002_final.png'


def crop(img, pts, idx, pad):
    p = pts[idx] if idx is not None else pts
    x0, y0 = p.min(axis=0)
    x1, y1 = p.max(axis=0)
    px, py = (x1 - x0) * pad, (y1 - y0) * pad
    h, w = img.shape[:2]
    return img[max(0, int(y0 - py)):min(h, int(y1 + py)), max(0, int(x0 - px)):min(w, int(x1 + px))]


def save(name, img, height):
    out = cv2.resize(img, (round(img.shape[1] * height / img.shape[0]), height), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(IMG / f'{name}.jpg'), out, [cv2.IMWRITE_JPEG_QUALITY, 86])


def shrink(src: Path, name: str, width=1700):
    img = cv2.imread(str(src))
    if img.shape[1] > width:
        img = cv2.resize(img, (width, round(img.shape[0] * width / img.shape[1])), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(IMG / f'{name}.jpg'), img, [cv2.IMWRITE_JPEG_QUALITY, 84])


def prepare_images():
    IMG.mkdir(parents=True, exist_ok=True)
    opts = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(ROOT / 'research/data/models/face_landmarker.task')), num_faces=1)
    with vision.FaceLandmarker.create_from_options(opts) as det:
        bare = cv2.imread(str(STAGES[0][1]))
        pts = landmarks(det, cv2.cvtColor(bare, cv2.COLOR_BGR2RGB))
        final = cv2.imread(str(FINAL))
        fpts = landmarks(det, cv2.cvtColor(final, cv2.COLOR_BGR2RGB))
    parts = {'face': (None, 0.3, 420), 'lips': ([61, 291, 0, 17], 0.35, 150), 'eyes': ([33, 133, 263, 362, 105, 334, 145, 374], 0.18, 150),
             'cheek': ([234, 454, 117, 346, 205, 425, 4, 168], 0.05, 260)}
    for key, path, _ in STAGES:
        img = cv2.imread(str(path))
        for part, (idx, pad, h) in parts.items():
            save(f'{key}_{part}', crop(img, pts, idx, pad), h)
    for part, (idx, pad, h) in parts.items():
        save(f'final_{part}', crop(final, fpts, idx, pad), h)
    for s in ('0.6', '1', '1.35'):
        save(f'strength_{s}', crop(cv2.imread(str(VIDEO / f'strength/front_s{s}.png')), pts, None, 0.3), 460)
    for src, name in ((VIDEO / 'strength/front_ladder.jpg', 'ladder'), (VIDEO / 'blend_modes/blush_modes.jpg', 'blush_modes'),
                      (VIDEO / 'photos/left_compare.jpg', 'left'), (VIDEO / 'photos/right_compare.jpg', 'right'),
                      (VIDEO / 'photos/open_compare.jpg', 'open'), (VIDEO / 'photos/other_strawberry_compare.jpg', 'other1'),
                      (VIDEO / 'photos/other_yearend_compare.jpg', 'other2')):
        shrink(src, name)


def sw(hex_):
    return f'<span class="sw" style="background:{hex_}"></span><code>{hex_}</code>'


def fig(name, caption, cls=''):
    return f'<figure class="{cls}"><img src="img/{name}.jpg"><figcaption>{html.escape(caption)}</figcaption></figure>'


def header(badge, meta, title, badge_cls=''):
    return (f'<div class="top"><span class="badge {badge_cls}">{badge}</span><span class="meta">{meta}</span></div>'
            f'<h1>{title}</h1>')


CSS = """
@page { size: A4; margin: 13mm 12mm 12mm; }
* { box-sizing: border-box; }
body { font-family: 'Noto Sans KR', 'Malgun Gothic', sans-serif; color: #1d2030; font-size: 9.3pt; line-height: 1.55; margin: 0; }
.page { page-break-after: always; }
.page:last-child { page-break-after: auto; }
.top { margin-bottom: 4px; }
.badge { display: inline-block; background: #b23f5f; color: #fff; font-weight: 800; border-radius: 999px; padding: 2px 11px; font-size: 8.3pt; }
.badge.navy { background: #2a3a6b; } .badge.gold { background: #a8741a; }
.meta { color: #7a7d88; font-size: 8.3pt; margin-left: 8px; }
h1 { font-size: 20pt; margin: 4px 0 6px; font-weight: 900; letter-spacing: -0.6px; }
h2 { color: #2a3a6b; font-size: 12pt; margin: 14px 0 6px; font-weight: 800; }
p { margin: 4px 0; } b { font-weight: 800; }
code { font-family: Consolas, monospace; font-size: 8pt; color: #555; }
table { width: 100%; border-collapse: collapse; font-size: 8.3pt; }
th { background: #eef1f8; color: #2a3a6b; text-align: left; padding: 5px 6px; font-weight: 800; }
td { padding: 5px 6px; border-bottom: 1px solid #eceef3; vertical-align: top; }
td.k { color: #2a3a6b; font-weight: 800; white-space: nowrap; }
td.now { background: #fbf2f4; }
td.d { color: #2a3a6b; font-weight: 800; white-space: nowrap; width: 60px; }
.callout { border: 1px solid #efc6d1; background: #fcf4f6; border-radius: 10px; padding: 9px 12px; margin-top: 10px; font-size: 8.6pt; }
.callout .hl { color: #b23f5f; font-weight: 800; }
.note { color: #6b6f7c; font-size: 8pt; margin-top: 6px; }
.strip { display: flex; gap: 5px; align-items: flex-end; }
.strip figure { margin: 0; flex: 1; text-align: center; }
.strip img { width: 100%; border-radius: 6px; display: block; }
figcaption { font-size: 7.4pt; color: #404452; margin-top: 3px; line-height: 1.3; }
figure.now figcaption { color: #b23f5f; font-weight: 800; }
figure.final figcaption { color: #2a3a6b; font-weight: 800; }
figure.now img { outline: 2px solid #b23f5f; outline-offset: -2px; }
.wide { margin: 0 0 8px; } .wide img { width: 100%; border-radius: 6px; display: block; }
.wide figcaption { text-align: left; }
.sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px; vertical-align: -1px; margin-right: 4px; border: 1px solid rgba(0,0,0,.12); }
.tag { display: inline-block; border-radius: 5px; padding: 0 6px; font-size: 7.4pt; font-weight: 800; white-space: nowrap; }
.tag.ok { background: #e3f4e8; color: #2d7a4c; } .tag.warn { background: #fde9d4; color: #b0601a; }
.tag.new { background: #e6ebfa; color: #2a3a6b; } .tag.bad { background: #fbe1e6; color: #b23f5f; }
.flow { display: flex; gap: 6px; margin: 6px 0 4px; }
.flow div { flex: 1; background: #f5f6fa; border-radius: 8px; padding: 7px 8px; font-size: 8pt; }
.flow div b { display: block; color: #2a3a6b; font-size: 8.6pt; }
.flow div code { display: block; margin-top: 2px; }
.flow div.hot { background: #fbf2f4; } .flow div.hot b { color: #b23f5f; }
.check li { margin: 3px 0; }
"""


def build_html() -> str:
    meta = '2026-11-14 · 전진영(AR 파트) · 코드 기준(브랜치 feat/ar-look-false-lashes, 미커밋 변경 포함)'
    pages = []

    # 1. Summary
    pages.append(f"""<section class="page">
{header('VISHUE · AR', meta, '설윤 뿌까 룩, 영상 완성 얼굴에 가까워지기까지')}
<p>11-09에는 영상 제품 색을 <b>그대로 공통 방식으로</b> 칠했습니다. 그 뒤 5일 동안 같은 맨얼굴에 렌더해 <b>영상 완성 얼굴과 나란히 비교</b>하면서,
화면에 그릴 때만 입히는 <b>룩 전용 색·모양·효과</b>를 만들었습니다. 실기기 피드백으로 한 번 약해진 뒤, <b>덮지 않고도 티가 나는 혼합 방식</b>과
<b>"룩 강도" 슬라이더</b>로 자연스러움과 화장한 티 사이의 타협점을 잡았습니다.</p>
<h2>한눈에 보기</h2>
<div class="strip">
  {fig('bare_face', '맨얼굴')}{fig('d1109_face', '11-09 제품 색 그대로')}{fig('d1114c_face', '지금 (룩 강도 100%)', 'now')}{fig('final_face', '영상 완성', 'final')}
</div>
<p class="note">같은 맨얼굴 캡처에 실제 AR 페이지(WebGL)로 렌더한 정지 화면입니다. 영상 완성은 영상 캡처이며 앞머리·조명·영상 필터는 재현 대상이 아닙니다.</p>
<h2>처음과 지금</h2>
<table>
<tr><th style="width:15%"></th><th style="width:36%">11-09 (시연 룩 6선 문서)</th><th>지금 (11-14)</th></tr>
<tr><td class="k">칠하는 방식</td><td>영상 제품 색을 모든 룩 공통 방식으로</td><td class="now">제품 데이터·장바구니는 그대로, <b>화면에 그릴 때만</b> 룩 전용 색·모양·효과를 입힘 (<code>lib/videoLookStyles.ts</code>)</td></tr>
<tr><td class="k">피부</td><td>파운데이션을 얇게 덮음 — 잡티·톤 그대로</td><td class="now"><b>주파수 분리</b>로 붉은기·칙칙함만 정리, 모공·솜털·그림자는 유지</td></tr>
<tr><td class="k">블러셔</td><td>볼 중앙 주황 패치 {sw('#FF928F')}</td><td class="now">핑크 {sw('#E46F8C')} <b>색상 혼합 + 소프트 라이트</b>, 크게 번지게</td></tr>
<tr><td class="k">립</td><td>밝은 주황 색 면 {sw('#E77671')}</td><td class="now">장미빛 {sw('#B0606C')} 색상 혼합, 바깥이 옅은 그라데이션·아랫입술 물광·소량 오버립</td></tr>
<tr><td class="k">아이라인</td><td>짧은 갈색 꼬리</td><td class="now">몸통에서 이어지며 가늘어지는 꼬리 {sw('#3A2A26')}</td></tr>
<tr><td class="k">속눈썹</td><td>빗살 같은 세로줄</td><td class="now">곡선으로 컬되고 끝이 가는 가닥</td></tr>
<tr><td class="k">물광·애교살</td><td>거의 안 보임</td><td class="now">볼록하고 빛받는 곳만 물광(<b>국소 대비 반사광 마스크</b>), 아래 속눈썹 밑 펄</td></tr>
<tr><td class="k">세기 조절</td><td>부위별 진하기만</td><td class="now">AR 화면 <b>"룩 강도"</b> 30~170% 한 번에 (기본 100%)</td></tr>
<tr><td class="k">다른 룩·제품 체험</td><td>—</td><td class="now">변화 없음: 다른 5룩·설윤 제품 AR이 작업 전 렌더러와 <b>같은 프레임 0픽셀 차이</b></td></tr>
</table>
<div class="callout"><span class="hl">실기기(Expo Go) 확인은 아직입니다.</span> 모든 비교는 정지 사진 렌더입니다. 실제 카메라 조명에서는 블러셔·물광 세기가 다르게 보일 수 있고,
그 차이는 룩 강도 슬라이더로 맞추거나 기본값을 다시 조정합니다. 11-13 사용자 결정으로 <b>영상 룩 AR은 원칙보다 영상 재현 품질을 우선</b>합니다(제품 AR은 기존 원칙 유지).</div>
</section>""")

    # 2. Timeline
    rows = [
        ('11-09', '<b>시연 룩 6선 정리.</b> 설윤 룩 9부위를 영상 제품 색(같은 제품 7, 가까운 색 2)으로 칠함. 제품 색을 그대로 써서 립은 밝은 주황, 블러셔는 볼 중앙 주황 패치.', 'new'),
        ('11-11', '카리나 영상으로 <b>"제품별 발림 프로필"</b> 시도 → 손 가림·겹쳐 바르기 때문에 검증 가능한 값이 없어 채택 0. 값을 실어 보낼 경로만 마련.', 'warn'),
        ('11-12', '<b>방향 전환: 제품 기준 → 룩×부위 기준.</b> 웹 Gemini의 장면 시각은 6개 모두 영상 길이부터 틀려 폐기, YouTube 자동 캡처는 제한으로 중단 → 직접 캡처. 설윤 맨얼굴·완성 캡처 확보. AR_SPEC에 "룩 AR 모드 예외"(룩 색·보정 허용) 추가.', 'new'),
        ('11-13', '립을 제품과 분리된 <b>렌더 전용 룩 색</b>으로(후보 <code>#BA5F6A</code>→<code>#8D4A50</code>). 제품 색·장바구니는 유지.', 'new'),
        ('11-13', '<b>사용자 결정: 영상 룩 AR은 원칙보다 영상 재현 우선.</b> <code>lib/videoLookStyles.ts</code> 신설, 렌더러 룩 모드(소프트 라이트 블러셔, 피부 톤, 잡티 정리, 하이라이터 글로우). 마스카라 축소, 아이라인 꼬리 연장. 혼합 방식 비교: 곱하기는 빨간 패치, 소프트 라이트가 가장 자연스러움.', 'new'),
        ('11-13', '다른 얼굴에 입혀 확인 → 밝은 피부가 <b>하얀 가면</b>처럼 됨(제품 파운데이션 자체가 원인). 룩 파운데이션 밝기 상한 + 원래 피부색 절반 유지. 애교살 둘째 색은 눈 밑이 붉어 보여 제거.', 'ok'),
        ('11-14', '<b>6항목 보강(Codex).</b> 립 바깥 감쇠·아랫입술 분절 물광·소량 오버립, 이어지는 베지어 꼬리, 3차 곡선 컬 속눈썹, 넓은 반경 잡티 정리, 펄 애교살, 따뜻한 피부 색 보정. 같은 프레임 회귀 비교 도구 추가.', 'new'),
        ('11-14', '<b>실기기 피드백:</b> 눈 밑 붉은 얼룩, 짙은 꼬리, 코·턱 얼룩, 가면 느낌 → 피부 보정을 끄고 전반을 약하게. 자연스러워졌지만 <b>맨얼굴과 거의 구분되지 않음</b>.', 'bad'),
        ('11-14', '<b>타협점:</b> 덮지 않고 티 나게 — 피부 주파수 분리, 블러셔·립 색상 혼합, 물광 국소 대비 반사광 마스크. AR 화면 <b>"룩 강도"</b> 슬라이더. 셰이더 4조합 컴파일, 다른 5룩·설윤 제품 AR 0픽셀, Jest 1,104 통과.', 'ok'),
    ]
    label = {'new': ('진행', 'new'), 'warn': ('보류', 'warn'), 'ok': ('해결', 'ok'), 'bad': ('문제', 'bad')}
    tl = ''.join(f'<tr><td class="d">{d}</td><td><span class="tag {label[k][1]}">{label[k][0]}</span> {t}</td></tr>' for d, t, k in rows)
    pages.append(f"""<section class="page">
{header('변경 이력', '11-09 → 11-14', '5일 동안 바뀐 것', 'gold')}
<table class="tl">{tl}</table>
<h2>얼굴로 보는 변화</h2>
<div class="strip">
  {''.join(fig(f'{k}_face', c, 'now' if k == 'd1114c' else '') for k, _, c in STAGES[1:])}{fig('final_face', '영상 완성', 'final')}
</div>
<p class="note">모두 같은 맨얼굴·같은 추적 프레임 렌더입니다. 11-13 1차는 진했고, 11-14 6항목 보강 뒤 실기기 피드백으로 약해졌다가, 지금은 그 사이에서 피부결을 살린 채 색이 보이게 맞췄습니다.</p>
</section>""")

    # 3. Zoom evolution
    def zoom_row(part):
        items = [fig(f'{k}_{part}', c, 'now' if k == 'd1114c' else '') for k, _, c in STAGES[1:]] + [fig(f'final_{part}', '영상 완성', 'final')]
        return f'<div class="strip">{"".join(items[:3])}</div><div class="strip" style="margin-top:4px">{"".join(items[3:])}</div>'
    pages.append(f"""<section class="page">
{header('부위별 변화', '같은 맨얼굴 · 단계별 확대', '입술, 눈, 볼은 이렇게 바뀌었습니다', 'navy')}
<h2>립</h2>{zoom_row('lips')}
<p class="note">주황 색 면 → 장미빛. 지금은 바른 색의 밝기·주름을 그대로 두고 색조만 바꾸는 <b>색상 혼합</b>으로 색이 보이면서 결이 남고, 아랫입술 가운데에 끊긴 물광이 생깁니다. 영상의 반짝임 배열과 완전히 같지는 않습니다.</p>
<h2>눈</h2>{zoom_row('eyes')}
<p class="note">떨어진 삼각형 꼬리 → 몸통에서 이어지는 꼬리. 빗살 속눈썹 → 곡선 컬 가닥. 실기기에서 "짙고 두껍다"는 의견을 반영해 두께 0.08·길이 0.3으로 중간을 잡았습니다.</p>
<h2>볼</h2>{zoom_row('cheek')}
<p class="note">주황 패치 → 넓게 번진 핑크. 붉은 패치가 됐던 곱하기 대신 색상 혼합(피부와 블러셔 채도의 중간) + 소프트 라이트로 피부결이 비칩니다.</p>
</section>""")

    # 4. Part table
    part_rows = [
        ('파운데이션', '미샤 M 퍼펙트 커버 비비크림 EX 20 쿨 베이지', '#F5DCCA', '가까운 색', '덮는 정도 0.45배 · 주파수 분리 0.6 · 핑크 톤 ' + sw('#EFC9D2') + ' 0.25', '주파수 분리, 소프트 라이트, 밝기 상한·피부색 절반 유지'),
        ('쉐딩', '페리페라 브이 쉐딩 03 그레이쉬쿨', '#D1B68D', '같은 제품', sw('#AE9598') + ' 차가운 그림자 · 0.45배', '파우더 층'),
        ('하이라이터', '캔메이크 무뉴토 하이라이터 02 로즈쿼츠', '#DAB7B2', '같은 제품', sw('#E3C6CA') + ' 콧등·눈 밑·턱 · 물광 0.6', '스크린 + 국소 대비 반사광 마스크'),
        ('블러셔', '비디비치 페탈 글로우 크림 블러시 08 보타닉 피치', '#FF928F', '같은 제품', sw('#E46F8C') + ' 크기 1.45배·번짐 최대 · 0.65배', '색상 혼합 1 + 소프트 라이트 2, 따뜻한 피부 보정'),
        ('아이브로우', '페리페라 스피디 스키니 브로우 03 내추럴 브라운', '#4B453C', '같은 제품', '같은 색 · 0.45배', '파우더'),
        ('아이섀도', '삐아 레디 투 웨어 아이 섀도우 09 모태분위기', '#E9B09F', '같은 제품', '같은 색 · 0.6배 + 애교살 펄 0.3', '곱하기 + 펄 띠'),
        ('아이라인', '키스미 스무스 리퀴드 아이라이너 N 차콜 브라운', '#493725', '같은 제품', sw('#3A2A26') + ' 꼬리 0.3 · 두께 0.08 · 10°', '이어지는 베지어 꼬리'),
        ('마스카라', '에뛰드 컬 픽스 마스카라 01 블랙', '#0F0E0E', '가까운 색', '같은 색 · 14가닥 곡선 컬 · 0.8배', '3차 곡선 가닥'),
        ('립', '이더앤 듀이 시럽 틴트 01 멜트어웨이', '#E77671', '같은 제품', sw('#B0606C') + ' 0.85배 · 오버립 0.025', '색상 혼합 0.45, 바깥 감쇠 0.45, 아랫입술 물광 2'),
    ]
    trs = ''.join(
        f'<tr><td class="k">{z}</td><td>{html.escape(v)}</td><td>{sw(h)}<br><span class="tag {"ok" if m == "같은 제품" else "warn"}">{m}</span></td>'
        f'<td class="now">{look}</td><td>{how}</td></tr>' for z, v, h, m, look, how in part_rows)
    pages.append(f"""<section class="page">
{header('K-연예인 ②', '시연 룩 · 영상 룩 모드', '설윤 뿌까 메이크업 — 부위별로 지금 이렇게 칠합니다', 'navy')}
<p><code>youtube.com/watch?v=e1gSkUdG6Bo</code> · 제품(장바구니·선택 상품)은 왼쪽 "제품 AR 색" 그대로이고, 영상 룩 AR 화면에서만 오른쪽 룩 값으로 그립니다.
배수는 룩 강도 100% 기준이며 슬라이더가 덮는 정도와 효과 세기를 함께 바꿉니다(색·모양은 그대로).</p>
<table>
<tr><th style="width:10%">부위</th><th style="width:24%">영상 속 제품</th><th style="width:14%">제품 AR 색</th><th style="width:27%">룩 모드 (지금)</th><th>방식</th></tr>
{trs}
</table>
<h2>구조</h2>
<div class="flow">
  <div><b>① 룩 슬롯</b>부위별 제품·셰이드·모양<code>lib/demoLookAr.ts</code></div>
  <div><b>② 상태 저장</b>제품 색 그대로<code>hooks/useVideoTryOn.ts</code></div>
  <div class="hot"><b>③ 룩 값 입히기</b>화면 그리기 직전에만 · 룩 강도 배율<code>lib/videoLookStyles.ts</code><code>lib/videoLookMakeup.ts</code></div>
  <div class="hot"><b>④ 렌더러 룩 모드</b>값이 있을 때만 켜짐<code>components/ar/faceTrackerHtml.ts</code></div>
  <div><b>⑤ AR 화면</b>"룩 강도" 슬라이더<code>app/(tabs)/ar.tsx</code></div>
</div>
<p class="note">룩 값이 없는 다른 5개 룩과 설윤 제품 체험은 ③·④를 지나도 계산이 같아, 작업 전 렌더러와 같은 추적 프레임에서 0픽셀 차이(<code>research/look6/check_legacy_render.py</code>).</p>
</section>""")

    # 5. Techniques
    tech = [
        ('소프트 라이트', '블러셔 · 피부 톤', '밝은 곳은 밝게, 어두운 곳은 어둡게 둔 채 색만 물들임', '곱하기는 빨간 패치처럼 떠서 제외(아래 시험)'),
        ('색상 혼합', '블러셔 · 립', '그 픽셀의 밝기 × 룩 색의 색조 → 주름·명암을 남기고 색을 확실히 입힘', '채도를 그대로 쓰면 형광 핑크 → 피부색과 절반 섞고 가장자리를 완만하게'),
        ('주파수 분리', '피부', '넓은 고리 평균(저역)만 얼굴 평균 톤으로 옮기고, 잔결(카메라 − 저역)은 그대로 더함', '덮는 파운데이션 대신 써서 가면 느낌 없이 톤 정리'),
        ('국소 대비 반사광 마스크', '하이라이터 물광 · 립 광택', '주변 평균보다 밝고 얼굴 평균보다 밝은 볼록한 곳만 반사 → 주름·모공·그늘은 빛나지 않음', '립에는 기존 <code>uGlossCavity</code>, 물광에 같은 원리 확장'),
        ('밝기 상한 · 피부색 절반 유지', '파운데이션', '이미 밝은 피부는 더 밝히지 않고 원래 색감을 절반 남김', '다른 사람 얼굴의 하얀 가면 방지'),
        ('피부톤 색 보정', '립 · 블러셔', '따뜻한 피부에서만 푸른 성분을 조금 낮춤', '보랏빛 립 방지, 설윤 정면은 0픽셀 차이'),
    ]
    trs = ''.join(f'<tr><td class="k">{a}</td><td>{b}</td><td>{c}</td><td>{d}</td></tr>' for a, b, c, d in tech)
    pages.append(f"""<section class="page">
{header('방법', '자연스러우면서 티 나게', '덮지 않고 색이 보이게 하는 방법들', 'navy')}
<table>
<tr><th style="width:17%">방법</th><th style="width:14%">쓰는 곳</th><th style="width:38%">하는 일</th><th>왜 / 시험 결과</th></tr>
{trs}
</table>
<h2>혼합 방식 시험 (11-13, 설윤 맨얼굴에 블러셔)</h2>
{fig('blush_modes', '위 줄: 제품 색 / 아래 줄: 룩 색 — 기존 파우더(볼 중앙·눈 아래), 곱하기, 소프트 라이트, 오버레이. 곱하기는 빨간 패치, 소프트 라이트·오버레이가 가장 자연스러움.', 'wide')}
<p class="note">성능: 룩 모드에서만 피부 픽셀당 카메라 읽기 8회(주파수 분리), 하이라이터 영역 4회(물광 마스크)가 늘어납니다. 실기기 FPS는 미확인.</p>
</section>""")

    # 6. Strength slider
    pages.append(f"""<section class="page">
{header('룩 강도', 'AR 화면 · 영상 룩 전용', '자연스럽게 ↔ 진하게, 사용자가 고릅니다', 'navy')}
<p>실기기에서 "너무 진하다"와 "티가 안 난다"가 모두 나와, 기본값은 그 사이(100%)로 두고 <b>AR 화면에서 직접 조절</b>하게 했습니다.
슬라이더는 영상 룩으로 들어왔고 그 룩에 룩 값이 있을 때만 보이며(지금은 설윤 뿌까), <b>덮는 정도와 효과 세기만</b> 30~170%로 함께 바꿉니다.
색·모양(꼬리, 속눈썹, 블러셔 위치)은 그대로이고, 다른 룩으로 바꾸면 100%로 돌아갑니다.</p>
{fig('ladder', '맨얼굴 | 30% | 60% | 100% (기본) | 135% | 170% | 영상 완성', 'wide')}
<div class="strip">{fig('strength_0.6', '60%')}{fig('strength_1', '100% (기본)', 'now')}{fig('strength_1.35', '135%')}{fig('final_face', '영상 완성', 'final')}</div>
<table>
<tr><th style="width:18%">강도</th><th>보이는 모습</th></tr>
<tr><td class="k">30~60%</td><td>거의 맨얼굴. 피부 톤만 살짝 정리되고 색은 은은함</td></tr>
<tr><td class="k">100% (기본)</td><td class="now">피부결은 남은 채 톤 정리, 볼 전체 은은한 핑크, 장미빛 립과 물광, 이어지는 꼬리 — 화장한 티는 나되 자연스러운 지점</td></tr>
<tr><td class="k">135~170%</td><td>영상처럼 진해짐. 170%에서는 블러셔 테두리가 보이기 시작</td></tr>
</table>
<p class="note">구현: <code>lib/videoLookMakeup.ts</code>의 <code>scaleLookOverrides</code>, 화면 <code>app/(tabs)/ar.tsx</code> (기존 <code>CoverageBar</code> 재사용, 문구 "룩 강도 · 100% / 자연스럽게 · 진하게").</p>
</section>""")

    # 7. Angles and other faces
    pages.append(f"""<section class="page">
{header('확인', '고개 돌림 · 입 벌림 · 다른 얼굴', '다른 각도와 다른 사람에게도 어색하지 않은지', 'navy')}
<p>각 줄은 <b>맨얼굴 | 제품 AR | 11-13 진한 룩 | 11-14 약한 룩 | 지금</b> 순서입니다.</p>
{fig('left', '설윤 왼쪽', 'wide')}
{fig('right', '설윤 오른쪽', 'wide')}
{fig('open', '설윤 입 벌림', 'wide')}
{fig('other1', '밝고 붉은 피부(딸기 토끼상 맨얼굴): 제품 AR은 하얀 가면처럼 뜨지만, 지금은 원래 피부색이 남음', 'wide')}
{fig('other2', '연말 수상템 맨얼굴: 지금이 가장 자연스러우면서 색이 보임', 'wide')}
<p class="note">다른 사람 사진은 설윤 룩을 입혀 어색함을 보는 용도이며, 각 영상의 룩 값이 아닙니다.</p>
</section>""")

    # 8. Checklist
    pages.append(f"""<section class="page">
{header('확인할 것', '발표·시연 전에', '아직 확인이 필요한 것')}
<ol class="check">
<li><b>실기기 확인</b> — Expo Go에서 같은 자리·조명으로 설윤 룩 정면·고개 좌우·입 벌림·깜빡임, 룩 강도 슬라이더 조절, FPS(룩 모드 피부 읽기 +8·물광 +4), 다른 룩·제품 체험이 그대로인지.</li>
<li><b>값은 측정이 아님</b> — 정지 사진 한 장을 눈으로 비교해 맞춘 값입니다. 실제 카메라 조명에서 세기가 다르면 슬라이더 또는 <code>lib/videoLookStyles.ts</code> 값을 조정합니다.</li>
<li><b>남은 차이</b> — 영상 아랫입술의 촘촘한 반짝임 배열, 얼굴 입체감(쉐딩), 깊은 잡티, 눈 형태. 앞머리·조명·영상 필터·얼굴형은 복제하지 않습니다.</li>
<li><b>설윤만 적용</b> — 다른 5개 룩은 아직 제품 색 공통 방식입니다. 렌더러 기능은 만들어져 있어 룩 값만 추가하면 됩니다(각 영상의 맨얼굴·완성 캡처 필요).</li>
<li><b>제품 AR은 그대로</b> — 룩 색·보정은 영상 룩 AR에서만. 상품 체험으로 바꾸거나 부위 제품을 바꾸면 해제됩니다.</li>
<li><b>데이터 주의</b> — 이 문서는 공개 영상 인물과 사용자 캡처를 담은 <b>내부용</b>입니다. 외부 배포·저장소 커밋 금지(<code>docs/AR_SPEC.md</code> 1-13 예외 범위).</li>
<li><b>커밋 전</b> — 이번 변경은 아직 커밋되지 않았고, 작업 트리에 다른 병합 작업이 함께 있습니다.</li>
</ol>
<p class="note">근거: <code>lib/videoLookStyles.ts</code>, <code>lib/videoLookMakeup.ts</code>, <code>components/ar/faceTrackerHtml.ts</code>, <code>app/(tabs)/ar.tsx</code>,
<code>__tests__/videoLookMakeup.test.ts</code>, <code>__tests__/videoLookRenderer.test.ts</code>, <code>research/look6/README.md</code>, <code>docs/AR_PROGRESS.md</code> (11-09~11-14).
이미지는 모두 <code>research/data/look6/e1gSkUdG6Bo/</code>의 오프라인 렌더(Git 제외).</p>
</section>""")
    return f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>{CSS}</style></head><body>{"".join(pages)}</body></html>'


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    prepare_images()
    page_html = OUT / 'VISHUE_AR_sullyoon_look.html'
    page_html.write_text(build_html(), encoding='utf-8')
    pdf = OUT / 'VISHUE_AR_sullyoon_look.pdf'
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME, headless=True)
        try:
            page = browser.new_page()
            page.route('http*://**/*', lambda route: route.abort())
            page.goto(page_html.as_uri(), wait_until='load')
            page.pdf(path=str(pdf), format='A4', print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()
    print('wrote', pdf)


if __name__ == '__main__':
    main()
