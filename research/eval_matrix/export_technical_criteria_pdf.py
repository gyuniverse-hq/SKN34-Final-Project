"""Export technical eval criteria PDF v1.2 (v2.1 narrative + score ladders).

  ml/.venv/Scripts/python.exe research/eval_matrix/export_technical_criteria_pdf.py
"""
from __future__ import annotations

import shutil
from pathlib import Path

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
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[2]
LADDER = ROOT / "research" / "data" / "eval_matrix" / "tech_score_ladder" / "images"
OUT = ROOT / "reports" / "VISHUE_AR_technical_metrics_v1.2_20261120.pdf"
OUT2 = ROOT / "research" / "data" / "lip_rubric" / "learn_astra" / "VISHUE_AR_technical_metrics_v1.2_20261120.pdf"
FONT = r"C:\Windows\Fonts\malgun.ttf"
FONT_B = r"C:\Windows\Fonts\malgunbd.ttf"

DE_STRIP = [
    ("de_0p80", "0.8\n알아챔", False),
    ("de_1p80", "1.8\n합격·허용", True),
    ("de_2p90", "2.9\n피부 floor", False),
    ("de_3p65", "3.65\n우리 AR 중앙", False),
    ("de_7p20", "7.2\n맨입술 중앙", False),
]
SSIM_STRIP = [
    ("ssim_0p98", "0.98", False),
    ("ssim_0p95", "0.95\n눈 목표", True),
    ("ssim_0p90", "0.90", False),
    ("ssim_0p80", "0.80", False),
    ("ssim_0p66", "0.66\n우리 AR 중앙", False),
]
MAE_STRIP = [
    ("mae_0p01", "0.01", False),
    ("mae_0p04", "0.04\n눈 목표", True),
    ("mae_0p08", "0.08", False),
    ("mae_0p12", "0.12", False),
    ("mae_0p20", "0.20", False),
]
MIOU_STRIP = [
    ("miou_0p950", "0.95", False),
    ("miou_0p850", "0.85\n눈 목표", True),
    ("miou_0p797", "0.797\nSegFace", False),
    ("miou_0p700", "0.70", False),
    ("miou_0p500", "0.50", False),
]


def _styles():
    pdfmetrics.registerFont(TTFont("Malgun", FONT))
    pdfmetrics.registerFont(TTFont("MalgunBold", FONT_B))
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "t", parent=base["Title"], fontName="MalgunBold", fontSize=13.5,
            leading=18, alignment=TA_CENTER, spaceAfter=3,
        ),
        "sub": ParagraphStyle(
            "s", parent=base["Normal"], fontName="Malgun", fontSize=8.0,
            leading=11, alignment=TA_CENTER, textColor=colors.HexColor("#555"), spaceAfter=6,
        ),
        "h": ParagraphStyle(
            "h", parent=base["Normal"], fontName="MalgunBold", fontSize=10.2,
            leading=13.5, spaceBefore=7, spaceAfter=3,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Normal"], fontName="MalgunBold", fontSize=9.0,
            leading=12, spaceBefore=5, spaceAfter=2, textColor=colors.HexColor("#1b7a6e"),
        ),
        "body": ParagraphStyle(
            "b", parent=base["Normal"], fontName="Malgun", fontSize=8.1,
            leading=11.2, alignment=TA_JUSTIFY, spaceAfter=3,
        ),
        "cap": ParagraphStyle(
            "cap", parent=base["Normal"], fontName="Malgun", fontSize=6.5,
            leading=8.2, alignment=TA_CENTER,
        ),
        "cap_pass": ParagraphStyle(
            "capp", parent=base["Normal"], fontName="MalgunBold", fontSize=6.5,
            leading=8.2, alignment=TA_CENTER, textColor=colors.HexColor("#1b7a6e"),
        ),
        "cell": ParagraphStyle(
            "c", parent=base["Normal"], fontName="Malgun", fontSize=6.7, leading=8.8, alignment=TA_LEFT,
        ),
        "cell_h": ParagraphStyle(
            "ch", parent=base["Normal"], fontName="MalgunBold", fontSize=6.7,
            leading=8.8, textColor=colors.white, alignment=TA_CENTER,
        ),
        "foot": ParagraphStyle(
            "f", parent=base["Normal"], fontName="Malgun", fontSize=7.0,
            leading=9.2, textColor=colors.HexColor("#555"),
        ),
        "callout": ParagraphStyle(
            "co", parent=base["Normal"], fontName="Malgun", fontSize=8.0,
            leading=11, alignment=TA_LEFT, backColor=colors.HexColor("#eef7f5"),
            borderPadding=4, spaceAfter=4,
        ),
    }


def _p(text, style):
    return Paragraph(str(text).replace("\n", "<br/>"), style)


def _table(rows, widths):
    styles = _styles()
    data = []
    for i, row in enumerate(rows):
        st = styles["cell_h"] if i == 0 else styles["cell"]
        data.append([_p(c, st) for c in row])
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#ccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f7f7")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.0),
        ("TOPPADDING", (0, 0), (-1, -1), 2.0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.0),
    ]))
    return t


def _swatch_row(items: list[tuple[str, str, bool]], side_mm: float = 28.0):
    styles = _styles()
    imgs, caps = [], []
    for stem, caption, is_pass in items:
        path = LADDER / f"{stem}.png"
        if not path.is_file():
            continue
        imgs.append(Image(str(path), width=side_mm * mm, height=side_mm * mm))
        caps.append(_p(caption, styles["cap_pass"] if is_pass else styles["cap"]))
    if not imgs:
        return [_p(f"(사다리 이미지 없음: {LADDER})", styles["foot"])]
    n = len(imgs)
    t = Table([imgs, caps], colWidths=[side_mm * mm] * n)
    cmds = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#111111")),
        ("LEFTPADDING", (0, 0), (-1, -1), 1),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]
    for i, (_, _, is_pass) in enumerate(items):
        if is_pass and i < n:
            cmds.append(("BOX", (i, 0), (i, 0), 1.5, colors.HexColor("#2a9d8f")))
    t.setStyle(TableStyle(cmds))
    return [t]


def _metric_figure(title: str, blurb: str, strip: list[tuple[str, str, bool]]):
    styles = _styles()
    return KeepTogether([
        _p(title, styles["h2"]),
        _p(blurb, styles["body"]),
        *_swatch_row(strip),
        Spacer(1, 1.5 * mm),
    ])


def build():
    styles = _styles()
    story = []

    # ── P1 cover + summary ──
    story.append(_p("VISHUE AR 테크니컬 평가지표 v1.2", styles["title"]))
    story.append(_p(
        "숫자로 재는 트랙 B · v2.1 근거 원칙 + 점수대 사다리(눈 앵커) · 2026-11-20",
        styles["sub"],
    ))
    story.append(_p(
        "이 문서는 <b>입술 ROI의 기술 지표</b>만 다룹니다. "
        "“실제로 바른 것처럼 보이냐”는 사람·Astra 설문(트랙 A)은 "
        "Ext-B / 멘토 Likert 문서로 갑니다.",
        styles["body"],
    ))
    story.append(_p(
        "<b>원칙 한 줄</b> — 합격선은 ① 사람 눈 공개 역치, ② 같은 데이터 공개 SOTA, "
        "③ “우연이 아니다” 통계 검정 중 하나에서만 가져옵니다. "
        "근거를 댈 수 없으면 합격·불합격을 매기지 않고 <b>기록만</b> 합니다. "
        "초록 테두리 숫자는 팀이 사다리에서 고른 <b>눈 앵커(목표)</b>이며, "
        "공개 근거 선이 있으면 그쪽이 공식입니다.",
        styles["body"],
    ))

    story.append(_p("평가지표 요약표 (공식 선 + 예시 스냅샷)", styles["h"]))
    story.append(_table([
        ["지표", "무엇을 재나", "합격선(근거)", "예시 현재값", "판정"],
        ["① 색\nΔE2000", "AR 입술색 vs\n실제 바른 색",
         "중앙 ≤1.8 (Paravina)\n+ 맨입술보다 가까움 ≥15/20",
         "중앙 ≈3.65\n피부 floor ≈2.90\n가깝게 17/20",
         "절대: 판정 불가\n상대: 합격"],
        ["② 위치\nmIoU/F1", "정답 마스크와\n겹침",
         "F1 ≥0.887\n(=IoU ≥0.797, SegFace)\n눈 목표 IoU ≥0.85",
         "F1 ≈0.840\n(IoU ≈0.724)",
         "불합격\n(공식 선 기준)"],
        ["③ 질감\n묶음", "명암폭·하이라이트\n·SSIM이 맨입술보다\n실바에 가까운가",
         "세 수치 각 ≥15/20\n(부호검정)",
         "9 · 9 · 4 /20\n(예시 스냅샷)",
         "불합격"],
        ["④ SSIM\n절대값", "립 ROI 구조·명암",
         "절대선 없음 → 기록만\n(+눈 목표 ≥0.95)\n상대는 ③에 포함",
         "AR 중앙 ≈0.66",
         "기록만\n+상대는 ③"],
        ["⑤ MAE\n(/LPIPS)", "픽셀·지각 거리",
         "절대선 없음 → 기록만\nMAE 눈 목표 ≤0.04\n상대 ≥15/20",
         "(재측정 필요)",
         "기록만\n+상대 검정"],
    ], [22 * mm, 30 * mm, 42 * mm, 36 * mm, 28 * mm]))
    story.append(_p(
        "예시 값은 eval_matrix / v2.1 측정 스냅샷입니다. 렌더를 고친 뒤에는 "
        "같은 파이프라인으로 다시 재서 표를 갱신합니다.",
        styles["foot"],
    ))

    story.append(_p("판정 단어", styles["h"]))
    story.append(_table([
        ["단어", "뜻"],
        ["합격", "제대로 잰 값이 근거 있는 합격선을 넘음"],
        ["불합격", "제대로 잰 값이 합격선에 못 미침"],
        ["판정 불가", "잰 값은 있지만 데이터(조명·표본)가 판정할 만큼 정확하지 않음"],
        ["기록만", "근거 있는 절대 합격선이 세상에 없음 → 변화만 추적"],
        ["미측정", "아직 안 잼"],
    ], [28 * mm, 142 * mm]))

    story.append(_p(
        "<b>한 줄 결론(예시 스냅샷)</b> — 위치·질감은 근거 있는 기준으로도 아직 불합격. "
        "색 절대선은 사진 바닥값(2.9)이 합격선(1.8)보다 커서 판정 불가이고, "
        "맨입술보다 가깝다는 상대 검정만 통과. "
        "자연스러움 설문은 이 PDF 범위 밖(트랙 A).",
        styles["body"],
    ))

    # ── P2: why / relation / coin test ──
    story.append(PageBreak())
    story.append(_p("v2.1과 이 문서의 관계 · 왜 이렇게 나눴나", styles["h"]))
    story.append(_table([
        ["v2.1 매트릭스", "이 테크니컬 PDF", "비고"],
        ["① 색상일치", "① ΔE + 피부 floor", "동일 원칙·동일 1.8"],
        ["② 위치", "② mIoU/F1 + 사다리", "공식 0.797 + 눈 목표 0.85"],
        ["③ 질감·광택", "③ 묶음 + SSIM/MAE 사다리", "절대선 없음→상대 15/20"],
        ["④ 자연스러움", "제외 (트랙 A)", "Ext-B / 멘토 1–5"],
    ], [36 * mm, 52 * mm, 82 * mm]))
    story.append(_p(
        "v2.1이 “근거 있는 합격선만으로 판정표”라면, v1.2는 같은 원칙을 유지하면서 "
        "<b>숫자가 눈으로 어떻게 보이는지(사다리)</b>와 "
        "<b>팀 목표 앵커</b>를 덧붙인 테크니컬 설명서입니다. "
        "앵커로 공식 선을 바꾸지 않습니다.",
        styles["body"],
    ))

    story.append(_p("“15/20”이 팀 감이 아닌 이유 (부호 검정)", styles["h"]))
    story.append(_p(
        "AR이 아무 효과가 없으면, 20쌍 중 이기는 횟수는 동전 20번과 같습니다. "
        "앞면이 15번 이상 나올 확률은 약 <b>2.1%</b>입니다. "
        "과학에서 흔히 쓰는 “우연 5% 미만” 기준을 넘기려면 최소 15승이 필요합니다. "
        "14승이면 약 5.8%라 부족합니다. "
        "그래서 15는 사람이 고른 숫자가 아니라 <b>계산에서 나온 값</b>입니다.",
        styles["body"],
    ))

    story.append(_p("공식 선 vs 팀 눈 앵커", styles["h"]))
    story.append(_table([
        ["지표", "눈 앵커(목표)", "공식 합격선", "관계"],
        ["ΔE", "≤ 1.8", "≤ 1.8 (Paravina)", "동일 → 공식으로 사용"],
        ["mIoU", "≥ 0.85", "≥ 0.797 (SegFace F1 0.887)", "눈이 더 엄격(목표)"],
        ["SSIM", "≥ 0.95", "15/20 상대만 (절대선 없음)", "절대는 기록만+목표"],
        ["MAE", "≤ 0.04", "15/20 상대만", "절대는 기록만+목표"],
        ["LPIPS", "(사다리 없음)", "15/20 상대만", "기록+상대"],
    ], [24 * mm, 32 * mm, 58 * mm, 56 * mm]))

    # ── P3 ladders ──
    story.append(PageBreak())
    story.append(_p("점수대 사다리 — 숫자가 눈에 어떻게 보이나", styles["h"]))
    story.append(_p(
        "왼쪽 = 기준, 오른쪽 = 그 점수대 예시. 초록 테두리 = 2026-11-20 팀이 고른 눈 앵커/합격 칸. "
        "ΔE는 단색 Lab, SSIM·MAE는 실립 crop 열화, mIoU는 합성 마스크(초록=정답·빨강=예측·노랑=겹침).",
        styles["body"],
    ))
    story.append(_metric_figure(
        "① ΔE CIE2000 — 낮을수록 좋음 · 공식·눈 합격 ≤1.8",
        "0.8≈알아챔, 1.8≈허용. 2.9는 지금 사진의 피부 바닥값, 3.65는 AR 중앙 예시.",
        DE_STRIP,
    ))
    story.append(_metric_figure(
        "④ SSIM — 높을수록 좋음 · 절대선 없음 · 눈 목표 ≥0.95",
        "지금 AR 중앙≈0.66이라 목표와 거리가 큼. 목표는 ‘지금 통과선’이 아니라 ‘이 정도면 눈으로 합격’.",
        SSIM_STRIP,
    ))

    story.append(PageBreak())
    story.append(_metric_figure(
        "⑤ MAE — 낮을수록 좋음 · 절대선 없음 · 눈 목표 ≤0.04 (RGB 0~1)",
        "픽셀이 평균적으로 얼마나 틀렸는지. 공식 판정은 상대 15/20.",
        MAE_STRIP,
    ))
    story.append(_metric_figure(
        "② mIoU — 높을수록 좋음 · 공식 ≥0.797 · 눈 목표 ≥0.85",
        "SegFace 공개 SOTA가 공식. 0.85는 내부 목표(대체 아님).",
        MIOU_STRIP,
    ))

    # ── P4 metric deep dives ──
    story.append(PageBreak())
    story.append(_p("① 색(ΔE) — 기준은 있지만, 사진이 흔들리면 판정 불가", styles["h"]))
    story.append(_p(
        "입술 안쪽 평균 Lab으로 AR vs 실바의 CIEDE2000을 잽니다. "
        "1.8은 관찰자 50%가 “이 정도면 받아들인다”고 한 공개 허용 역치(Paravina 2015). "
        "화면 얼굴 피부 실험도 ≈1.81(Lagouvardo 2018). 립스틱 전용 역치는 없어 "
        "<b>가장 가까운 공개 역치</b>로 씁니다.",
        styles["body"],
    ))
    story.append(_p(
        "<b>왜 판정 불가인가(쉬운 비유)</b> — 자로 재려는 길이보다 자 눈금이 더 굵은 상황. "
        "립스틱이 안 닿는 입 주변 피부(bare vs real)만 비교해도 ΔE≈2.9면, "
        "조명·노출이 이미 합격선(1.8)보다 크게 어긋난 것입니다. "
        "AR이 완벽해도 이 사진 쌍으로는 1.8 아래가 나오기 어렵습니다. "
        "그래서 불합격이 아니라 <b>판정 불가</b>. "
        "코드 조건: 피부 바닥값 &lt; 1.8일 때만 절대 합격·불합격을 매깁니다. "
        "상대 검정(맨입술보다 가깝나 ≥15/20)은 그 전과 무관하게 가능합니다.",
        styles["body"],
    ))
    story.append(_table([
        ["측정", "예시 값", "기준", "판정"],
        ["AR 입술 ΔE 중앙", "≈3.65", "≤1.8", "판정 불가(바닥값)"],
        ["맨입술보다 가까움", "17/20", "≥15/20", "합격"],
        ["피부 바닥값", "≈2.90", "&lt;1.8", "조건 미달"],
    ], [48 * mm, 36 * mm, 36 * mm, 50 * mm]))
    story.append(_p(
        "판정 가능하게 하려면: 같은 자리·노출·화이트밸런스 고정 + 가능하면 컬러체커. "
        "찍은 뒤 피부 바닥값이 1.8보다 충분히 작은지 먼저 확인.",
        styles["foot"],
    ))

    story.append(_p("② 위치(mIoU/F1) — 공개 최고 성적과 비교", styles["h"]))
    story.append(_p(
        "사람이 칠한 입술 정답과 예측이 얼마나 겹치나. 논문은 보통 F1(Dice)로 보고하고, "
        "IoU = F1/(2−F1)로 1:1 변환됩니다(F1 0.887 ⇔ IoU 0.797). "
        "합격선은 LaPa에서 공개된 최근 최고(SegFace AAAI 2025)의 입술 F1 0.887입니다. "
        "폰 실시간 랜드마크 vs 서버 분할은 <b>근사 비교</b>입니다.",
        styles["body"],
    ))
    story.append(_table([
        ["측정", "예시 값", "기준", "판정"],
        ["립 F1 (합산)", "≈0.840", "≥0.887", "불합격"],
        ["이전 버전 회귀", "—", "Wilcoxon p≥0.05", "미측정"],
        ["눈 목표 IoU", "—", "≥0.85", "내부 목표"],
    ], [48 * mm, 36 * mm, 36 * mm, 50 * mm]))

    story.append(_p("③ 질감 묶음 — 맨입술보다 확실히 낫나", styles["h"]))
    story.append(_p(
        "질감에는 공인 절대 역치가 없습니다. 대신 “AR을 올렸으면 맨입술보다는 실바에 가까워야 한다”를 "
        "명암 폭·하이라이트·SSIM 세 갈래로 재고, <b>각 ≥15/20</b>이어야 합격입니다. "
        "하나만 넘기면 합격으로 하면 우연히 통과할 확률이 커지므로 모두 통과를 요구합니다. "
        "명암·하이라이트는 팀 설계 프록시라 사람 광택 감각과의 연결은 설문으로 계속 보강합니다.",
        styles["body"],
    ))
    story.append(_table([
        ["수치", "예시 이긴 쌍", "기준", "판정"],
        ["명암 폭", "9/20", "≥15", "불합격"],
        ["하이라이트", "9/20", "≥15", "불합격"],
        ["결 SSIM", "4/20", "≥15", "불합격"],
    ], [48 * mm, 36 * mm, 36 * mm, 50 * mm]))

    # ── P5 limits + next ──
    story.append(PageBreak())
    story.append(_p("한계를 숨기지 않고 적음", styles["h"]))
    story.append(_table([
        ["지표", "한계", "사용 판단"],
        ["색", "역치가 치과·화면 피부 실험(립스틱 아님). 바닥값 크면 절대 판정 불가",
         "조건부 — 고정 촬영 후"],
        ["위치", "서버 SOTA vs 폰 실시간 근사. 입술 합산은 약간 유리할 수 있음",
         "사용 가능(근사)"],
        ["질감", "판정(15/20)은 객관. 명암·하이라이트 정의는 팀 프록시",
         "사용 가능"],
        ["SSIM/MAE\n절대값", "립스틱 AR 공개 절대선 없음",
         "기록만 + 눈 목표"],
        ["자연스러움", "이 문서 범위 밖",
         "트랙 A 문서"],
    ], [28 * mm, 88 * mm, 54 * mm]))

    story.append(_p("발표에서 이렇게 말하면 됩니다", styles["h"]))
    story.append(_p(
        "“AR 메이크업 전용 공인 합격선은 논문에 거의 없습니다. "
        "그래서 가장 가까운 공개 역치·같은 데이터 SOTA·통계 검정으로만 합격선을 정했습니다. "
        "팀이 고른 눈 앵커는 ‘이 정도면 눈으로 합격’ 목표이고, 공식 선을 바꾸지 않습니다. "
        "자연스러워 보이냐는 숫자 트랙이 아니라 사람·Astra 트랙으로 따로 봅니다.”",
        styles["body"],
    ))

    story.append(_p("다음에 할 일 (측정)", styles["h"]))
    story.append(_p(
        "① 노출 고정·컬러체커 bare/real 쌍 → 피부 바닥값 &lt;1.8 확인 후 ΔE 절대 판정<br/>"
        "② LaPa(또는 동의 데이터)로 F1/mIoU + 이전 버전 Wilcoxon<br/>"
        "③ 립 ROI에서 명암폭·하이라이트·SSIM·MAE·LPIPS → 각 15/20<br/>"
        "④ 결과 JSON으로 이 요약표의 ‘현재값·판정’ 칸을 갱신<br/>"
        "⑤ 자연스러움은 mentor Likert / Ext-B로 사람→Astra 일치",
        styles["body"],
    ))

    story.append(_p("파일", styles["h"]))
    story.append(_p(
        "· 기계 판독: research/eval_matrix/criteria_technical_v1.json (v1.2)<br/>"
        "· 근거 원본 매트릭스: research/eval_matrix/criteria_v2.1.json<br/>"
        "· 사다리 이미지: research/data/eval_matrix/tech_score_ladder/<br/>"
        "· 재생성: ml/.venv/Scripts/python.exe research/eval_matrix/export_technical_criteria_pdf.py",
        styles["foot"],
    ))

    if not LADDER.is_dir():
        raise FileNotFoundError(f"사다리 이미지 없음: {LADDER}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT2.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=10 * mm, bottomMargin=10 * mm,
        title="VISHUE AR 테크니컬 평가지표 v1.2",
        author="VISHUE",
    )
    doc.build(story)
    shutil.copyfile(OUT, OUT2)
    return OUT


if __name__ == "__main__":
    print(build())
