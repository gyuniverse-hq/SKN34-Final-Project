"""Export a Korean PDF briefing on lip naturalness evaluation.

Covers timeline, rubric, pack design, quality ladder, concepts, figures, FAQ.

  ml/.venv/Scripts/python.exe research/lip_rubric/export_eval_report_pdf.py
"""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
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
FIG_DIR = OUT_DIR / "report_figs"
PDF_PATH = OUT_DIR / "lip_eval_metrics_briefing_20261119.pdf"
DIST = OUT_DIR / "dist_plots" / "dinov2_vits14"
GALLERY = OUT_DIR / "pass_gallery" / "images"
PACK_IMG = DATA / "pack" / "rating_pack" / "images"
PROBE = OUT_DIR / "restore_texture_probe"
FONT = r"C:\Windows\Fonts\malgun.ttf"
FONT_B = r"C:\Windows\Fonts\malgunbd.ttf"

plt.rcParams.update({
    "font.family": "Malgun Gothic",
    "axes.unicode_minus": False,
    "figure.facecolor": "white",
})


def _styles():
    pdfmetrics.registerFont(TTFont("Malgun", FONT))
    pdfmetrics.registerFont(TTFont("MalgunBold", FONT_B))
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title_k", parent=base["Title"], fontName="MalgunBold", fontSize=18,
            leading=26, alignment=TA_CENTER, spaceAfter=6,
        ),
        "sub": ParagraphStyle(
            "sub_k", parent=base["Normal"], fontName="Malgun", fontSize=10.5,
            leading=15, alignment=TA_CENTER, textColor=colors.HexColor("#444444"), spaceAfter=10,
        ),
        "h1": ParagraphStyle(
            "h1_k", parent=base["Heading1"], fontName="MalgunBold", fontSize=13.5,
            leading=19, spaceBefore=12, spaceAfter=7, textColor=colors.HexColor("#1a1a1a"),
        ),
        "h2": ParagraphStyle(
            "h2_k", parent=base["Heading2"], fontName="MalgunBold", fontSize=11.5,
            leading=16, spaceBefore=9, spaceAfter=5, textColor=colors.HexColor("#222222"),
        ),
        "body": ParagraphStyle(
            "body_k", parent=base["Normal"], fontName="Malgun", fontSize=9.2,
            leading=13.5, alignment=TA_JUSTIFY, spaceAfter=5,
        ),
        "bullet": ParagraphStyle(
            "bullet_k", parent=base["Normal"], fontName="Malgun", fontSize=9.2,
            leading=13, leftIndent=2,
        ),
        "caption": ParagraphStyle(
            "cap_k", parent=base["Normal"], fontName="Malgun", fontSize=8.2,
            leading=11, alignment=TA_CENTER, textColor=colors.HexColor("#555555"), spaceAfter=8,
        ),
        "qa_q": ParagraphStyle(
            "qa_q", parent=base["Normal"], fontName="MalgunBold", fontSize=9.5,
            leading=13.5, spaceBefore=7, spaceAfter=2, textColor=colors.HexColor("#1f4e79"),
        ),
        "qa_a": ParagraphStyle(
            "qa_a", parent=base["Normal"], fontName="Malgun", fontSize=9.2,
            leading=13.2, alignment=TA_JUSTIFY, spaceAfter=4, leftIndent=4,
        ),
        "toc": ParagraphStyle(
            "toc_k", parent=base["Normal"], fontName="Malgun", fontSize=10,
            leading=15, leftIndent=8, spaceAfter=3,
        ),
        "foot": ParagraphStyle(
            "foot_k", parent=base["Normal"], fontName="Malgun", fontSize=8,
            leading=10, alignment=TA_CENTER, textColor=colors.HexColor("#777777"),
        ),
        "cell": ParagraphStyle(
            "cell_k", parent=base["Normal"], fontName="Malgun", fontSize=8,
            leading=11, alignment=TA_LEFT,
        ),
        "cell_h": ParagraphStyle(
            "cell_h", parent=base["Normal"], fontName="MalgunBold", fontSize=8,
            leading=11, alignment=TA_CENTER, textColor=colors.white,
        ),
    }


def _p(text: str, style):
    return Paragraph(text.replace("\n", "<br/>"), style)


def _bullets(items: list[str], style):
    return ListFlowable(
        [ListItem(_p(t, style), leftIndent=10, bulletColor=colors.HexColor("#333333")) for t in items],
        bulletType="bullet",
        start="•",
        leftIndent=14,
        bulletFontName="Malgun",
        bulletFontSize=9,
    )


def _table(rows, col_widths, header=True):
    styles = _styles()
    wrapped = []
    for ri, row in enumerate(rows):
        style = styles["cell_h"] if header and ri == 0 else styles["cell"]
        wrapped.append([_p(str(c), style) if not isinstance(c, (Image, Paragraph)) else c for c in row])
    t = Table(wrapped, colWidths=col_widths, repeatRows=1 if header else 0)
    cmds = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cccccc")),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [colors.white, colors.HexColor("#f7f7f7")]),
    ]
    if header:
        cmds += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ]
    t.setStyle(TableStyle(cmds))
    return t


def _img(path: Path, max_w=160 * mm, max_h=95 * mm):
    if not path.is_file():
        return None
    im = Image(str(path))
    w, h = im.imageWidth, im.imageHeight
    scale = min(max_w / w, max_h / h, 1.0)
    im.drawWidth = w * scale
    im.drawHeight = h * scale
    return im


def _fig(path: Path, caption: str, styles, max_w=160 * mm, max_h=88 * mm):
    im = _img(path, max_w, max_h)
    if im is None:
        return [_p(f"(이미지 없음: {path.name})", styles["caption"])]
    return [KeepTogether([im, _p(caption, styles["caption"])])]


def _thumb_row(paths: list[Path | None], labels: list[str], styles, cell_w=48 * mm):
    n = max(len(paths), 1)
    cells, caps = [], []
    for p, lab in zip(paths, labels):
        im = _img(p, cell_w - 4 * mm, 42 * mm) if p else None
        cells.append(im if im else _p("(없음)", styles["caption"]))
        caps.append(_p(lab, styles["caption"]))
    g = Table([cells, caps], colWidths=[cell_w] * n)
    g.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return g


# --- figure generators -------------------------------------------------------

def make_diagrams() -> dict[str, Path]:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}

    # Timeline
    path = FIG_DIR / "timeline.png"
    fig, ax = plt.subplots(figsize=(10.2, 3.4))
    events = [
        (0, "v1→v2\n채점표·묶음", "#5b8def"),
        (1, "사람 5명\nICC·MDC", "#3aa675"),
        (2, "VLM 실패\n만점 편향", "#e8743b"),
        (3, "A/B·예시\n프롬프트", "#d4a72c"),
        (4, "품질 사다리\n·확장 묶음", "#8e5cc9"),
        (5, "R5 학습\nSpearman.31", "#5b8def"),
        (6, "Astra 증류\n→ DINOv2", "#3aa675"),
        (7, "합격선 4.68\n칼리브", "#2c3e50"),
    ]
    ax.set_xlim(-0.4, 7.4)
    ax.set_ylim(0, 1.2)
    ax.plot([0, 7], [0.55, 0.55], color="#cccccc", lw=3, zorder=1)
    for x, label, c in events:
        ax.scatter([x], [0.55], s=120, color=c, zorder=3, edgecolors="white", linewidths=1.5)
        ax.text(x, 0.92 if x % 2 == 0 else 0.18, label, ha="center", va="center",
                fontsize=8.5, color="#222",
                bbox=dict(boxstyle="round,pad=0.35", facecolor="#f8f8f8", edgecolor=c, lw=1.2))
    ax.axis("off")
    ax.set_title("립 자연스러움 평가지표 타임라인 (요약)", fontsize=12, pad=8)
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    out["timeline"] = path

    # Quality ladder
    path = FIG_DIR / "quality_ladder.png"
    fig, ax = plt.subplots(figsize=(9.6, 4.2))
    levels = [
        ("L5 current", "현재 렌더러\n(목표에 가장 가까움)", "#2a9d8f"),
        ("L4 less texture", "결·스파클 약화", "#57c4ad"),
        ("L3 flat shade", "명암 납작", "#e9c46a"),
        ("L2 hard edge", "테두리 딱딱", "#f4a261"),
        ("L1 near sticker", "거의 스티커", "#e76f51"),
    ]
    ax.set_xlim(0, 10)
    ax.set_ylim(-0.2, len(levels) + 0.6)
    for i, (name, desc, c) in enumerate(reversed(levels)):
        y = i + 0.5
        ax.barh(y, 8.2, left=1.0, height=0.72, color=c, alpha=0.9)
        ax.text(1.15, y, f"{name}", va="center", ha="left", fontsize=10, fontweight="bold", color="white")
        ax.text(9.4, y, desc, va="center", ha="left", fontsize=9, color="#333")
    ax.text(0.2, len(levels) / 2, "좋음\n↑\n나쁨", ha="center", va="center", fontsize=10, color="#555")
    ax.set_title("품질 사다리 (샘플링 설계 — 라벨이 아님)", fontsize=12)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    out["ladder"] = path

    # Defect map
    path = FIG_DIR / "defect_map.png"
    fig, ax = plt.subplots(figsize=(9.2, 3.6))
    defects = [
        ("texture_loss", "결 뭉개짐", "Q1 결"),
        ("flat_shade", "명암 납작", "Q2 명암"),
        ("gloss_blob", "광택 덩어리", "Q3 윤기"),
        ("edge_spill/gap", "테두리 번짐·틈", "Q4 경계"),
        ("sticker_blend", "스티커 블렌드", "Q5 밀착"),
        ("misalign 등", "어긋남·과선명", "Q4/Q5"),
    ]
    ax.set_xlim(0, 6.2)
    ax.set_ylim(0, 2.2)
    for i, (name, desc, q) in enumerate(defects):
        x = i % 3
        y = 1.1 if i < 3 else 0.15
        ax.add_patch(plt.Rectangle((x * 2.05 + 0.1, y), 1.9, 0.9,
                                   facecolor="#eef3f8", edgecolor="#2c3e50", lw=1.2, transform=ax.transData))
        ax.text(x * 2.05 + 1.05, y + 0.62, name, ha="center", fontsize=9, fontweight="bold")
        ax.text(x * 2.05 + 1.05, y + 0.38, desc, ha="center", fontsize=8.5, color="#444")
        ax.text(x * 2.05 + 1.05, y + 0.15, q, ha="center", fontsize=8, color="#1f4e79")
    ax.set_title("이미지 공간 결함(degrade.py) ↔ 채점표 문항 대응", fontsize=12)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    out["defects"] = path

    # Pipeline
    path = FIG_DIR / "pipeline.png"
    fig, ax = plt.subplots(figsize=(10.0, 2.6))
    boxes = [
        (0.3, "스크린샷\n/렌더"),
        (2.2, "MediaPipe\n정렬·립 crop"),
        (4.1, "DINOv2\n고정 임베딩"),
        (6.0, "Ridge\nraw 점수"),
        (7.9, "Isotonic\n칼리브"),
        (9.6, "≥4.68?\n합격 판정"),
    ]
    ax.set_xlim(0, 11.2)
    ax.set_ylim(0, 1.4)
    for i, (x, lab) in enumerate(boxes):
        ax.add_patch(plt.Rectangle((x, 0.35), 1.55, 0.7, facecolor="#2c3e50" if i == 5 else "#5b8def",
                                   edgecolor="white", lw=0, transform=ax.transData, alpha=0.95))
        ax.text(x + 0.775, 0.7, lab, ha="center", va="center", color="white", fontsize=8.5)
        if i < len(boxes) - 1:
            ax.annotate("", xy=(boxes[i + 1][0] - 0.05, 0.7), xytext=(x + 1.55, 0.7),
                        arrowprops=dict(arrowstyle="->", color="#888", lw=1.4))
    ax.set_title("현재 자동 채점 파이프라인 (연구 로컬)", fontsize=12)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    out["pipeline"] = path

    # Rubric overview
    path = FIG_DIR / "rubric_overview.png"
    fig, ax = plt.subplots(figsize=(9.4, 3.0))
    qs = [("Q1 결", "주름·피부감"), ("Q2 명암", "입체·조명"), ("Q3 윤기", "제형 반사"),
          ("Q4 경계", "테두리 자연"), ("Q5 밀착", "떠 보이지 않음")]
    ax.set_xlim(0, 5.5)
    ax.set_ylim(0, 1.5)
    for i, (t, s) in enumerate(qs):
        ax.add_patch(plt.Rectangle((i * 1.08 + 0.1, 0.35), 0.98, 0.85,
                                   facecolor="#1f4e79", alpha=0.9))
        ax.text(i * 1.08 + 0.59, 0.9, t, ha="center", color="white", fontsize=10, fontweight="bold")
        ax.text(i * 1.08 + 0.59, 0.55, f"체크 5개\n{s}", ha="center", color="#e8f1ff", fontsize=8)
    ax.text(2.75, 1.35, "총점 0~5 = 통과한 체크 비율 (매트는 윤기 일부 NA)", ha="center", fontsize=10)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    out["rubric"] = path

    return out


def _pack_kind_crops() -> dict[str, Path]:
    """Pick one crop each for sticker / render / real from the v2 pack."""
    key_path = DATA / "pack" / "key.csv"
    if not key_path.is_file():
        return {}
    with key_path.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out = {}
    for kind in ("sticker", "render", "real"):
        for r in rows:
            if r.get("repeat_of"):
                continue
            if r.get("kind") != kind:
                continue
            rid = r["random_id"]
            crop = PACK_IMG / f"{rid}_crop.png"
            if crop.is_file():
                out[kind] = crop
                break
    return out


def build():
    styles = _styles()
    figs = make_diagrams()
    kinds = _pack_kind_crops()
    story = []

    # ===== Cover =====
    story.append(Spacer(1, 18 * mm))
    story.append(_p("VISHUE 립 AR 자연스러움 평가지표", styles["title"]))
    story.append(_p("처음부터 끝까지 · 시행착오 · 개념 · 문제 제작 · 품질 사다리 · FAQ", styles["sub"]))
    story.append(_p("작성일: 2026-11-19 · 연구 전용 (앱 미연결) · 얼굴 데이터는 Git 제외 경로", styles["sub"]))
    story.append(Spacer(1, 4 * mm))
    story.append(_p(
        "한 줄 요약: AR 립이 ‘스티커’가 아니라 ‘직접 바른 것’처럼 보이는지를 "
        "사람 채점표(v2)로 정의하고, 평가 묶음·품질 사다리·자동 점수·합격선(4.68/5)까지 "
        "같은 눈금으로 잇는 과정을 정리한 브리핑이다.",
        styles["body"],
    ))
    story.append(Spacer(1, 4 * mm))
    story.append(_p("목차", styles["h1"]))
    for line in [
        "1. 무엇을 하려 했는가",
        "2. 타임라인과 시행착오",
        "3. 평가 문제는 어떻게 만들었는가",
        "4. 채점표(v2) 개념",
        "5. 품질 사다리와 결함 설계",
        "6. 사람 채점 결과와 신뢰도",
        "7. 자동화 시도: 실패와 전환",
        "8. 학습·증류·인코더 비교",
        "9. 합격선·칼리브레이션·파이프라인",
        "10. 자주 물어볼 만한 질문 (어떻게 했어요?)",
        "11. 한계와 다음 단계",
    ]:
        story.append(_p(line, styles["toc"]))
    story.append(PageBreak())

    # ===== 1 Goal =====
    story.append(_p("1. 무엇을 하려 했는가", styles["h1"]))
    story.append(_p(
        "제품 AR에서 입술 색을 올렸을 때, 사용자가 ‘직접 바른 것처럼’ 느끼는지를 "
        "재고 싶었다. 발색 정확도(실물 색 일치)와 부착(마스크 IoU)은 별도 축이고, "
        "여기서는 <b>트랙 A 현실감(자연스러움)</b>만 본다. 5점은 ‘실제로 바른 사진 같다’이다.",
        styles["body"],
    ))
    story.append(_bullets([
        "사람 채점표(v2): 결·명암·윤기·경계·밀착 각 5체크 → 총점 0~5",
        "평가 묶음: 스티커(하한) · AR 렌더 · 실제 립 사진(상한)을 한 눈에 비교",
        "품질 사다리·결함: 점수가 퍼지도록 의도적으로 품질을 흩뜨린 샘플링",
        "자동화: 사람 라벨 → (실패) VLM → (성공 방향) 인코더+회귀 → 칼리브",
        "합격선: 사람이 고른 앵커 21장 평균 <b>4.68/5</b> (자동 raw로 정하지 않음)",
        "절대 원칙: 얼굴 영상/이미지를 서버로 보내지 않음. 본 파이프는 로컬 연구용",
    ], styles["bullet"]))
    story.append(Spacer(1, 2 * mm))
    kind_paths = [kinds.get("sticker"), kinds.get("render"), kinds.get("real")]
    if any(kind_paths):
        story.append(_thumb_row(
            kind_paths,
            ["스티커(하한 예시)", "AR 렌더(중간)", "실제 립(상한 예시)"],
            styles,
        ))
        story.append(_p(
            "그림. v2 본 채점 묶음의 종류 예시(입술 crop). 같은 눈금에서 ‘나쁨~좋음’ 범위를 확보한다.",
            styles["caption"],
        ))

    # ===== 2 Timeline =====
    story.append(_p("2. 타임라인과 시행착오", styles["h1"]))
    story.extend(_fig(figs["timeline"], "그림. 평가지표 타임라인 요약.", styles, max_h=55 * mm))
    story.append(_table([
        ["시기", "시도", "결과·교훈"],
        ["~11-11", "v1 채점표·104장 규모", "장당 ~170초 → 전체 수시간. 축소 필요"],
        ["~11-12", "v2 25체크·54장·사람 5명", "극단(스티커/실제)은 일치, 렌더끼리 ICC 낮음"],
        ["11-12", "코드 지표 vs 사람", "상관 약함·CI가 0 포함 → 대체 불가"],
        ["11-12~13", "Qwen2.5-VL 절대 채점", "거의 만점·스티커도 고득점 → 폐기"],
        ["11-13", "A/B·체크별 예시 프롬프트", "위치 편향·구별 실패 → 프롬프트 방향 종료"],
        ["11-14", "품질 사다리·expand_pack", "TUNING만으론 픽셀 거의 안 변함 → 이미지 공간 degrade"],
        ["11-16", "R5 라벨 + ResNet18", "절대 Spearman ~0.31 (데이터 적음)"],
        ["11-19", "Astra 1,659장 증류", "R5 홀드아웃 0.50으로 상승"],
        ["11-19", "인코더 bakeoff", "DINOv2 0.515 소폭 최고. FT는 악화"],
        ["11-19", "합격선·칼리브·스크린샷", "앵커 평균 4.68. raw→사람 눈금 환산"],
    ], [22 * mm, 48 * mm, 100 * mm]))
    story.append(PageBreak())

    # ===== 3 How packs were made =====
    story.append(_p("3. 평가 문제는 어떻게 만들었는가", styles["h1"]))
    story.append(_p(
        "‘문제’는 시험지처럼 한 장씩 점수를 매기는 사진 묶음이다. "
        "정답을 미리 찍지 않고, 사람이 같은 채점표로 점수를 매기면 그것이 라벨이 된다.",
        styles["body"],
    ))
    story.append(_p("3.1 데이터와 규칙", styles["h2"]))
    story.append(_bullets([
        "출처: LaPa test만 (비상업 연구). 팀원 얼굴 금지",
        "사람이 face_id·맨입술/립스틱 라벨을 검토한 후보만 사용",
        "피부톤(ITA 분위)·입 모양·요우를 고르게 뽑도록 샘플링",
        "결과·이미지는 research/data/lip_rubric/ (Git 제외)",
    ], styles["bullet"]))
    story.append(_p("3.2 v2 본 채점 묶음 구성", styles["h2"]))
    story.append(_table([
        ["구성", "수량", "역할"],
        ["AR 렌더", "38장", "실제 개선 대상. 글로시/새틴/매트·셰이드 혼합"],
        ["스티커", "6장", "하한 앵커. ‘붙여 넣은’ 실패 사례"],
        ["실제 립 사진", "6장", "상한 앵커. 진짜로 바른 사진"],
        ["반복", "4장", "같은 사진 재등장 → 평가자 내 안정성"],
        ["연습", "3장", "다른 인물. 본 점수/DB에 넣지 않음(R0 시범)"],
        ["합계(본)", "54장", "고유 50 + 반복 4. 고정 벤치마크 SHA 기록"],
    ], [36 * mm, 22 * mm, 112 * mm]))
    story.append(_p(
        "생성 도구는 build_pack.py다. 렌더는 앱과 같은 faceTrackerHtml 경로로 만들고, "
        "평가자에게는 rating_pack(이미지+HTML UI)만 넘긴다. key.csv·원본 이름·매니페스트는 숨긴다.",
        styles["body"],
    ))
    story.append(_p("3.3 채점 UI와 블라인드", styles["h2"]))
    story.append(_bullets([
        "Chrome에서 index.html → 평가자 코드(R1~R5) 입력 → 폴더 선택",
        "Y/N/A(해당 없음) 체크 + 전체 인상 1~5",
        "평가자끼리 상의 금지. 끝나면 CSV만 전달하고 사진 삭제",
        "같은 CSV 중복 반영 없음. R0(시범)는 DB 거부",
    ], styles["bullet"]))
    story.append(_p("3.4 확장 묶음 (2026-11-14)", styles["h2"]))
    story.append(_p(
        "기존에 쓴 얼굴을 빼고 expand_pack.py로 새 얼굴을 넣어 묶음을 나눴다. "
        "같은 인물에 제형 여러 종 + 실험 설정(결 약화·과한 광택 등) + 스티커·실제 립을 섞는다. "
        "설정은 앱을 바꾸지 않으며, ‘이 설정=이 점수’라는 라벨이 아니다. "
        "점수 라벨은 사람이 채점한 뒤에만 생긴다.",
        styles["body"],
    ))

    # ===== 4 Rubric =====
    story.append(_p("4. 채점표(v2) 개념", styles["h1"]))
    story.extend(_fig(figs["rubric"], "그림. 문항 구조. 체크 통과 비율로 총점 0~5.", styles, max_h=48 * mm))
    story.append(_table([
        ["문항", "무엇을 보나", "대표 체크"],
        ["Q1 결", "주름·피부감이 남는가", "세로 주름, 페인트/플라스틱 아님"],
        ["Q2 명암", "조명·형태에 맞는 입체", "위·아래 명암, 납작하지 않음"],
        ["Q3 윤기", "제형에 맞는 반사", "위치·퍼짐; 매트는 일부 NA"],
        ["Q4 경계", "테두리가 자연스러운가", "가위질 아님, 입꼬리 부드러움"],
        ["Q5 밀착", "떠 보이지 않는가", "필름 아님, 확대해도 어색하지 않음"],
    ], [28 * mm, 48 * mm, 94 * mm]))
    story.append(_p(
        "전체 인상(1~5)도 따로 묻는다. 체크리스트 총점과 전체 인상의 Spearman은 "
        "사람 채점에서 약 0.91로 높았다. 그래도 운영 판단의 기본 눈금은 체크 총점이다.",
        styles["body"],
    ))
    story.append(PageBreak())

    # ===== 5 Quality ladder =====
    story.append(_p("5. 품질 사다리와 결함 설계", styles["h1"]))
    story.append(_p(
        "사람 점수가 전부 비슷하면 모델도, 렌더러 비교도 배우기 어렵다. "
        "그래서 ‘좋은 렌더 → 거의 스티커’까지 품질을 의도적으로 펼친다. "
        "중요: 사다리 단계 이름은 <b>샘플링 설계</b>이지 정답 라벨이 아니다. 라벨은 사람 채점이다.",
        styles["body"],
    ))
    story.extend(_fig(figs["ladder"], "그림. 품질 사다리 L5→L1 (quality_variants.py).", styles, max_h=68 * mm))
    story.append(_p("5.1 왜 TUNING만으로 부족했나", styles["h2"]))
    story.append(_p(
        "처음에 creaseGain·lipFeatherPx 같은 렌더러 TUNING으로 L5~L1을 만들려 했다. "
        "그런데 페이지가 카메라 블러·조명을 측정해 보정해, L1을 줘도 입술 픽셀이 거의 안 바뀌거나 "
        "D4_edge는 0픽셀 차이인 경우가 있었다. 그래서 렌더 후 <b>이미지 공간 degrade</b>로 "
        "입술 다각형 안에만 결함을 심는 방식으로 바꿨다.",
        styles["body"],
    ))
    story.extend(_fig(figs["defects"], "그림. degrade.py 결함 ↔ 채점표 문항.", styles, max_h=58 * mm))
    story.append(_p("5.2 결함 강도", styles["h2"]))
    story.append(_bullets([
        "강도 light / mild / strong (대략 0.25 / 0.5 / 1.0)",
        "sticker_blend: 평평한 스티커 쪽으로 혼합 (밀착·전체 실패)",
        "texture_loss: 주름 뭉개기 (결)",
        "flat_shade: 명암 폭 줄이기 (명암)",
        "gloss_blob: 흰 광택 점 (윤기)",
        "edge_spill / edge_gap / misalign: 테두리·위치 (경계)",
    ], styles["bullet"]))
    story.append(_p(
        "같은 얼굴의 current vs strong 결함을 점수 모델로 비교하면, "
        "‘결을 더 남기기’ 방향은 모델이 선호하는 신호가 관측됐다 "
        "(restore_texture 탐침). 미세 creaseGain만 올리는 TUNING은 거의 무의미했다.",
        styles["body"],
    ))
    # before/after probe thumbs if present
    ba = sorted(PROBE.glob("*__before_crop.png"))[:1]
    aa = sorted(PROBE.glob("*__after_crop.png"))[:1]
    if ba and aa:
        story.append(_thumb_row(
            [ba[0], aa[0]],
            ["before (결 약함)", "after (결 복원 탐침)"],
            styles,
            cell_w=70 * mm,
        ))
        story.append(_p("그림. 결 복원 탐침 예시 crop (연구용).", styles["caption"]))

    # ===== 6 Human results =====
    story.append(_p("6. 사람 채점 결과와 신뢰도", styles["h1"]))
    story.append(_p(
        "R1~R5 팀원 5명이 v2 54장을 채점했다(독립 외부 평가자 아님). "
        "스티커 &lt; 렌더 &lt; 실제 순서는 5명 모두 지켰다. "
        "렌더끼리의 원점수 일치도는 낮다 — 엄격함 차이가 크고, 순위는 상대적으로 안정적이다.",
        styles["body"],
    ))
    story.append(_table([
        ["지표", "값", "해석"],
        ["ICC(2,1) 고유 50장", "0.587", "극단 포함 시 중간"],
        ["ICC(2,1) 렌더 38장", "0.256", "렌더끼리 낮음"],
        ["ICC(2,k) 정규화 렌더", "0.794", "엄격함 보정 후 5명 평균은 안정"],
        ["렌더 평균 총점", "3.04 / 5", "CI 대략 2.69~3.37"],
        ["문항 약점", "밀착 0.44 · 결 0.50", "경계 0.61, 명암·윤기는 상대적 강점"],
        ["MDC95 (원점수)", "1.42점", "한 장에서 이보다 작은 변화는 노이즈"],
    ], [42 * mm, 32 * mm, 96 * mm]))
    story.append(_p(
        "제형별로는 새틴에서 평가자 의견이 가장 갈렸다(‘은은한 반짝임’ 기준이 사람마다 다름). "
        "반복 4쌍은 대체로 1점 미만 차이였다.",
        styles["body"],
    ))
    story.append(PageBreak())

    # ===== 7 Automation failures =====
    story.append(_p("7. 자동화 시도: 실패와 전환", styles["h1"]))
    story.append(_p("7.1 코드 지표", styles["h2"]))
    story.append(_p(
        "고주파·반사 면적·경계 폭 등(metrics.py)은 탐색용이다. "
        "사람 총점과 상관이 약하고 신뢰구간이 0을 포함해 대체 지표로 쓰지 않는다.",
        styles["body"],
    ))
    story.append(_p("7.2 VLM 절대 채점 (Qwen2.5-VL-7B)", styles["h2"]))
    story.append(_bullets([
        "채점표만 / 사례 3장(RAG) 모두 거의 만점",
        "스티커에도 4.8~4.9점 → 종류 순서 조건 실패 → ‘쓰지 않음’",
        "미묘한 주름·반사·떠 보임을 ‘자연스럽다’로 뭉개 버림",
    ], styles["bullet"]))
    story.append(_p("7.3 A/B 비교", styles["h2"]))
    story.append(_p(
        "절대 점수 대신 ‘더 자연스러운 쪽’을 물었다. 핵심 쌍 정확도 ~0.67로 "
        "규칙상 ‘보조만’이지만, 88%가 첫 번째 사진을 고르는 위치 편향이 컸다. "
        "같은 얼굴 비교(렌더 버전 비교에 필요한 설정)에서는 신호가 없었다.",
        styles["body"],
    ))
    story.append(_p("7.4 체크별 예시 프롬프트", styles["h2"]))
    story.append(_p(
        "체크마다 사람의 예/아니오 사진을 보여 줘도 ‘예’ 비율 ~97%로 거의 안 바뀌었다. "
        "기준을 몰라서가 아니라, 이 모델·해상도에서는 차이를 못 보는 쪽으로 해석하고 "
        "프롬프트 VLM 방향을 종료했다.",
        styles["body"],
    ))

    # ===== 8 Learning =====
    story.append(_p("8. 학습·증류·인코더 비교", styles["h1"]))
    story.append(_p("8.1 R5만으로 학습 (11-16)", styles["h2"]))
    story.append(_p(
        "고정 ResNet18 임베딩 + Ridge. checklist 98장 기준 Spearman ~0.31. "
        "A/B 쌍 헤드는 ~0.81로 상대 비교는 배우기 쉬웠다. "
        "절대 점수 판관으로 쓰기엔 데이터·신호가 부족했다.",
        styles["body"],
    ))
    story.append(_p("8.2 Astra 증류 (11-19)", styles["h2"]))
    story.append(_p(
        "Astra(OpenAI)가 v2 표로 expansion 풀 1,659장(얼굴 667명)을 채점 → "
        "그 라벨로만 학습 → Astra가 못 본 R5 사람 98장으로 시험. "
        "Spearman 0.50으로 상승. Astra 평균(~1.85)이 R5(~3.13)보다 짜서 "
        "절대 눈금이 아니라 순위로 비교한다.",
        styles["body"],
    ))
    story.append(_p("8.3 인코더 bakeoff", styles["h2"]))
    story.append(_table([
        ["모델", "R5 Spearman", "R5 MAE", "비고"],
        ["ResNet18 고정 + Ridge", "0.501", "1.60", "기준선"],
        ["EfficientNet-B0 / B3", "0.37~0.40", "— / 1.54", "순위↓"],
        ["ConvNeXt-Tiny", "0.497", "1.51", "R18과 유사"],
        ["DINOv2-ViT-S/14 + Ridge", "0.515", "1.49", "bakeoff 최고"],
        ["B0 / DINOv2 파인튜닝", "0.30대", "악화", "메인 미채택"],
        ["DINOv2 + isotonic 칼리브", "순위 유지", "CV MAE~1.03", "사람 눈금 환산"],
    ], [52 * mm, 32 * mm, 28 * mm, 58 * mm]))
    story.append(_p(
        "종류 평균 순서 sticker &lt; render &lt; real 은 대체로 유지. "
        "문제는 4~5점대 절대 숫자가 눌리는 ‘분포 압축’이었다.",
        styles["body"],
    ))
    story.append(_p("8.4 분포로 본 문제 (DINOv2 raw)", styles["h2"]))
    for name, cap in [
        ("scatter_human_vs_pred.png", "사람 총점 vs 예측. 고득점이 아래로 눌림."),
        ("hist_scores.png", "사람(넓음) vs 모델(좁고 낮음)."),
        ("bar_by_kind.png", "종류 순서는 유지, 높이는 전부 낮음."),
    ]:
        story.extend(_fig(DIST / name, f"그림. {cap}", styles, max_h=72 * mm))
    story.append(PageBreak())

    # ===== 9 Pass line & pipeline =====
    story.append(_p("9. 합격선·칼리브레이션·파이프라인", styles["h1"]))
    story.append(_p("9.1 합격선 4.68", styles["h2"]))
    story.append(_p(
        "R5 총점 ≥4.0 후보 갤러리에서 사용자가 ‘합격’으로 고른 21장의 평균이 "
        "<b>4.68</b>이다(중앙값 4.8, 범위 4.0~5.0). "
        "자동 raw 점수로 합격선을 정하지 않았다. 사람 채점표 눈금이다.",
        styles["body"],
    ))
    thumbs = sorted(GALLERY.glob("*.png"))[:6]
    if thumbs:
        cells, row = [], []
        for i, p in enumerate(thumbs):
            im = _img(p, 28 * mm, 28 * mm)
            if im:
                row.append(im)
            if len(row) == 3 or i == len(thumbs) - 1:
                while len(row) < 3:
                    row.append("")
                cells.append(row)
                row = []
        if cells:
            g = Table(cells, colWidths=[55 * mm] * 3)
            g.setStyle(TableStyle([
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]))
            story.append(g)
            story.append(_p("그림. 합격 후보 갤러리 일부 (R5 ≥4.0 crop).", styles["caption"]))

    story.append(_p("9.2 칼리브레이션이란", styles["h2"]))
    story.append(_p(
        "모델 온도계와 사람 온도계의 <b>환산표</b>다. R5 98장에서 "
        "‘DINOv2 raw → 사람 총점’ 단조 매핑(isotonic)을 학습한다. "
        "순위는 유지하고 숫자만 사람 척도에 붙인 뒤, 합격선 4.68과 같은 눈금으로 비교한다.",
        styles["body"],
    ))
    story.append(_p("9.3 현재 파이프라인", styles["h2"]))
    story.extend(_fig(figs["pipeline"], "그림. 스크린샷 → 보정 점수 → 합격 판정.", styles, max_h=42 * mm))
    story.append(_bullets([
        "학습: Astra 1,659장 → 고정 DINOv2 → Ridge(α=1000)",
        "보정: R5 isotonic → calibration_dinov2_vits14.json",
        "도구: learn_astra.py, calibrate_score.py, score_capture.py, compare_score.py",
        "합격: calibrated_score ≥ 4.68",
    ], styles["bullet"]))
    story.append(_table([
        ["유형", "보정 전(대략)", "보정 후", "합격(≥4.68)"],
        ["실화장 사진", "≈3.1", "≈4.88", "통과"],
        ["스티커 립", "≈1.0~1.7", "≈0.1~2.9", "탈락"],
        ["Expo AR 샘플", "≈2.2~2.8", "≈3.5~4.1", "탈락(해당 샘플)"],
        ["맨입술", "≈2.65", "≈3.97", "탈락·AR과 간격 좁음"],
    ], [40 * mm, 38 * mm, 35 * mm, 57 * mm]))
    story.append(_p(
        "점수 자동화 ≠ AR이 이미 합격이라는 뜻이 아니다. "
        "맨입술 vs 애매한 AR 구분은 여전히 과제다.",
        styles["body"],
    ))
    story.append(PageBreak())

    # ===== 10 Concepts glossary =====
    story.append(_p("핵심 개념 한눈에", styles["h1"]))
    story.append(_table([
        ["개념", "쉬운 설명"],
        ["채점표(rubric)", "예/아니오 체크 모음. 통과 비율이 0~5 총점"],
        ["Spearman", "숫자 일치가 아니라 ‘누가 더 낫다’ 순위 일치"],
        ["MAE / 편향", "평균 몇 점 빗나가는지 / 전반적으로 낮은지 높은지"],
        ["분포 압축", "모델이 점수를 1.5~3 근처에 몰아 넣는 현상"],
        ["고정 인코더+Ridge", "사전학습 ‘눈’은 고정, 얇은 선형식만 학습"],
        ["Astra 증류", "큰 채점자가 매긴 라벨로 작은 모델을 가르침"],
        ["칼리브레이션", "모델 점수를 사람 눈금으로 환산"],
        ["ICC", "평가자끼리 얼마나 같은 점수를 주는지"],
        ["MDC95", "노이즈와 구분되는 최소 의미 있는 점수 차이"],
        ["품질 사다리", "좋음→나쁨 샘플을 펼치는 설계 (라벨 아님)"],
        ["블라인드 묶음", "정답·원본명을 숨긴 채점용 사진 세트"],
    ], [40 * mm, 130 * mm]))

    # ===== 11 FAQ =====
    story.append(_p("10. 자주 물어볼 만한 질문 — 어떻게 했어요?", styles["h1"]))

    faqs = [
        ("Q. 점수는 누가 정했나요?",
         "A. 1차는 사람(팀원 R1~R5)이 v2 채점표로 매긴다. 자동 모델은 그 사람 눈금을 "
         "배우거나(Astra 증류 후 R5로 검증) 환산(칼리브)할 뿐이다. 합격선도 사람이 고른 앵커 평균이다."),
        ("Q. 평가용 사진은 어떻게 골랐나요?",
         "A. LaPa test에서 사람 검토된 얼굴만 쓰고, 맨입술/립스틱·ITA·입 모양을 고르게 샘플링했다. "
         "스티커·실제·렌더를 한 묶음에 넣어 하한~상한 범위를 확보했다."),
        ("Q. 왜 스티커랑 실제 사진을 넣었나요?",
         "A. 점수가 전부 3점대에 몰리면 ‘좋다/나쁘다’를 배울 수 없다. "
         "스티커는 실패 하한, 실제 립은 성공 상한 앵커다."),
        ("Q. 품질 사다리는 정답 라벨인가요?",
         "A. 아니다. L5~L1·결함 이름은 샘플을 흩뜨리기 위한 설계다. "
         "정답은 언제나 사람 채점(또는 그 눈금을 배운 모델)이다."),
        ("Q. 왜 VLM을 안 쓰나요?",
         "A. 써 봤다. 절대 채점·A/B·예시 프롬프트 모두 이 과제에서 실패하거나 "
         "렌더 버전 비교에 쓸 수 없었다. 프롬프트로 억지하지 않고 학습으로 전환했다."),
        ("Q. Spearman 0.5면 쓸 만한가요?",
         "A. ‘누가 더 낫다’ 순서는 중간 정도로 맞지만, 절대 숫자는 눌린다. "
         "그래서 칼리브로 사람 눈금에 붙이고, 합격선은 사람 앵커로 둔다. CI도 넓다."),
        ("Q. 왜 더 큰 모델을 파인튜닝하지 않나요?",
         "A. B0/DINOv2 헤드·부분 FT를 해 봤고 절대 Spearman이 오히려 떨어졌다. "
         "지금은 고정 DINOv2+Ridge가 bakeoff 최고다."),
        ("Q. 앱에 바로 넣나요? 서버로 사진 보내나요?",
         "A. 연구 로컬 파이프다. 얼굴 이미지를 서버로 보내지 않는 원칙을 지킨다. "
         "앱 배포·운영 대시보드 연결은 별도 결정 사항이다."),
        ("Q. 렌더러를 고치면 점수로 어떻게 확인하나요?",
         "A. 같은 얼굴 before/after crop을 compare_score로 재고, "
         "고정 벤치마크(bench.py)로 묶음 전후를 비교한다. 한두 점 차이는 MDC를 넘는지 본다."),
        ("Q. 발색(색이 제품과 같음)도 이 점수로 보나요?",
         "A. 아니다. 이 지표는 자연스러움(트랙 A)이다. 색 재현(트랙 B)은 별도 ΔE 등이다."),
        ("Q. 가이드 예시가 편향을 주지 않나요?",
         "A. 줄 수 있다. 가이드는 R0 pool 사진 기반이며 본 채점에도 등장한다. "
         "출처와 영향을 보고에 명시했다. test 분할은 가이드에서 뺐다."),
        ("Q. 다음에 뭐가 필요한가요?",
         "A. 폰 AR·실화장 사람 라벨을 더 모아 칼리브/헤드를 도메인에 맞추고, "
         "결 살리기 등 눈에 보이는 AR 개선을 보정 점수로 전후 비교한 뒤 Expo Go로 확인한다."),
    ]
    for q, a in faqs:
        story.append(_p(q, styles["qa_q"]))
        story.append(_p(a, styles["qa_a"]))

    story.append(PageBreak())

    # ===== 11 Limits =====
    story.append(_p("11. 한계와 다음 단계", styles["h1"]))
    story.append(_bullets([
        "평가자 5명은 팀원(외부 독립 평가자 없음)",
        "실제 사진과 렌더는 짝이 아님 — 발색 재현도 미평가",
        "표본이 작아 CI가 넓음. VLM·학습 결과는 예비/연구용",
        "얼굴 ID 사람 검토의 오류 가능성",
        "칼리브 후에도 맨입술 vs 애매한 AR 구분 과제",
        "Expo Go 실기기에서 ‘해결’로 보고하려면 별도 확인 필요",
    ], styles["bullet"]))
    story.append(_p("다음에 하면 좋은 것", styles["h2"]))
    story.append(_bullets([
        "폰 AR·실화장 라벨 추가 → 칼리브/헤드 재적합",
        "결 복원 등 AR 개선 → compare_score 전후 → Expo 확인",
        "음수 사례·페어로 맨입술/AR 혼동 재보정",
        "관리자 숫자는 집계만 (이미지 업로드 서버 금지 유지)",
    ], styles["bullet"]))

    story.append(Spacer(1, 8 * mm))
    story.append(_p(
        "본 PDF는 research/lip_rubric 실험 기록과 2026-11-19까지의 결과를 요약한 연구 브리핑이다. "
        "운영 앱 배포 상태를 의미하지 않는다. 재생성: "
        "ml/.venv/Scripts/python.exe research/lip_rubric/export_eval_report_pdf.py",
        styles["foot"],
    ))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(PDF_PATH),
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=13 * mm,
        bottomMargin=13 * mm,
        title="VISHUE 립 AR 평가지표 브리핑",
        author="VISHUE research",
    )
    doc.build(story)
    return PDF_PATH


if __name__ == "__main__":
    path = build()
    print(path)
