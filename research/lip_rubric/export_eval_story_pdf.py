"""Story-flow PDF with chronology fixed from research records.

Correct order after Qwen failure:
  ④ quality ladder + R5 solo labels
  ⑤ R5-only learner (weak absolute)
  ⑥ Astra mass-label → distill to score model
  ⑦ calibration + pass line

  ml/.venv/Scripts/python.exe research/lip_rubric/export_eval_story_pdf.py
"""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research" / "data" / "lip_rubric"
OUT_DIR = DATA / "learn_astra"
FIG_DIR = OUT_DIR / "report_figs_story"
PDF_PATH = OUT_DIR / "lip_eval_story_flow_20261119.pdf"
DIST = OUT_DIR / "dist_plots" / "dinov2_vits14"
PACK_IMG = DATA / "pack" / "rating_pack" / "images"
GALLERY = OUT_DIR / "pass_gallery" / "images"
FONT = r"C:\Windows\Fonts\malgun.ttf"
FONT_B = r"C:\Windows\Fonts\malgunbd.ttf"

plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False})

RUBRIC_ROWS = [
    ["Q1 결", "세로 주름이 보이는가", "색 입힌 뒤에도 주름이 또렷한가", "페인트/플라스틱이 아닌 피부처럼 보이는가",
     "주변 피부·사진 느낌과 비슷한가", "얼룩·끊김 없이 고른가"],
    ["Q2 명암", "위·아랫입술 명암이 조명·형태에 맞는가", "아랫입술이 볼록해 보이는가", "입꼬리 명암이 자연스러운가",
     "한 밝기로 납작하지 않은가", "얼굴 밝은 쪽과 입술 밝은 쪽이 같은가"],
    ["Q3 윤기", "반짝임 정도가 제형과 맞는가", "반사가 볼록한 곳에 있는가*", "반사가 조명 방향과 맞는가*",
     "반짝임이 결을 따라 퍼지는가*", "하얗게 날아간 곳이 없는가"],
    ["Q4 경계", "테두리가 가위질처럼 딱딱하지 않은가", "테두리 선명도가 다른 윤곽과 비슷한가", "테두리가 끊기지 않고 매끄러운가",
     "입꼬리에서 색이 부드럽게 사라지는가", "안쪽 선이 자연스럽게 이어지는가"],
    ["Q5 밀착", "필름처럼 떠 있지 않고 스며든 느낌인가", "폰 크기에서 어색하지 않은가", "확대해도 어색하지 않은가",
     "입술 색 분위기가 얼굴 조명과 맞는가", "실제 바른 사진으로 믿을 것 같은가"],
]


def _styles():
    pdfmetrics.registerFont(TTFont("Malgun", FONT))
    pdfmetrics.registerFont(TTFont("MalgunBold", FONT_B))
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "st", parent=base["Title"], fontName="MalgunBold", fontSize=18,
            leading=26, alignment=TA_CENTER, spaceAfter=6,
        ),
        "sub": ParagraphStyle(
            "ss", parent=base["Normal"], fontName="Malgun", fontSize=10.5,
            leading=15, alignment=TA_CENTER, textColor=colors.HexColor("#555"), spaceAfter=12,
        ),
        "h1": ParagraphStyle(
            "sh1", parent=base["Heading1"], fontName="MalgunBold", fontSize=13.5,
            leading=19, spaceBefore=10, spaceAfter=6, textColor=colors.HexColor("#1a1a1a"),
        ),
        "h2": ParagraphStyle(
            "sh2", parent=base["Heading2"], fontName="MalgunBold", fontSize=11,
            leading=15, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor("#1f4e79"),
        ),
        "body": ParagraphStyle(
            "sb", parent=base["Normal"], fontName="Malgun", fontSize=9.5,
            leading=14, alignment=TA_JUSTIFY, spaceAfter=5,
        ),
        "bullet": ParagraphStyle(
            "sbu", parent=base["Normal"], fontName="Malgun", fontSize=9.3, leading=13.2,
        ),
        "caption": ParagraphStyle(
            "sc", parent=base["Normal"], fontName="Malgun", fontSize=8.2,
            leading=11, alignment=TA_CENTER, textColor=colors.HexColor("#666"), spaceAfter=8,
        ),
        "step": ParagraphStyle(
            "sstep", parent=base["Normal"], fontName="MalgunBold", fontSize=10,
            leading=14, textColor=colors.white, alignment=TA_CENTER,
        ),
        "note": ParagraphStyle(
            "snote", parent=base["Normal"], fontName="Malgun", fontSize=8.8,
            leading=12.5, textColor=colors.HexColor("#333"),
            backColor=colors.HexColor("#fff8e7"), borderPadding=4, spaceAfter=6,
        ),
        "cell": ParagraphStyle(
            "scell", parent=base["Normal"], fontName="Malgun", fontSize=7.3, leading=10,
        ),
        "cell_h": ParagraphStyle(
            "scellh", parent=base["Normal"], fontName="MalgunBold", fontSize=7.5,
            leading=10, textColor=colors.white, alignment=TA_CENTER,
        ),
        "foot": ParagraphStyle(
            "sf", parent=base["Normal"], fontName="Malgun", fontSize=8,
            leading=10, alignment=TA_CENTER, textColor=colors.HexColor("#777"),
        ),
    }


def _p(text: str, style):
    return Paragraph(text.replace("\n", "<br/>"), style)


def _bullets(items, style):
    return ListFlowable(
        [ListItem(_p(t, style), leftIndent=10, bulletColor=colors.HexColor("#333")) for t in items],
        bulletType="bullet", start="•", leftIndent=14, bulletFontName="Malgun", bulletFontSize=9,
    )


def _table(rows, col_widths, header=True):
    styles = _styles()
    wrapped = []
    for ri, row in enumerate(rows):
        st = styles["cell_h"] if header and ri == 0 else styles["cell"]
        wrapped.append([_p(str(c), st) if not isinstance(c, (Image, Paragraph)) else c for c in row])
    t = Table(wrapped, colWidths=col_widths, repeatRows=1 if header else 0)
    cmds = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#ccc")),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [colors.white, colors.HexColor("#f7f7f7")]),
    ]
    if header:
        cmds += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50"))]
    t.setStyle(TableStyle(cmds))
    return t


def _img(path: Path, max_w=160 * mm, max_h=90 * mm):
    if not path or not Path(path).is_file():
        return None
    im = Image(str(path))
    scale = min(max_w / im.imageWidth, max_h / im.imageHeight, 1.0)
    im.drawWidth = im.imageWidth * scale
    im.drawHeight = im.imageHeight * scale
    return im


def _fig(path, caption, styles, max_w=160 * mm, max_h=80 * mm):
    im = _img(path, max_w, max_h)
    if im is None:
        return [_p(f"(이미지 없음: {Path(path).name})", styles["caption"])]
    return [KeepTogether([im, _p(caption, styles["caption"])])]


def _step_banner(n: int, title: str, styles):
    cell = _p(f"STEP {n}  ·  {title}", styles["step"])
    t = Table([[cell]], colWidths=[170 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1f4e79")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    return [Spacer(1, 2 * mm), t, Spacer(1, 3 * mm)]


def make_flow_fig() -> Path:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    path = FIG_DIR / "story_flow.png"
    fig, ax = plt.subplots(figsize=(10.4, 2.55))
    steps = [
        "① 25체크\n채점표",
        "② 54장\n×5명",
        "③ Qwen\n실패",
        "④ 사다리\n+R5 채점",
        "⑤ R5만\n학습 0.31",
        "⑥ Astra\n증류 0.52",
        "⑦ 칼리브\n·합격선",
    ]
    cols = ["#1f4e79", "#2a6f97", "#e76f51", "#e9c46a", "#8e5cc9", "#2a9d8f", "#264653"]
    ax.set_xlim(0, 7.4)
    ax.set_ylim(0, 1.35)
    for i, (lab, c) in enumerate(zip(steps, cols)):
        x = i + 0.15
        ax.add_patch(plt.Rectangle((x, 0.35), 0.9, 0.7, facecolor=c, alpha=0.95))
        ax.text(x + 0.45, 0.7, lab, ha="center", va="center", color="white", fontsize=8)
        if i < len(steps) - 1:
            ax.annotate("", xy=(x + 1.05, 0.7), xytext=(x + 0.9, 0.7),
                        arrowprops=dict(arrowstyle="->", color="#888", lw=1.3))
    ax.axis("off")
    ax.set_title("평가지표 만들기 — 기록에 맞춘 실제 순서", fontsize=12, pad=6)
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return path


def make_ladder_fig() -> Path:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    path = FIG_DIR / "story_ladder.png"
    fig, ax = plt.subplots(figsize=(8.8, 3.4))
    levels = [
        ("고득점대", "실제 립 · current 렌더", "#2a9d8f"),
        ("중간단", "약한~중간 결함", "#e9c46a"),
        ("저득점대", "강한 결함 · 스티커", "#e76f51"),
    ]
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 3.5)
    for i, (name, desc, c) in enumerate(reversed(levels)):
        y = i + 0.4
        ax.barh(y, 7.5, left=1.2, height=0.85, color=c, alpha=0.9)
        ax.text(1.4, y, name, va="center", color="white", fontsize=11, fontweight="bold")
        ax.text(9.0, y, desc, va="center", fontsize=9, color="#333")
    ax.text(0.4, 1.8, "모든\n점수대\n확보", ha="center", va="center", fontsize=9, color="#555")
    ax.set_title("품질 사다리 — 샘플링 설계 (정답 라벨 아님)", fontsize=11)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return path


def make_distill_fig() -> Path:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    path = FIG_DIR / "story_distill.png"
    fig, ax = plt.subplots(figsize=(9.6, 2.4))
    boxes = [
        (0.2, "사람 v2\n채점표", "#1f4e79"),
        (2.0, "Astra\n1,659장 채점", "#2a9d8f"),
        (4.0, "CSV\n선생님 점수", "#e9c46a"),
        (5.9, "DINOv2+\nRidge 학습", "#8e5cc9"),
        (7.9, "R5 98장으로\n홀드아웃 시험", "#264653"),
    ]
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 1.3)
    for i, (x, lab, c) in enumerate(boxes):
        ax.add_patch(plt.Rectangle((x, 0.35), 1.55, 0.7, facecolor=c, alpha=0.95))
        ax.text(x + 0.775, 0.7, lab, ha="center", va="center", color="white", fontsize=8.5)
        if i < len(boxes) - 1:
            ax.annotate("", xy=(boxes[i + 1][0] - 0.05, 0.7), xytext=(x + 1.55, 0.7),
                        arrowprops=dict(arrowstyle="->", color="#888", lw=1.3))
    ax.axis("off")
    ax.set_title("증류: Astra 라벨로 가르치고, 사람이 채점한 R5로만 검증", fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return path


def _pack_crops():
    key = DATA / "pack" / "key.csv"
    if not key.is_file():
        return {}
    with key.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out = {}
    for kind in ("sticker", "render", "real"):
        for r in rows:
            if r.get("repeat_of") or r.get("kind") != kind:
                continue
            p = PACK_IMG / f"{r['random_id']}_crop.png"
            if p.is_file():
                out[kind] = p
                break
    return out


def build():
    styles = _styles()
    flow = make_flow_fig()
    ladder = make_ladder_fig()
    distill = make_distill_fig()
    kinds = _pack_crops()
    story = []

    # Cover
    story.append(Spacer(1, 12 * mm))
    story.append(_p("립 AR 평가지표, 이렇게 만들었습니다", styles["title"]))
    story.append(_p(
        "①25체크 → ②54장×5명 → ③Qwen 실패 → ④사다리+R5 → ⑤R5만 학습 → ⑥Astra 증류 → ⑦칼리브",
        styles["sub"],
    ))
    story.append(_p(
        "한 줄 목표: 사람 채점표 눈금으로 AR 자연스러움을 재고, "
        "그 눈금을 자동 점수 모델로 옮겨 <b>올린 이미지</b>를 채점하는 것. "
        "(연구 로컬 · 얼굴 이미지 서버 전송 없음)",
        styles["body"],
    ))
    story.extend(_fig(flow, "그림. 실제 실험 순서(기록 기준).", styles, max_h=48 * mm))
    story.append(_p(
        "이전에 헷갈리기 쉬운 점: Astra 증류는 Qwen 직후가 아닙니다. "
        "먼저 품질 사다리로 데이터를 펼치고 R5가 채점한 뒤, R5만으로 학습해 보고, "
        "절대 점수가 약해서 Astra로 라벨을 늘려 증류했습니다.",
        styles["note"],
    ))
    story.append(PageBreak())

    # STEP 1
    story.extend(_step_banner(1, "채점표 — 5문항 × 5체크 = 25개", styles))
    story.append(_p(
        "자연스러움만 봅니다(트랙 A). 총점은 체크 통과 비율 0~5점. "
        "매트는 윤기 체크 일부(*)를 NA로 둡니다.",
        styles["body"],
    ))
    header = ["문항", "체크1", "체크2", "체크3", "체크4", "체크5"]
    story.append(_table([header] + RUBRIC_ROWS, [18 * mm, 30 * mm, 30 * mm, 32 * mm, 30 * mm, 30 * mm]))
    story.append(_p("* Q3-2~4: 매트에서 NA 가능", styles["caption"]))

    # STEP 2
    story.extend(_step_banner(2, "54장을 다섯 명이 채점", styles))
    story.append(_p(
        "고정 묶음: 렌더 38 + 스티커 6 + 실제 립 6 + 반복 4 = <b>본 채점 54장</b>. "
        "R1~R5가 같은 표로 채점. 이 점수가 이후의 ‘사람 눈금’ 기준선이 됩니다.",
        styles["body"],
    ))
    story.append(_table([
        ["구성", "역할"],
        ["스티커 6", "하한 — 붙여 넣은 실패"],
        ["AR 렌더 38", "개선 대상"],
        ["실제 립 6", "상한 — 진짜 바른 사진"],
        ["반복 4", "평가자 안 안정성"],
    ], [40 * mm, 130 * mm]))
    if any(kinds.get(k) for k in ("sticker", "render", "real")):
        cells, labels = [], []
        for k, lab in [("sticker", "스티커"), ("render", "렌더"), ("real", "실제")]:
            im = _img(kinds.get(k), 42 * mm, 42 * mm)
            cells.append(im if im else "")
            labels.append(_p(lab, styles["caption"]))
        g = Table([cells, labels], colWidths=[52 * mm] * 3)
        g.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
        story.append(Spacer(1, 2 * mm))
        story.append(g)
        story.append(_p("그림. 종류 예시(입술 crop).", styles["caption"]))
    story.append(_bullets([
        "스티커 &lt; 렌더 &lt; 실제 순서는 5명 모두 유지",
        "렌더끼리 원점수 일치도는 낮음(엄격함 차이). 순위는 상대적으로 안정",
        "렌더 평균 약 3.0/5. 약점: 밀착·결",
    ], styles["bullet"]))
    story.append(PageBreak())

    # STEP 3
    story.extend(_step_banner(3, "사람 채점 기준을 Qwen에 맡겨 자동 채점 시도 → 실패", styles))
    story.append(_p(
        "채점표·사람 예시를 프롬프트로 주고 로컬 VLM(Qwen2.5-VL-7B)에게 같은 25체크를 물었습니다. "
        "<b>Qwen을 추가로 학습(파인튜닝)한 단계는 아닙니다.</b> 채점관으로 써 본 것입니다.",
        styles["body"],
    ))
    story.append(_table([
        ["시도", "결과", "판정"],
        ["절대 채점 (표만 / 예시+표)", "거의 만점. 스티커도 고득점", "쓰지 않음"],
        ["A/B 비교", "첫 장 편향 ~88%. 같은 얼굴 비교 약함", "보조만 / 렌더 비교 불가"],
        ["체크별 예·아니오 예시", "‘예’ ~97%. 사람 기준과 거의 불일치", "쓰지 않음"],
    ], [42 * mm, 72 * mm, 56 * mm]))
    story.append(_p(
        "결론: 프롬프트로 기준을 알려 주는 방향은 종료. "
        "다음부터는 <b>사람 라벨로 작은 점수 모델을 직접 학습</b>하는 쪽으로 갑니다.",
        styles["body"],
    ))

    # STEP 4 — corrected
    story.extend(_step_banner(4, "데이터·점수대가 부족 → 품질 사다리로 이미지 생성, R5가 단독 채점", styles))
    story.append(_p(
        "54장×5명만으로는 절대 점수 모델을 가르치기엔 표본이 작고, "
        "렌더 점수도 중간대에 몰려 있었습니다. "
        "그래서 <b>모든 점수대가 나오게</b> 이미지를 의도적으로 펼칩니다.",
        styles["body"],
    ))
    story.extend(_fig(ladder, "그림. 고·중·저 점수대를 샘플링으로 채움.", styles, max_h=52 * mm))
    story.append(_p("무엇을 만들었나", styles["h2"]))
    story.append(_bullets([
        "먼저 확장 묶음(expand_pack): 새 얼굴 + 실험용 렌더 설정(결 약화·과한 광택 등)",
        "이어서 v3(build_v3): 같은 렌더 프레임에 이미지 공간 결함(degrade) — "
        "current + 결함 4종. TUNING만으로는 픽셀이 거의 안 바뀌어서 degrade로 전환",
        "체크리스트 묶음 + 같은 얼굴 A/B 묶음. 설계 단계 이름은 화면에 안 보임(블라인드)",
        "사다리/결함 이름은 <b>정답 라벨이 아님</b>. 라벨은 사람 채점",
    ], styles["bullet"]))
    story.append(_p("누가 채점했나", styles["h2"]))
    story.append(_p(
        "추가 묶음은 <b>R5 한 명</b>이 중심으로 채점했습니다. "
        "checklist 01–03 절대점수 <b>98장</b>, 같은 얼굴 A/B <b>476쌍</b>(decisive) 규모. "
        "반복 쌍 일치율 약 0.87. current vs 결함에서는 대체로 current가 이김 "
        "(강한 결함일수록 더 분명).",
        styles["body"],
    ))
    story.append(PageBreak())

    # STEP 5 — corrected: R5-only learn BEFORE Astra
    story.extend(_step_banner(5, "R5 사람 라벨만으로 먼저 학습해 봄 → 절대 점수는 약함", styles))
    story.append(_p(
        "VLM 프롬프트를 접은 뒤 첫 학습은 Astra가 아닙니다. "
        "<b>R5가 매긴 점수만</b>으로 고정 ResNet18 임베딩 + 작은 헤드를 학습했습니다 "
        "(learn.py, 2026-11-16).",
        styles["body"],
    ))
    story.append(_table([
        ["헤드", "결과", "해석"],
        ["절대 총점 (Ridge)", "CV Spearman ≈ 0.31, MAE ≈ 1.38", "평균 찍기와 비슷. 0~5 판관으로 부족"],
        ["A/B 선호 (Logistic)", "CV 정확도 ≈ 0.81 (다수 baseline 0.54)", "같은 얼굴 current vs 결함 순위는 배울 만함"],
    ], [42 * mm, 58 * mm, 70 * mm]))
    story.append(_p(
        "읽기: ‘어느 쪽이 더 나은지’는 신호가 있는데, "
        "‘몇 점인지’를 사람처럼 맞추려면 절대 점수 라벨이 더 필요합니다. "
        "그래서 다음 단계에서 라벨을 크게 늘립니다.",
        styles["body"],
    ))

    # STEP 6 — Astra distill
    story.extend(_step_banner(6, "사람 채점표를 Astra에 주고 대량 채점 → 그 CSV로 점수 모델 증류", styles))
    story.append(_p(
        "아이디어: 사람(대호 AR) 평가 기준 = <b>같은 v2 채점표 25체크</b>를 Astra(OpenAI)에게 주고, "
        "R5가 안 본 큰 풀(expansion_v3_openai_pool)을 채점하게 합니다. "
        "나온 CSV가 선생님 점수이고, 작은 점수 모델이 그걸 배웁니다. "
        "검증은 Astra가 못 본 <b>사람 R5 라벨</b>로만 합니다.",
        styles["body"],
    ))
    story.extend(_fig(distill, "그림. 증류와 홀드아웃 검증.", styles, max_h=42 * mm))
    story.append(_bullets([
        "Astra 채점: 약 1,659장 (얼굴 667명). 매트는 R5와 같이 윤기 일부 NA",
        "학습: Astra 라벨만 → 고정 인코더 + Ridge (Qwen 파인튜닝 아님)",
        "시험: R5 checklist 98장 · A/B 476쌍",
        "R5만 학습 0.31 → Astra 증류 후 Spearman ≈ 0.50~0.52 (DINOv2 bakeoff 최고쪽)",
        "Astra 평균 총점 ~1.85 vs R5 ~3.13 → Astra가 더 짬. 절대값보다 순위로 비교",
    ], styles["bullet"]))
    story.append(_table([
        ["모델", "R5 Spearman", "비고"],
        ["R5만 + ResNet18", "~0.31", "STEP 5"],
        ["Astra 증류 + ResNet18", "~0.50", "라벨 확대 효과"],
        ["Astra 증류 + DINOv2", "~0.52", "최종 raw 점수 쪽"],
        ["파인튜닝 헤드", "~0.30대", "악화 → 미채택"],
    ], [55 * mm, 35 * mm, 80 * mm]))
    story.append(PageBreak())

    # STEP 7
    story.extend(_step_banner(7, "순위는 나아졌지만 절대 눈금이 부족 → 칼리브 + 합격선", styles))
    story.append(_p(
        "증류 모델도 raw 점수는 2~3점대에 몰립니다. 실화장도 raw로는 낮게 나옵니다. "
        "순위 신호는 있으나 사람 눈금의 ‘몇 점’과는 어긋납니다. "
        "그래서 <b>칼리브레이션</b>을 붙입니다.",
        styles["body"],
    ))
    story.append(_bullets([
        "방법: R5 98장으로 raw → 사람 총점 단조 매핑(isotonic)",
        "순위 유지, 숫자만 사람 척도에 환산",
        "합격선은 모델이 정하지 않음. 사람이 고른 앵커 21장 평균 <b>4.68/5</b>",
        "판정: calibrated_score ≥ 4.68 (연구용). score_capture / compare_score가 이 점수를 씀",
    ], styles["bullet"]))
    thumbs = sorted(GALLERY.glob("*.png"))[:6] if GALLERY.is_dir() else []
    if thumbs:
        row = [_img(p, 26 * mm, 26 * mm) or "" for p in thumbs]
        while len(row) < 6:
            row.append("")
        g = Table([row[:3], row[3:]], colWidths=[52 * mm] * 3)
        g.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
        story.append(g)
        story.append(_p("그림. 합격 앵커 후보 일부 (사람 총점 ≥4.0).", styles["caption"]))

    # Closing
    story.append(_p("한 장으로 다시 말하면 (수정된 순서)", styles["h1"]))
    story.append(_p(
        "① 25체크 채점표 → ② 54장을 다섯 명이 채점 → ③ Qwen 자동 채점은 실패 "
        "(학습이 아니라 채점관 시도) → ④ 점수대를 채우려고 품질 사다리·결함 이미지를 만들고 "
        "<b>R5가 단독 채점</b> → ⑤ 그 R5 라벨만으로 먼저 학습해 보니 "
        "A/B는 ~0.81인데 절대 점수는 ~0.31 → ⑥ 같은 채점표를 Astra에게 주고 "
        "큰 풀을 채점한 CSV로 <b>점수 모델을 증류</b>(DINOv2+Ridge, 홀드아웃 ~0.52) → "
        "⑦ 절대 눈금이 눌려 있어 칼리브와 합격선 4.68을 붙였습니다.",
        styles["body"],
    ))
    story.append(_p(
        "지금 ‘올린 AR 이미지’를 넣는 파이프는: "
        "crop → DINOv2+Ridge(raw) → 칼리브 → 4.68과 비교입니다.",
        styles["body"],
    ))
    story.append(Spacer(1, 6 * mm))
    story.append(_p(
        "연구 브리핑 · 2026-11-19 · 재생성: "
        "ml/.venv/Scripts/python.exe research/lip_rubric/export_eval_story_pdf.py",
        styles["foot"],
    ))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(PDF_PATH),
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title="립 AR 평가지표 스토리 흐름",
        author="VISHUE research",
    )
    doc.build(story)
    return PDF_PATH


if __name__ == "__main__":
    print(build())
