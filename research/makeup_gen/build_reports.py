"""VISHUE 메이크업 생성 모델 보고서 2종 (HTML → Chrome headless PDF).
사용: python build_reports.py <eval_dir> <out_dir>
글꼴: 맑은 고딕이 있으면 우선, 없으면 Noto Sans CJK KR (CSS font-family 순서).
"""
import sys, os, json, base64, subprocess, html, datetime
EV, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
M = json.load(open(os.path.join(EV, 'metrics.json'), encoding='utf-8'))
SW = json.load(open(os.path.join(EV, 'metrics_sweep.json'), encoding='utf-8')) if os.path.exists(os.path.join(EV, 'metrics_sweep.json')) else None
R = M['rows']; S = M['summary']
TODAY = '2026-11-20'

def img(name, width='100%', cap=None):
    p = os.path.join(EV, name)
    if not os.path.exists(p): return f'<div class="miss">그림 없음: {name} (미측정)</div>'
    b = base64.b64encode(open(p, 'rb').read()).decode()
    c = f'<figcaption>{cap}</figcaption>' if cap else ''
    return f'<figure><img src="data:image/png;base64,{b}" style="width:{width}">{c}</figure>'

def table(head, rows, widths=None, cls=''):
    cg = ''.join(f'<col style="width:{w}">' for w in widths) if widths else ''
    th = ''.join(f'<th>{h}</th>' for h in head)
    tr = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows)
    return f'<table class="{cls}"><colgroup>{cg}</colgroup><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>'

def rng(prefix, key, fmt='{:.2f}'):
    s = (S.get(prefix) or {}).get(key)
    if not s: return '<span class="na">미측정</span>'
    if abs(s['max'] - s['min']) < 1e-9: return fmt.format(s['mean'])
    return f"{fmt.format(s['mean'])} <span class='sm'>({fmt.format(s['min'])}~{fmt.format(s['max'])})</span>"

CSS = """
@page { size: A4; margin: 15mm 14mm 16mm 14mm; }
* { box-sizing: border-box; }
body { font-family: 'Malgun Gothic','맑은 고딕','Noto Sans CJK KR','Noto Sans KR',sans-serif; color:#1f2430; font-size:9.3pt; line-height:1.5; margin:0; }
h1.cover { font-size:17pt; color:#1a2744; margin:0 0 4px; letter-spacing:-0.3px; }
.sub { color:#2a6f7f; font-size:10pt; margin-bottom:10px; }
.band { height:5px; background:linear-gradient(90deg,#1a2744,#2a6f7f 60%,#c77276); margin:6px 0 12px; border-radius:2px; }
h2 { font-size:12.5pt; color:#1a2744; border-left:4px solid #2a6f7f; padding-left:8px; margin:16px 0 7px; break-after:avoid; }
h3 { font-size:10.3pt; color:#2a6f7f; margin:10px 0 5px; break-after:avoid; }
p { margin:4px 0 6px; }
table { width:100%; border-collapse:collapse; margin:6px 0 10px; font-size:8.2pt; break-inside:avoid; table-layout:fixed; }
th { background:#eef2f6; color:#1a2744; font-weight:700; text-align:left; }
th, td { border:0.6px solid #c5cdd6; padding:3.5px 5px; vertical-align:top; word-break:keep-all; overflow-wrap:anywhere; }
tr:nth-child(even) td { background:#fafbfd; }
figure { margin:6px 0 10px; break-inside:avoid; text-align:center; }
figure img { border:0.6px solid #dde3ea; }
figcaption { font-size:8pt; color:#555; margin-top:3px; text-align:left; }
.note { background:#fff6e8; border-left:3px solid #e0a040; padding:6px 9px; font-size:8.6pt; margin:6px 0 10px; break-inside:avoid; }
.key { background:#eef6f7; border-left:3px solid #2a6f7f; padding:7px 10px; margin:6px 0 10px; break-inside:avoid; }
.na { color:#a05a00; font-weight:700; }
.sm { color:#666; font-size:7.6pt; }
.good { color:#1d7a46; font-weight:700; } .bad { color:#b3261e; font-weight:700; }
.pb { break-before:page; }
.miss { border:1px dashed #c9a; color:#a05a00; padding:20px; text-align:center; }
ul { margin:3px 0 7px 16px; padding:0; } li { margin:1.5px 0; }
.two { display:flex; gap:10px; } .two > div { flex:1; }
.meta { font-size:8pt; color:#555; }
.src a { color:#2a6f7f; text-decoration:none; } .src li { font-size:7.6pt; line-height:1.35; margin:0.5px 0; }
"""

def page(title, sub, body, foot):
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>{title}</title><style>{CSS}
@page {{ @bottom-left {{ content: "{foot}"; font-size:7pt; color:#777; }} @bottom-right {{ content: counter(page) " / " counter(pages); font-size:7pt; color:#777; }} }}
</style></head><body><h1 class="cover">{title}</h1><div class="sub">{sub}</div><div class="band"></div>{body}</body></html>"""

# ---------- 공통 수치 ----------
A = R['A_bare']; E = R['E_real']
mm_runs = [R[f'C_MagicMakeup_lip_seed{i}'] for i in range(3)]
sm_runs = [R[f'D_StableMakeup_full_seed{i}'] for i in range(3)]
B0 = R.get('B_VISHUE_AR_frame0')

def best_sweep():
    if not SW: return None
    return min(((k, v) for k, v in SW['rows'].items() if 'glow' not in k), key=lambda kv: kv[1]['dE00_lip_vs_E_real'])

def best_glossy():
    if not SW: return None
    return min(((k, v) for k, v in SW['rows'].items() if '_glossy_' in k and k.startswith('real')), key=lambda kv: kv[1]['dE00_lip_vs_E_real'])

# ---------- 공통 섹션: 진행 방식과 근거 ----------
RATIONALE = f"""
<h2>진행 방식과 근거</h2>
<p>이 보고서의 실험 설계를 왜 이렇게 정했는지, 그리고 처음 계획과 달라진 점을 정리했습니다.</p>
<h3>1. 비교 기준을 '실제로 바른 사진(E)'으로 둔 이유</h3>
<ul>
<li>11/19 멘토링(3쪽)의 핵심 검증 질문은 <b>"사용자가 실제 제품을 발랐을 때와 얼마나 유사한가"</b>입니다. 그래서 정답 기준은 생성 모델끼리의 우열이 아니라 E입니다.</li>
<li>멘토 권고에 따라 범위를 <b>립 제품 1개</b>(롬앤 더 쥬시 래스팅 틴트 03 베어 그레이프)로 줄였고, 지표는 <b>2~3개</b>(색, 영역, 보존)로 단순화했습니다.</li>
</ul>
<h3>2. 모델별 적용 범위를 다르게 둔 이유 (MagicMakeup = 립만, Stable-Makeup = 얼굴 전체)</h3>
{table(['모델', '이번 실행', '그렇게 한 이유'], [
 ['VISHUE AR', '입술만', '앱이 실제로 하는 일이 립 제품 1개를 입술에 칠하는 것이므로 그대로 사용'],
 ['MagicMakeup', '<b>입술만</b> (<code>--label lip</code>)', '공식 코드가 부위 지정(eyes / lip / face)을 지원함. AR과 같은 조건(입술만)으로 맞출 수 있어 이것을 택함'],
 ['Stable-Makeup', '<b>얼굴 전체</b> (부위 지정 불가)', '공식 추론 코드에 부위를 고르는 옵션이 없음. 레퍼런스 얼굴의 화장 전체를 한 번에 옮기도록 설계되어 있어, 입술만 실행하는 것은 모델의 원래 동작이 아님'],
], ['17%', '23%', '60%'])}
<ul>
<li><b>MagicMakeup을 얼굴 전체 모드로 다시 돌리지 않은 이유:</b> 레퍼런스 사진(E)에는 립 제품만 발라져 있습니다. 얼굴 전체 모드는 립이 아니라 E 사진의 피부톤, 조명, 안경까지 옮길지를 보는 실험이 되어 멘토의 질문(제품 재현)과 맞지 않습니다. 또 RunPod를 다시 써야 해서(설치 약 10분 + 추론 약 10분) 비용 대비 얻는 정보가 적다고 판단했습니다.</li>
<li><b>Stable-Makeup 결과에서 입술만 잘라 붙이지(D′) 않은 이유:</b> 그렇게 하면 모델 출력이 아니라 후처리 결과가 됩니다. 이번 보고서는 각 모델을 <b>원래 할 수 있는 방식 그대로</b> 보여 주는 것을 원칙으로 했습니다.</li>
<li><b>공정성 확보 방법:</b> 적용 범위는 다르지만 <b>평가는 모든 열을 같은 입술 영역 지표로</b> 했습니다(입술 색 ΔE00, 입술 형태 IoU / Boundary F1, 입술 밖 변화). Stable-Makeup의 얼굴 전체 변화는 감점 요소가 아니라 <b>'입술만 따로 적용할 수 없다'는 모델 특성</b>으로 수치화했습니다. AR은 입술만 바꿔야 하므로 이 특성 자체가 비교 결과입니다.</li>
</ul>
<h3>3. 실행 환경을 이렇게 고른 이유</h3>
{table(['결정', '근거 (실측 / 확인)'], [
 ['Stable-Makeup → 무료 Colab T4', 'SD 1.5, 512px 모델이라 T4(15GB)로 충분. 실측 최대 VRAM 약 10GB, 이미지 1장 약 31초, 비용 $0'],
 ['MagicMakeup → RunPod RTX A6000 48GB', 'FLUX.1-Kontext-dev 12B 기반. 실측 VRAM 최대 33.4GB(nvidia-smi). 무료 Colab은 VRAM 15GB, RAM 약 12.7GB라 offload를 써도 모델(약 34GB)이 RAM에 들어가지 않음. Colab Pro(월 $9.99)보다 RunPod 단발 사용($0.18 실측)이 저렴'],
 ['Secure Cloud, 볼륨 없음, 사용 후 즉시 삭제', '얼굴 사진을 외부 GPU에 올리므로 노출 기간을 최소화. 결과는 해시로 PC 수신을 확인한 뒤 Pod를 Terminate'],
 ['ART 미실행, DreamMakeup 보류', 'ART는 학습 코드가 미공개라 재학습할 수 없고 같은 FLUX 기반이라 보조 후보로 둠. DreamMakeup은 공식 추론 코드가 없음 (PDF① 참고)'],
], ['32%', '68%'])}
<h3>4. 처음 계획과 달라진 점 / 부딪힌 문제</h3>
<ul>
<li><b>사용자 얼굴 사용:</b> 기존 <code>env_check.md</code>, <code>README.md</code>에는 "사용자 얼굴은 쓰지 않는다"고 적혀 있었습니다. 이번에는 사용자가 <b>본인 사진과 실제 착용 사진을 제공하고 사용을 승인</b>해서 그 방침을 바꿨습니다. 외부 업로드(Colab Drive, RunPod)도 사전 승인을 받았습니다.</li>
<li><b>MagicMakeup 공식 requirements 충돌:</b> <code>mediapipe==0.10.21</code>(protobuf&lt;5 필요)과 <code>protobuf==5.29.6</code>이 동시에 고정되어 있었습니다. mediapipe만 <code>--no-deps</code>로 따로 설치해 해결했고, 추론에 쓰이는 패키지 버전은 바꾸지 않았습니다.</li>
<li><b>Stable-Makeup 저장소 문제:</b> <code>infer_kps.py</code>에 문법 오류가 있고 의존성 핀끼리 충돌해서, 같은 계산을 하는 실행 스크립트를 따로 작성했습니다(tokenizers 0.14.1, datasets 2.14.6, setuptools&lt;70 추가).</li>
<li><b>순환성:</b> E는 생성 모델의 레퍼런스이면서 동시에 정답입니다. 멘토 자료상 다른 '바른 후' 사진이 없어 분리할 수 없었고, 이 한계를 결과 해석에 반영했습니다.</li>
<li><b>AR 보정 실험의 성격:</b> AR 색을 E에서 뽑은 값으로 바꾼 실험은 <b>같은 사진에 맞춘 보정</b>이라 독립 검증이 아닙니다. 다른 조명이나 다른 사람으로 다시 확인해야 합니다.</li>
</ul>
"""

SOURCES = """
<h2>출처</h2><ul class="src">
<li>MagicMakeup — arXiv:2607.20924 (ECCV 2026) · <a href="https://github.com/vivoCameraResearch/Magic-Makeup">github.com/vivoCameraResearch/Magic-Makeup</a> (커밋 b4d16f5, 2026-10-14) · <a href="https://huggingface.co/Anyou/MagicMakeup">huggingface.co/Anyou/MagicMakeup</a></li>
<li>FLUX.1-Kontext-dev — <a href="https://huggingface.co/black-forest-labs/FLUX.1-Kontext-dev">huggingface.co/black-forest-labs/FLUX.1-Kontext-dev</a> (FLUX.1 [dev] Non-Commercial License)</li>
<li>Stable-Makeup — arXiv:2403.07764 (SIGGRAPH 2025) · <a href="https://github.com/Xiaojiu-z/Stable-Makeup">github.com/Xiaojiu-z/Stable-Makeup</a> (커밋 88c8ca5)</li>
<li>ART — arXiv:2606.31089 (ECCV 2026) · <a href="https://github.com/csbowei/ART">github.com/csbowei/ART</a> · huggingface.co/csbowei/ART</li>
<li>DreamMakeup — arXiv:2510.10918 (WACV 2026) · dreammakeup.github.io</li>
<li>얼굴 분할 — jonathandinu/face-parsing (MagicMakeup 전처리) · 랜드마크 — MediaPipe Face Landmarker (face_landmarker.task, sha256 64184e22…)</li>
<li>제품 색 — 롬앤 공식몰 '더 쥬시 래스팅 틴트' COLOR CHART (2026-11-20 측정, product_target.json) · 멘토링 — VISHUE_2026-11-19_멘토링_요약.pdf (2·3·6쪽)</li>
</ul>"""

# ---------- PDF ② ----------
def pdf2():
    b = []
    bs = best_sweep()
    # 요약
    sw_line = ''
    if bs:
        n, r = bs
        sw_line = f"<li><b>AR 색을 실제 발색 기준으로 바꾸면</b> 실제 착용 사진과의 차이가 {B0['dE00_lip_vs_E_real']:.1f} → <b>{r['dE00_lip_vs_E_real']:.1f}</b>로 줄었습니다(설정: <code>{html.escape(r['lip_input']['hex'])}</code>, {r['lip_input']['texture']}, 진하기 {r['lip_input']['intensity']}). glossy를 유지하면 {best_glossy()[1]['dE00_lip_vs_E_real']:.2f}입니다. 다만 E에 맞춘 보정이라 독립 검증은 아닙니다.</li>"
    b.append(f"""<div class="key"><b>한눈에 보는 결론</b><ul>
<li><b>VISHUE AR</b>은 입술에만 정확히 적용되지만(입술 밖 변화 0), 공식몰 광고색을 그대로 칠해 <b>실제로 바른 사진보다 훨씬 진한 코랄 핑크</b>가 됩니다(실제 사진과의 입술색 차이 ΔE00 {B0['dE00_lip_vs_E_real']:.1f}, 공식몰 목표색과는 {B0['dE00_lip_vs_official_target']:.1f}).</li>
<li><b>MagicMakeup</b>(립만)은 자연스럽지만 변화가 작아, 아무것도 안 바른 맨얼굴(ΔE00 {A['dE00_lip_vs_E_real']:.2f})보다 조금 나은 수준입니다({rng('C_MagicMakeup','dE00_lip_vs_E_real')}).</li>
<li><b>Stable-Makeup</b>(얼굴 전체)은 입술색이 실제에 가장 가깝지만({rng('D_StableMakeup','dE00_lip_vs_E_real')}), 얼굴 전체 피부가 바뀌고(입술 밖 평균 ΔE00 {rng('D_StableMakeup','change_dE00_mean_outside_lip(face)')}) <b>레퍼런스 사진의 안경 자국</b>이 생깁니다.</li>
{sw_line}
<li><b>우선 적용 방향:</b> 생성 모델을 앱에 넣는 것(A, B)이 아니라, <b>실제 착용 사진에서 측정한 색과 진하기로 AR 셰이더 입력을 보정</b>(C)하고, 생성 결과는 품질 기준선으로만 사용(D)하는 것입니다.</li>
</ul></div>""")
    b.append('<h2>1. 실험 제품 및 환경</h2>')
    b.append(table(['항목', '내용'], [
        ['제품', '롬앤 더 쥬시 래스팅 틴트 <b>03 베어 그레이프</b> (공식몰 설명: 포도 속살 컬러의 핑크 베이지, glossy)'],
        ['목표색 (공식몰)', '<code>#C77276</code> · Lab(57.4, 32.0, 12.6) — 공식몰 COLOR CHART의 바른 입술 영역 중앙값. 광고 이미지라 보정과 조명을 알 수 없음'],
        ['A 맨얼굴', '사용자 정면 사진(앱 카메라 캡처) 1054×2576 → 정사각 크롭 (0,800,1054,1854) → 1024 / 512. 색 보정 없음'],
        ['E 실제 착용', '같은 사람이 제품을 바른 정면 사진 1932×2576 → 크롭 → 1024 / 512. <b>안경 착용</b>, 조명과 촬영 시점이 A와 다름'],
        ['B 입력', 'A 원본의 다른 크롭(0,660,1054,2065 → 720×960)을 가짜 카메라로 AR 페이지에 입력'],
        ['동일성 확인', '모든 입력은 디코딩한 RGB 배열 sha256으로 기록(preprocess.json, reference.json). 업로드한 파일도 해시 일치 확인'],
    ], ['20%', '80%']))
    b.append('<h3>모델별 입력 및 실행 조건</h3>')
    b.append(table(['', 'B VISHUE AR', 'C MagicMakeup', 'D Stable-Makeup'], [
        ['적용 범위', '입술만', '입술만 (<code>--label lip</code>)', '얼굴 전체 (부위 지정 불가)'],
        ['입력', 'A 프레임 + 립 상태 {hex #C77276, glossy, 0.65}', 'A 1024 + E 1024 + 얼굴 마스크 2장', 'A 512 + E 512 + 구조 이미지(SPIGA)'],
        ['코드 / 버전', '앱 스냅샷 HEAD ffad408 (faceTrackerHtml.ts 고정)', '커밋 b4d16f5 · torch 2.6.0+cu124 · diffusers 0.35.0', '커밋 88c8ca5 · 저자 핀 torch 2.0.1 · 저장소 내장 diffusers'],
        ['설정', '앱 기본 (립 기본 질감 glossy, 진하기 0.65)', '28 steps · guidance 2.5 · model_offload · seed 0/1/2', '30 steps DDIM · guidance 1.6 · fp32 · seed 0/1/2'],
        ['실행 환경', '헤드리스 Edge (SwiftShader 소프트웨어 GL)', 'RunPod RTX A6000 48GB', 'Colab Tesla T4 15GB'],
        ['처리 시간', '추적 시작까지 15.0초 · FPS <span class="na">미측정</span>(소프트웨어 GL이라 대표성 없음)', '이미지 1장 187~195초 · 모델 로드 16.8초', '이미지 1장 30.7~32.0초 · 모델 로드 55초'],
        ['최대 VRAM', '— (GPU 미사용)', '31.85GB (torch) / 33.4GB (nvidia-smi)', '약 10.0GB'],
        ['비용', '$0 (PC)', '$0.18 (RunPod 잔액 차이 실측)', '$0 (무료 Colab)'],
    ], ['14%', '27%', '30%', '29%']))
    b.append('<div class="pb"></div><h2>2. 동일 맨얼굴 비교 이미지</h2>')
    b.append(img('fig_compare_5col.png', cap='그림 1. A 맨얼굴 · B VISHUE AR · C MagicMakeup(seed 0) · D Stable-Makeup(seed 0) · E 실제 착용 사진. 아랫줄은 입술 확대(같은 비율로 크롭). B는 앱 카메라 프레임 크롭이라 화면 비율이 다르고, D는 512px 출력을 표시용으로 확대했습니다.'))
    b.append("""<div class="note"><b>육안 관찰</b><ul>
<li><b>B:</b> 입술 경계가 깔끔하고 입술 밖은 그대로지만, 색이 실제보다 훨씬 밝고 채도 높은 코랄 핑크입니다. 입술 주름과 질감이 덮여 평면적으로 보입니다.</li>
<li><b>C:</b> 얼굴과 조명이 그대로 유지되고 입술만 약간 진해졌습니다. 변화가 작아 '바른 티'가 잘 나지 않습니다.</li>
<li><b>D:</b> 입술 윤곽이 진해지고 색은 E와 비슷하지만, 피부가 전체적으로 밝아지고 <b>눈 주변과 콧등에 안경테 모양의 흰 자국</b>이 생겼습니다(E의 안경이 옮겨짐). 세 seed 모두 같은 현상입니다.</li>
<li><b>E:</b> 맨입술보다 약간 더 진하고 붉은 정도입니다. 이 제품은 이 사람에게 바르면 <b>은은하게 발색</b>됩니다.</li></ul></div>""")
    b.append('<h2>3. 평가 방법</h2>')
    b.append(table(['지표', '정의', '해석'], [
        ['① 색 정확도', '각 이미지에서 MediaPipe 478점 랜드마크로 입술 마스크(바깥 입술 − 안쪽 입)를 만들고, CIELAB(D65) 중앙값의 <b>ΔE00</b>을 E 입술색과 공식몰 목표색에 대해 계산', 'ΔE00 2.3 ≈ 눈으로 구분 가능한 최소 차이(JND). 낮을수록 좋음'],
        ['② 영역 정확도', '입술 형태 IoU, Boundary F1(허용 4px@1024), 맨얼굴 대비 ΔE00&gt;5인 변화 영역과 입술의 IoU, 변화 중 입술 밖 비율(번짐률)', '입술만 바뀌어야 함'],
        ['③ 보존', '입술 주변 21px를 뺀 얼굴 영역의 SSIM(밝기 구조)과 평균 ΔE00. LPIPS는 <span class="na">미측정</span>(평가 환경에 torch 없음)', '높은 SSIM, 낮은 ΔE00이 좋음'],
        ['보조', '랜드마크 이동량(눈 사이 거리 대비 %)', '얼굴 형태 유지'],
        ['자연스러움 1~5', '5 실제 사진과 구분 어려움 · 4 자연스럽고 작은 차이 · 3 보정 티가 나지만 수용 가능 · 2 부자연스러움 명확(스티커감, 과채도, 얼굴 변형) · 1 사용 불가', '이번 값은 1인 잠정 평가'],
    ], ['15%', '58%', '27%']))
    b.append('<div class="note">B의 변화 기준은 같은 프레임에서 AR을 끈 이미지(ar_off)입니다. AR을 끈 프레임의 입술색은 원본과 같았습니다(Lab 47.8/23.5/15.6 vs 47.6/23.6/15.6). E는 다른 촬영이라 ②·③을 계산하지 않았습니다. D는 512px에서, C는 1024px에서 비교해 SSIM의 해상도 조건이 다릅니다.</div>')
    b.append('<div class="pb"></div><h2>4. 결과: 색, 경계, 보존</h2>')
    rows = [
        ['A 맨얼굴 (아무것도 안 함)', f"{A['dE00_lip_vs_E_real']:.2f}", f"{A['dE00_lip_vs_official_target']:.2f}", '—', '—', '—', '—', '—'],
        ['<b>B VISHUE AR</b>', rng('B_VISHUE_AR', 'dE00_lip_vs_E_real'), rng('B_VISHUE_AR', 'dE00_lip_vs_official_target'), rng('B_VISHUE_AR', 'lip_shape_IoU_vs_bare', '{:.3f}'), rng('B_VISHUE_AR', 'lip_boundary_F1_vs_bare', '{:.3f}'), rng('B_VISHUE_AR', 'bleed_ratio(changed outside lip / all changed)', '{:.2f}'), rng('B_VISHUE_AR', 'change_dE00_mean_outside_lip(face)'), rng('B_VISHUE_AR', 'SSIM_outside_lip(face)', '{:.3f}')],
        ['<b>C MagicMakeup</b> (립)', rng('C_MagicMakeup', 'dE00_lip_vs_E_real'), rng('C_MagicMakeup', 'dE00_lip_vs_official_target'), rng('C_MagicMakeup', 'lip_shape_IoU_vs_bare', '{:.3f}'), rng('C_MagicMakeup', 'lip_boundary_F1_vs_bare', '{:.3f}'), rng('C_MagicMakeup', 'bleed_ratio(changed outside lip / all changed)', '{:.2f}'), rng('C_MagicMakeup', 'change_dE00_mean_outside_lip(face)'), rng('C_MagicMakeup', 'SSIM_outside_lip(face)', '{:.3f}')],
        ['<b>D Stable-Makeup</b> (전체)', rng('D_StableMakeup', 'dE00_lip_vs_E_real'), rng('D_StableMakeup', 'dE00_lip_vs_official_target'), rng('D_StableMakeup', 'lip_shape_IoU_vs_bare', '{:.3f}'), rng('D_StableMakeup', 'lip_boundary_F1_vs_bare', '{:.3f}'), rng('D_StableMakeup', 'bleed_ratio(changed outside lip / all changed)', '{:.2f}'), rng('D_StableMakeup', 'change_dE00_mean_outside_lip(face)'), rng('D_StableMakeup', 'SSIM_outside_lip(face)', '{:.3f}')],
        ['E 실제 착용', '0 (기준)', f"{E['dE00_lip_vs_official_target']:.2f}", '—', '—', '—', '—', '—'],
    ]
    b.append(table(['', '① 입술 ΔE00 vs E ↓', '입술 ΔE00 vs 공식몰색', '② 입술 형태 IoU ↑', '경계 F1 ↑', '번짐률 ↓', '③ 입술 밖 ΔE00 ↓', '입술 밖 SSIM ↑'], rows,
                   ['21%', '12%', '11%', '11%', '9%', '9%', '13%', '14%']))
    b.append('<p class="meta">값: 평균 (seed 또는 프레임 3개의 최솟값~최댓값). B는 같은 설정을 3프레임 캡처. 번짐률 = 맨얼굴 대비 ΔE00&gt;5인 얼굴 화소 중 입술(+21px) 밖 비율.</p>')
    b.append(img('fig_color_bar.png', '92%', '그림 2. 입술색과 실제 착용 사진(E)의 차이. 빨간 점선은 JND(≈2.3).'))
    b.append(img('fig_dE_maps.png', '78%', '그림 3. 기준 이미지 대비 화소별 ΔE00. B는 입술만, C는 머리카락·윤곽선의 미세 질감만(색 번짐 아님), D는 얼굴 피부 전체와 안경테 자국이 바뀜.'))
    b.append("""<div class="note"><b>수치 해석 주의</b><ul>
<li>C의 번짐률(약 0.9)은 색이 입술 밖으로 번진 것이 아닙니다. 모델이 이미지 전체를 다시 생성하면서 머리카락과 윤곽선의 미세 질감이 바뀐 것이고(그림 3), 평균 ΔE00 약 2로 눈으로 구분하기 어려운 수준입니다.</li>
<li>D의 SSIM이 C보다 높은 것은 512px 저해상도 비교라 세부 질감이 적기 때문입니다. 색 변화(ΔE00 6.3~6.7)는 D가 가장 큽니다.</li>
<li>맨얼굴(A)과 E의 차이가 3.94밖에 안 됩니다. 즉 이 제품은 이 사용자에게 은은하게 발색되어 <b>색 정확도로 모델을 가를 여지가 작습니다</b>. 또 A와 E는 조명이 달라 그 차이도 일부 섞여 있습니다.</li></ul></div>""")
    # 스윕
    b.append('<div class="pb"></div><h2>5. 실제 화장품 사진과의 차이를 줄이는 실험 (AR 입력 보정)</h2>')
    if SW:
        b.append('<p>현재 AR이 실제보다 진한 이유가 <b>입력색(광고 이미지 기준 #C77276)</b>과 <b>진하기(0.65)</b> 때문인지 확인하려고, 같은 프레임에서 AR 설정만 바꿔 렌더링했습니다. 앱 코드는 바꾸지 않았고, 연구용 렌더 스크립트에 설정 목록 옵션만 추가했습니다.</p>')
        srows = []
        for n, r in sorted(((k, v) for k, v in SW['rows'].items() if 'glow' not in k), key=lambda kv: kv[1]['dE00_lip_vs_E_real']):
            li = r['lip_input'] or {}
            srows.append([f"<code>{html.escape(li.get('hex',''))}</code>", li.get('texture', ''), f"{li.get('intensity','')}",
                          f"<b>{r['dE00_lip_vs_E_real']:.2f}</b>", f"{r['dE00_lip_vs_official_target']:.2f}", f"{r['dE00_lip_vs_bare']:.2f}",
                          f"{r['change_dE00_mean_outside_lip(face)']:.2f}", f"{r['lip_shape_IoU_vs_bare']:.3f}"])
        b.append(table(['입력색', '질감', '진하기', '입술 ΔE00 vs E ↓', 'vs 공식몰색', 'vs 맨입술', '입술 밖 ΔE00', '입술 형태 IoU'], srows,
                       ['13%', '10%', '9%', '15%', '12%', '12%', '15%', '14%']))
        b.append(img('fig_sweep.png', '100%', '그림 4. AR 설정별 입술 확대(같은 프레임). 왼쪽 위가 현재 앱 기본값, 오른쪽 아래가 실제 사진 E.'))
        bg = best_glossy()
        b.append(f'''<div class="key"><b>결과 해석</b><ul>
<li><b>원인은 입력색이었습니다.</b> 광고색 #C77276은 진하기를 0.35까지 낮춰도 실제 사진과 ΔE00 5.69 이상 차이가 납니다. 실측색 #A26263으로 바꾸면 glossy에서도 {bg[1]['dE00_lip_vs_E_real']:.2f}까지 줄어듭니다.</li>
<li><b>질감도 색을 바꿉니다.</b> 같은 #A26263이라도 glossy 질감은 입술색을 더 붉고 밝은 코랄 쪽으로 옮깁니다(a* 29~33, 입력과 E는 약 26). matte 0.5는 <b>ΔE00 1.13</b>으로 사람 눈으로 구분하기 어려운 수준(2.3)보다 낮습니다.</li>
<li><b>다만 이 제품은 glossy 제형</b>(카탈로그 기준)입니다. matte는 색은 맞지만 광택이 없어 실제 제품감과 다를 수 있습니다. 색 지표(중앙값)는 광택을 평가하지 못하므로, 다음 단계는 <b>glossy 질감에서 색을 유지하도록 셰이더의 광택 처리를 조정</b>하는 것입니다.</li>
<li>모든 설정에서 입술 밖 변화는 0, 입술 형태 IoU는 0.94 이상이었습니다. 셰이더 입력만 바꾼 것이라 실시간 구조는 그대로입니다.</li>
<li>현재 기본값의 재측정값(7.86)은 4절 B(7.98~8.03)와 약간 다릅니다. 렌더 세션이 달라서 생긴 차이입니다.</li></ul></div>''')
        b.append('<div class="note"><b>glow 설정 제외:</b> 처음 9개 설정에 glow 질감을 넣었는데, 셰이더 립 질감 목록(matte / velvet / cream / satin / sheer / glossy / shimmer)에 없는 값이라 matte로 처리됐습니다(faceTrackerHtml.ts 5954행, 결과도 matte와 사실상 동일). 앱 카탈로그에는 glow를 쓰는 제품이 없어서 앱 문제는 아니고, 실험 설정 실수라 표에서 뺐습니다.</div>')
        b.append('<div class="note"><b>#A26263</b>은 평가 기준인 E 사진의 입술 중앙값에서 뽑은 색입니다. 그래서 이 표는 <b>"실제 발색으로 맞추면 차이가 어디까지 줄어드는가"를 보는 보정 결과</b>이고 독립 검증이 아닙니다. 다른 조명이나 다른 사용자에서 다시 확인해야 합니다.</div>')
    else:
        b.append('<div class="miss">AR 설정 스윕 미실행 — 미측정</div>')
    b.append('<h2>6. 자연스러움 (1~5, 잠정)</h2>')
    sw_nat = []
    if bs:
        sw_nat = [['B′ AR 보정 (#A26263 · matte · 0.5)', '<b>3</b>', '색은 실제와 거의 같고 입술 주름이 보임. 다만 광택이 없어 glossy 제품감과 다름'],
                  ['B″ AR 보정 (#A26263 · glossy · 0.35)', '<b>3</b>', '광택은 있으나 여전히 코랄 쪽으로 밝음']]
    b.append(table(['', '점수', '근거'], [
        ['B VISHUE AR (기본값)', '<b>2</b>', '경계는 깔끔하나 과채도 코랄, 입술 질감이 덮여 스티커처럼 보임'],
        ['C MagicMakeup (립)', '<b>4</b>', '얼굴·조명 보존, 자연스러움. 다만 발색 변화가 매우 약함'],
        ['D Stable-Makeup (전체)', '<b>2</b>', '입술은 자연스러우나 안경테 자국, 피부 미백, 입술 윤곽 변형'],
    ] + sw_nat, ['30%', '12%', '58%']))
    b.append('<div class="note">위 점수는 <b>1인(Claude) 육안 잠정 평가</b>입니다. 멘토 권고대로 팀원 2명 이상이 같은 이미지를 독립 채점해 일치도를 확인해야 확정할 수 있습니다. 채점 기준은 3절의 1~5점 정의를 사용합니다.</div>')
    b.append('<div class="pb"></div><h2>7. GPU 추론 성능</h2>')
    b.append(table(['', '해상도', '1장 시간', '최대 VRAM', '모델 로드', 'GPU', '실시간(16~24fps) 대비'], [
        ['B VISHUE AR', '720×960', '프레임 단위 셰이더 (FPS <span class="na">미측정</span>)', '—', '추적 시작 15.0초', '폰 GPU (WebGL)', '실시간 설계'],
        ['C MagicMakeup', '1024', '187~195초', '33.4GB', '16.8초', 'RTX A6000', '<span class="bad">약 4,500~4,700배 느림</span>'],
        ['D Stable-Makeup', '512', '30.7~32.0초', '약 10.0GB', '55초', 'Tesla T4', '<span class="bad">약 740~770배 느림</span>'],
    ], ['16%', '9%', '18%', '11%', '12%', '13%', '21%']))
    b.append('<p class="meta">배수 = 1장 시간 ÷ (1/24초). 서버급 GPU 기준이며 모바일에서는 더 느립니다. AR의 FPS·지연·흔들림은 이번 헤드리스 렌더(소프트웨어 GL)로는 대표성이 없어 측정하지 않았습니다.</p>')
    b.append('<h2>8. 현재 VISHUE AR에 적용 가능한 기술</h2>')
    b.append(table(['적용 방식', '판단', '근거 (이번 실험)'], [
        ['A. 모바일 직접 추론', '<span class="bad">불가</span>', 'VRAM 10~33GB, 1장 30~195초(서버 GPU). Expo Go 환경에서 실행 불가'],
        ['B. 서버 실시간 추론', '<span class="bad">부적합</span>', '프레임당 수십~수백 초, 얼굴 영상 외부 전송(개인정보), GPU 비용. 정지 사진 1장 생성 서비스로만 가능'],
        ['C. 생성 결과·실사 분석 → 셰이더 반영', '<span class="good">우선 추진</span>', '실제 착용 사진에서 잰 입술색·진하기로 AR 입력을 바꾸면 차이가 크게 줄어듦(5절). 생성 모델 없이도 가능'],
        ['D. 생성 모델을 품질 기준선으로', '<span class="good">유지</span>', 'C(MagicMakeup)는 얼굴 보존과 자연스러움의 기준으로 유용. 단 생성 결과는 정답이 아님(D는 안경 자국 등 오류)'],
    ], ['24%', '13%', '63%']))
    b.append('<h3>모델별로 가져올 수 있는 요소</h3>')
    b.append(table(['모델', '참고할 점', 'AR에 바로 쓸 수 없는 이유'], [
        ['MagicMakeup', '부위별 어텐션 차단으로 입술 밖을 보존하는 방식. 맨입술 질감을 살린 채 색만 바꾸는 결과 → AR 셰이더의 "주름·질감 유지" 목표 이미지로 사용', '모델 내부 표현을 GLSL 파라미터로 바꾸는 경로가 없음. 정면 1장 결과라 회전·입 벌림에 대응하지 못함'],
        ['Stable-Makeup', '입술 윤곽(립 라인)이 진해지는 표현, 색 분포 참고', '얼굴 전체를 바꾸고 레퍼런스의 안경까지 옮김. 512px'],
    ], ['17%', '48%', '35%']))
    b.append('<h2>9. 실시간 AR 유지 및 고도화 전략</h2>')
    b.append('<ul><li><b>런타임은 그대로:</b> WebGL 셰이더, MediaPipe 478점 랜드마크, 얼굴 영상 비전송 구조를 유지합니다. 생성 모델은 앱에 넣지 않습니다(AR_SPEC 10장과 일치).</li>'
             '<li><b>제품 색 입력 정의 변경:</b> 공식몰 광고색 대신 <b>실제 착용 사진에서 측정한 입술색</b>을 제품별 입력값으로 쓰고, 진하기 기본값을 제품 발색에 맞춥니다(예: 틴트는 낮게).</li>'
             '<li><b>검증 루프:</b> 제품마다 [맨얼굴 / 착용] 사진 쌍 → 입술 ΔE00으로 AR 설정 조정 → <b>다른 조명·다른 사람의 별도 사진</b>으로 검증합니다. 이번 결과는 같은 사진에 맞춘 것이라 이 단계가 꼭 필요합니다.</li>'
             '<li><b>회귀 테스트:</b> 셰이더 입력값만 바꾸므로 FPS 영향은 없을 것으로 예상하지만, 실기기 FPS·지연·흔들림은 <span class="na">미측정</span>입니다. 변경 전후로 기존 AR 기준선과 비교해야 합니다.</li></ul>')
    b.append('<h2>10. 최종 우선 적용 방향</h2>')
    b.append('<div class="key"><ol style="margin:0 0 0 16px;padding:0">'
             '<li><b>1순위 (C):</b> 03 베어 그레이프의 AR 입력색을 실측 발색(#A26263) 기준으로 바꾸고 진하기를 낮춥니다(실험상 실제 사진과의 차이 7.9 → 1.1~3.0).</li><li><b>1-1 (셰이더):</b> glossy 질감이 색을 코랄 쪽으로 밝히는 원인을 찾아, 광택을 유지하면서 입력색을 지키도록 조정합니다.</li>'
             '<li><b>2순위 (검증):</b> 같은 제품을 다른 조명이나 다른 팀원으로 1쌍 더 촬영해, 보정값이 일반화되는지 ΔE00으로 확인합니다.</li>'
             '<li><b>3순위 (D):</b> MagicMakeup 결과를 질감 보존의 시각 기준으로 두고, 입술 주름이 덮이는 문제(B의 스티커감)를 셰이더에서 개선합니다.</li>'
             '<li><b>하지 않음 (A, B):</b> 생성 모델의 앱 탑재와 프레임 단위 서버 추론.</li></ol></div>')
    b.append('<h2>한계</h2><ul>'
             '<li>사람 1명, 제품 1개, 사진 1쌍입니다. 일반화할 수 없습니다.</li>'
             '<li>E는 생성 모델의 레퍼런스이자 정답이라 C와 D에는 순환성이 있습니다. B는 E를 입력으로 쓰지 않아 순환성이 없습니다(5절 보정 실험 제외).</li>'
             '<li>A와 E는 조명, 촬영 시점, 안경 착용 여부가 다릅니다.</li>'
             '<li>LPIPS, 실기기 FPS, 자연스러움 다수 평가자 일치도는 <span class="na">미측정</span>입니다.</li>'
             '<li>변화 판정 임계값(ΔE00 5)과 입술 주변 제외 폭(21px)은 이번 실험에서 정한 값입니다.</li></ul>')
    b.append(RATIONALE)
    b.append('<h2>재현 방법 (파일)</h2>' + table(['위치', '내용'], [
        ['research/data/makeup_gen/input/', '입력 크롭, preprocess.json, reference.json, product_target.json (git 제외)'],
        ['research/data/makeup_gen/out_magicmakeup/', 'C 결과 3장 + 패널, 얼굴 마스크, 실행 로그·pip freeze·커밋'],
        ['research/data/makeup_gen/out_stable_makeup/', 'D 결과 3장, 구조 이미지, run_log.json, sm_run.log'],
        ['research/data/makeup_gen/ar_out/ , ar_out_sweep/', 'B 프레임(AR 끔 / 켬), 설정 스윕'],
        ['research/data/makeup_gen/eval/', 'metrics.json, metrics_sweep.json, 그림'],
        ['research/makeup_gen/eval_makeup.py · eval_sweep.py · make_figs.py · build_reports.py', '지표 계산, 그림, 이 PDF 생성'],
    ], ['42%', '58%']))
    b.append(SOURCES)
    return page('VISHUE AR vs MagicMakeup vs Stable-Makeup 비교 검증',
                f'립 제품 1개(롬앤 03 베어 그레이프) · 같은 맨얼굴 · 실제 착용 사진 기준 · {TODAY}', ''.join(b),
                f'VISHUE research/makeup_gen · {TODAY} · 비교 검증')

# ---------- PDF ① ----------
def pdf1():
    b = []
    bs = best_sweep()
    b.append(f"""<div class="key"><b>요약</b><ul>
<li>2025~2026년 공개 메이크업 생성 모델 4개(MagicMakeup, Stable-Makeup, ART, DreamMakeup)를 논문, 코드, 가중치, 데이터 기준으로 조사했습니다.</li>
<li>공개 추론 코드와 가중치가 있고 바로 돌릴 수 있는 <b>MagicMakeup과 Stable-Makeup 2개를 실제로 실행</b>했습니다. ART는 보조 후보(미실행), DreamMakeup은 보류입니다.</li>
<li>두 모델 모두 품질 상한 참고로는 의미가 있지만, <b>1장 30~195초, VRAM 10~33GB</b>라 실시간 AR에 넣을 수 없습니다.</li>
<li>가장 큰 발견은 생성 모델이 아니라 <b>현재 AR의 입력색</b>이었습니다. 공식몰 광고색을 그대로 써서 실제 발색보다 훨씬 진하게 나옵니다(실제 착용 사진과의 ΔE00 {B0['dE00_lip_vs_E_real']:.1f}).{(' 실측 발색으로 바꾸면 ' + format(bs[1]['dE00_lip_vs_E_real'], '.1f') + '까지 줄어듭니다(보정 실험).') if bs else ''}</li>
<li>결론: 생성 모델은 <b>평가 기준선(D)</b>으로, 개선은 <b>실측 기반 셰이더 입력 보정(C)</b>으로 진행합니다.</li></ul></div>""")
    b.append('<h2>1. 멘토링 핵심 요구 (11/19)</h2>')
    b.append(table(['쪽', '요구', '이번 대응'], [
        ['2쪽', '평가 지표를 근거 있게 하거나, 기술 지표 2~3개 + 1~5점 정의로 축소', '색(ΔE00), 영역(IoU / F1 / 번짐), 보존(SSIM / ΔE00) + 자연스러움 1~5 정의'],
        ['3쪽', '립 제품 1개로 범위 축소', '롬앤 더 쥬시 래스팅 틴트 03 베어 그레이프 1개'],
        ['3쪽', '최신 논문·공개 모델 검토, 데이터셋과 추론 가능 여부 확인', '4개 모델 조사 (3~4절)'],
        ['3쪽', '작동하는 후보 1~2개를 실제로 비교', 'MagicMakeup, Stable-Makeup 실행 (PDF② 결과)'],
        ['3쪽', '무거운 모델로 상한 확인, 시연 품질과 경량 구현 구분', 'Colab T4 / RunPod A6000에서 실행, 실시간 AR과 분리해 평가'],
        ['3쪽', '"실제 제품을 발랐을 때와 얼마나 유사한가"', '같은 사람의 맨얼굴과 실제 착용 사진으로 입술 ΔE00 비교'],
        ['6쪽', '11/21까지 후보 실제 시험, 데이터, 구현 가능성, 육안 결과', '이 PDF와 PDF②'],
    ], ['8%', '44%', '48%']))
    b.append('<h2>2. 현재 VISHUE AR 구현 현황</h2>')
    b.append(table(['요소', '현재 구현'], [
        ['추적', 'MediaPipe Face Landmarker 478점, 프레임마다 랜드마크와 UV (components/ar/faceUV.ts, canonical face model)'],
        ['렌더', 'WebView 안 WebGL / GLSL 셰이더 (components/ar/faceTrackerHtml.ts). 립은 층 쌓기 방식, 질감(glossy / matte / glow / shimmer)과 진하기 0~1'],
        ['조명', '배경 Gray World + Gray-Edge 추정, 셀피 세그멘터'],
        ['입력', '제품 hex + 질감 + 진하기. 03 베어 그레이프 기본값: #C77276 (공식몰 측정), glossy, 0.65'],
        ['강점', '실시간, 얼굴 영상을 외부로 보내지 않음, 제품 hex를 그대로 유지, Expo Go 동작'],
        ['한계 (이번 실험)', '입력색이 광고 이미지 기준이라 실제 발색보다 진함. 입술 질감이 덮여 평면적'],
    ], ['16%', '84%']))
    b.append('<div class="pb"></div><h2>3. 최신 모델 4개 기술 분석</h2>')
    b.append(table(['', 'MagicMakeup', 'Stable-Makeup', 'ART', 'DreamMakeup'], [
        ['논문', 'arXiv:2607.20924 · ECCV 2026', 'arXiv:2403.07764 · SIGGRAPH 2025', 'arXiv:2606.31089 · ECCV 2026', 'arXiv:2510.10918 · WACV 2026'],
        ['기반', 'FLUX.1-Kontext-dev (12B) + LoRA + 이미지 가이더', 'SD 1.5 + 화장 인코더(CLIP) + 내용/구조 ControlNet', 'FLUX.1-Kontext-dev + LoRA', 'SD / SDXL, 학습 없음 (DDIM inversion 조기 중단)'],
        ['핵심 아이디어', '부위 라벨(eyes / lip / face)과 어텐션 마스크로 부위 밖 보존', '화장 특징과 얼굴 내용·구조를 분리해 레퍼런스 화장 전체 전이', 'Stage I 의사 타깃 → Stage II 실제 레퍼런스 복원 사이클', 'RGB 색 / 레퍼런스 / 텍스트로 화장 지정 (HEX 직접 입력 가능)'],
        ['부위 지정', '<span class="good">가능</span>', '<span class="bad">불가</span> (얼굴 전체)', '전체 전이 중심', '마스크 기반'],
        ['해상도', '1024', '512', '512 / 1024 LoRA (2K 주장)', '논문 기준'],
    ], ['14%', '22%', '22%', '21%', '21%']))
    b.append('<h2>4. 공개 코드·가중치·데이터셋 비교</h2>')
    b.append(table(['', 'MagicMakeup', 'Stable-Makeup', 'ART', 'DreamMakeup'], [
        ['추론 코드', '<span class="good">공개</span> test_single.py', '<span class="good">공개</span> infer_kps.py (문법 오류 있음)', '<span class="good">공개</span> infer.py', '<span class="bad">미공개</span> (의사코드만)'],
        ['학습 코드', '미공개', '공개 (train.sh)', '미공개', '해당 없음 (학습 없음)'],
        ['가중치', 'HF Anyou/MagicMakeup (safetensors) + FLUX(약관 동의)', 'Google Drive .bin 3개 + SD 1.5', 'HF csbowei/ART LoRA', '전용 가중치 없음'],
        ['데이터', '학습 6,772쌍 비공개 · MakeupHQ 이용계약 필요', 'Makeup-real 20k 비공개', 'MF2K 메타·URL만', 'QnA 46만 비공개'],
        ['라이선스', '비상업 학술 (FLUX dev 비상업)', 'Apache-2.0', 'FLUX dev 비상업', '—'],
        ['<b>이번 실행</b>', '<span class="good">실행</span> (RunPod A6000)', '<span class="good">실행</span> (Colab T4)', '<span class="na">미실행</span>', '<span class="na">실행 불가</span>'],
    ], ['14%', '22%', '22%', '21%', '21%']))
    b.append('<div class="note">논문에 보고된 수치(DINO-I, CLIP-I, Face-ID, FID 등)는 저자 벤치마크 결과이며 이번 측정과 조건이 다릅니다. 혼동을 막기 위해 이 보고서에는 인용하지 않았고, 모든 수치는 이번 실험의 실측값입니다.</div>')
    b.append('<h2>5. ART: 보조 후보로 둔 근거</h2><ul>'
             '<li>추론 코드와 LoRA는 공개되어 있어 <b>제외가 아니라 보조</b>입니다.</li>'
             '<li>학습 코드가 미공개라, 우리 제품으로 Stage II를 다시 학습할 수 없습니다.</li>'
             '<li>MagicMakeup과 같은 FLUX.1-Kontext-dev 기반이라 비용과 속도 특성이 비슷합니다. MagicMakeup이 부위 지정을 지원해 AR 조건에 더 맞으므로 우선순위를 낮췄습니다.</li>'
             '<li>재검토 조건: 같은 FLUX 환경을 다시 띄울 때 같은 입력으로 추가 실행 (약 $0.2 추정).</li></ul>')
    b.append('<h2>6. DreamMakeup: 보류 근거</h2><ul>'
             '<li>공식 추론 코드가 없습니다(2026-11-20 확인, 프로젝트 페이지에 Code 링크 없음). 논문 의사코드로 재구현하면 논문과 같다고 말할 수 없습니다.</li>'
             '<li>HEX 색을 직접 받는 유일한 후보라 제품색 입력과 잘 맞습니다. <b>코드가 공개되면 1순위로 재검토</b>합니다.</li></ul>')
    b.append('<h2>7. MagicMakeup·Stable-Makeup 선정 근거</h2>')
    b.append(table(['기준', 'MagicMakeup', 'Stable-Makeup'], [
        ['바로 실행 가능', '추론 코드 + 가중치 공개', '추론 코드 + 가중치 공개'],
        ['AR 조건과의 적합성', '<b>입술만 지정 가능</b> → AR과 같은 조건', '얼굴 전체만 → 부위 지정 기능이 없다는 점 자체를 비교'],
        ['자원', '대형(FLUX 12B, VRAM 33GB) → 품질 상한', '소형(SD 1.5, VRAM 10GB) → 무료 GPU로 실행'],
        ['서로 다른 접근', '최신 DiT + 부위 마스크', 'UNet + 화장 인코더'],
    ], ['24%', '38%', '38%']))
    b.append('<h2>8. 생성 이미지와 실시간 AR의 차이</h2>')
    b.append(table(['', '생성 모델 (C, D)', 'VISHUE AR (B)'], [
        ['입력', '정지 사진 1장 + 레퍼런스 사진', '연속 카메라 프레임 + 제품 hex·질감·진하기'],
        ['출력', '이미지 1장 (30~195초)', '16~24fps WebGL 렌더'],
        ['화장 방식', '확산 모델 샘플링 (이미지 전체 재생성)', '랜드마크 / UV 위 셰이더 층 쌓기 (입술만)'],
        ['얼굴 보존', '전체 재생성이라 미세 변화(C) 또는 큰 변화(D)', '입술 밖 변화 0 (실측)'],
        ['움직임 대응', '없음 (프레임마다 결과가 달라짐)', '프레임마다 추적'],
        ['개인정보', '서버 GPU로 얼굴 전송 필요', '얼굴 영상 외부 전송 없음'],
        ['제품 색 반영', '레퍼런스 사진의 발색을 옮김 (제품 hex 입력 없음)', '제품 hex를 그대로 칠함'],
    ], ['16%', '42%', '42%']))
    b.append(img('fig_compare_5col.png', '100%', '그림 1. 같은 맨얼굴(A)에 대한 VISHUE AR(B), MagicMakeup(C), Stable-Makeup(D)와 실제 착용 사진(E). 자세한 지표는 PDF② 참고.'))
    b.append('<h2>9. GPU 실행 환경 및 검증 결과</h2>')
    b.append(table(['단계', 'GPU 필요', '실행 환경 (실측)', '결과'], [
        ['모델 조사, 마스크, 지표, PDF', '불필요', '로컬 CPU', '완료'],
        ['VISHUE AR 렌더', '불필요', 'PC 헤드리스 Edge (소프트웨어 GL)', '완료 (추적 시작 15.0초, 오류 0)'],
        ['Stable-Makeup 추론', '필요 (≥10GB)', 'Colab Tesla T4 15GB · 최대 약 10.0GB · 1장 30.7~32.0초 · $0', '완료 (seed 3개)'],
        ['MagicMakeup 추론', '필요 (≥34GB 권장)', 'RunPod RTX A6000 48GB · 최대 33.4GB · 1장 187~195초 · $0.18', '완료 (seed 3개)'],
        ['ART 추론', '필요 (FLUX급)', '—', '<span class="na">미실행</span>'],
        ['LPIPS', '불필요 (CPU 가능)', 'torch 없는 평가 환경', '<span class="na">미측정</span>'],
    ], ['24%', '15%', '41%', '20%']))
    b.append('<p class="meta">로컬 PC에는 CUDA GPU가 없습니다(env_check.md). 외부 GPU에는 얼굴 사진 2장을 사용자 승인 후 업로드했고, 사용 후 삭제했습니다(RunPod Pod Terminate 확인, 과금 $0.000/hr). Colab Drive의 사본 정리는 남은 과제입니다.</p>')
    b.append('<h2>10. 최종 기술적 결론</h2>')
    b.append(table(['질문', '답'], [
        ['Q1. 같은 맨얼굴로 공정하게 비교할 수 있는가?', '입력(A)은 같게 맞췄습니다. 적용 범위는 모델 특성상 달라(MagicMakeup 립, Stable-Makeup 전체), <b>평가를 입술 영역 공통 지표로 통일</b>했습니다. 실제 착용 사진이 레퍼런스이자 정답이라는 순환성은 남습니다.'],
        ['Q2. AR에 도입 가능한 기술은?', '모델 자체가 아니라 <b>실측 기반 색·진하기 보정(C)</b>과 <b>품질 기준선(D)</b>입니다. MagicMakeup처럼 맨입술 질감을 살리는 표현이 셰이더 개선 목표입니다.'],
        ['Q3. GPU가 필요한 단계와 조건은?', '생성 추론만 필요합니다. Stable-Makeup은 T4(10GB), MagicMakeup은 약 34GB(A6000)였습니다(9절).'],
        ['Q4. ART / DreamMakeup 판단 근거는?', 'ART는 보조(학습 코드 미공개, MagicMakeup과 같은 기반), DreamMakeup은 공식 코드가 없어 보류입니다.'],
        ['Q5. 실제 제품과의 유사성 검증은?', '같은 사람의 맨얼굴 / 착용 사진에서 입술 ΔE00으로 측정했습니다. 다음 단계는 다른 조명·사람으로 독립 검증입니다.'],
        ['Q6. 품질을 올리면서 실시간 성능을 유지할 수 있는가?', '셰이더 입력값만 바꾸는 C 방식은 런타임 구조를 바꾸지 않습니다. 실기기 FPS 회귀는 <span class="na">미측정</span>이라 확인이 필요합니다.'],
        ['Q7. PDF 자료가 모두 확보됐는가?', '비교 이미지 5열, 지표, GPU 성능을 확보했습니다. LPIPS, 실기기 FPS, 다수 평가자 점수는 미측정으로 표시했습니다.'],
        ['Q8. 보완할 점은?', '① 독립 검증용 착용 사진 추가 ② 팀원 2명 이상 자연스러움 채점 ③ 실기기 FPS 회귀 측정 ④ 입술 질감·주름 보존 셰이더 개선 ⑤ 같은 FLUX 환경에서 ART 추가 실행.'],
    ], ['30%', '70%']))
    b.append(RATIONALE)
    b.append(SOURCES)
    return page('VISHUE AR 최신 메이크업 생성 모델 탐색 및 기술 검증',
                f'멘토링 11/19 반영 · 후보 4개 조사 · 2개 실제 실행 · {TODAY}', ''.join(b),
                f'VISHUE research/makeup_gen · {TODAY} · 생성 모델 탐색')

def to_pdf(htmlstr, name):
    hp = os.path.join(OUT, name + '.html'); pp = os.path.join(OUT, name + '.pdf')
    open(hp, 'w', encoding='utf-8').write(htmlstr)
    chrome = next((c for c in ['google-chrome', 'chromium', r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
                               r'C:/Program Files/Google/Chrome/Application/chrome.exe'] if os.path.exists(c) or subprocess.run(['which', c], capture_output=True).returncode == 0), None)
    subprocess.run([chrome, '--headless=new', '--no-sandbox', '--disable-gpu', '--no-pdf-header-footer',
                    f'--print-to-pdf={pp}', 'file://' + os.path.abspath(hp)], check=True, capture_output=True, timeout=120)
    os.remove(hp)
    return pp

print(to_pdf(pdf1(), 'VISHUE_최신_메이크업_생성모델_탐색'))
print(to_pdf(pdf2(), 'VISHUE_MagicMakeup_StableMakeup_AR_비교검증'))
