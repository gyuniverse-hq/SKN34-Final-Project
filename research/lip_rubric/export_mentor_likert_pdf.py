"""Export mentor-aligned 3-axis × 1–5 criteria PDF.

  ml/.venv/Scripts/python.exe research/lip_rubric/export_mentor_likert_pdf.py
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[2]
CRIT = ROOT / "research" / "lip_rubric" / "criteria_mentor_likert_v1.json"
OUT = ROOT / "reports" / "VISHUE_AR_mentor_likert_v1_20261120.pdf"
OUT2 = ROOT / "research" / "data" / "lip_rubric" / "learn_astra" / "VISHUE_AR_mentor_likert_v1_20261120.pdf"
FONT = r"C:\Windows\Fonts\malgun.ttf"
FONT_B = r"C:\Windows\Fonts\malgunbd.ttf"


def _styles():
    pdfmetrics.registerFont(TTFont("Malgun", FONT))
    pdfmetrics.registerFont(TTFont("MalgunBold", FONT_B))
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "t", parent=base["Title"], fontName="MalgunBold", fontSize=13.5,
            leading=18, alignment=TA_CENTER, spaceAfter=4,
        ),
        "sub": ParagraphStyle(
            "s", parent=base["Normal"], fontName="Malgun", fontSize=8.2,
            leading=11, alignment=TA_CENTER, textColor=colors.HexColor("#555"), spaceAfter=8,
        ),
        "h": ParagraphStyle(
            "h", parent=base["Normal"], fontName="MalgunBold", fontSize=10.5,
            leading=14, spaceBefore=8, spaceAfter=4,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Normal"], fontName="MalgunBold", fontSize=9.2,
            leading=12, spaceBefore=6, spaceAfter=2, textColor=colors.HexColor("#1b7a6e"),
        ),
        "body": ParagraphStyle(
            "b", parent=base["Normal"], fontName="Malgun", fontSize=8.3,
            leading=11.5, alignment=TA_JUSTIFY, spaceAfter=3,
        ),
        "cell": ParagraphStyle(
            "c", parent=base["Normal"], fontName="Malgun", fontSize=6.8, leading=9.0, alignment=TA_LEFT,
        ),
        "cell_h": ParagraphStyle(
            "ch", parent=base["Normal"], fontName="MalgunBold", fontSize=6.8,
            leading=9.0, textColor=colors.white, alignment=TA_CENTER,
        ),
        "foot": ParagraphStyle(
            "f", parent=base["Normal"], fontName="Malgun", fontSize=7.2,
            leading=9.5, textColor=colors.HexColor("#555"),
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
        ("LEFTPADDING", (0, 0), (-1, -1), 2.2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.2),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
    ]))
    return t


def build():
    crit = json.loads(CRIT.read_text(encoding="utf8"))
    styles = _styles()
    story = []

    story.append(_p("립 AR 평가 본선 지표 — 멘토 정렬 v1.0 (3축 × 1–5)", styles["title"]))
    story.append(_p(
        "영역 정확도 · 자연스러움 · 이미지 일관성 · bare|after 프로토콜 · 2026-11-20",
        styles["sub"],
    ))

    story.append(_p("0. 이 문서의 위치", styles["h"]))
    story.append(_p(
        "2026-11-19 멘토링에서 요청된 <b>2~3개 축 × 1–5 Likert</b> 본선 표다. "
        "내부 Ext-B(E1–E6 예/아니오)와 R5 25체크는 탐색·디버그용으로 두고, "
        "<b>멘토 보고·Astra 위임·생성 개선 트래킹은 이 표</b>를 쓴다.",
        styles["body"],
    ))

    story.append(_p("1. 채점 규칙", styles["h"]))
    story.append(_table([
        ["항목", "규칙"],
        ["축", "A1 영역 정확도 · A2 자연스러움 · A3 이미지 일관성"],
        ["척도", "각 축 정수 1–5 (아래 Likert 문구 그대로)"],
        ["입력", "화장 전(맨입술) + 화장 후. 없으면 화장 후만(A3=프레임 내 정합)"],
        ["숨김", "kind(스티커/렌더/실물), hex, 모델명"],
        ["overall", "(A1+A2+A3)/3"],
        ["소프트 게이트", "어느 축이든 1 또는 2 → overall_fail 권고(평균은 기록)"],
        ["제외", "제품 ΔE(트랙 B) · 25 OX 합산 총점"],
    ], [32 * mm, 138 * mm]))

    story.append(_p("2. 세 축 정의 (채점에 그대로 사용)", styles["h"]))
    for it in crit["items"]:
        story.append(_p(f"{it['id']} {it['name_ko']} — {it['question']}", styles["h2"]))
        rows = [["점수", "의미"]]
        for s in ["1", "2", "3", "4", "5"]:
            rows.append([s, it["likert"][s]])
        story.append(_table(rows, [14 * mm, 156 * mm]))
        ref_lines = " · ".join(f"{r['source']} ({r['axis']})" for r in it["refs"])
        story.append(_p(f"레퍼: {ref_lines}", styles["foot"]))
        story.append(_p(f"포함 이유: {it['why_included']}", styles["foot"]))

    story.append(PageBreak())
    story.append(_p("3. 멘토 지시 → 이 표에서의 대응", styles["h"]))
    story.append(_table([
        ["멘토 말", "대응"],
        ["영역 정확도 / 일관성 / 자연스러움", "A1 / A3 / A2"],
        ["1–5만 구체적으로", "축별 Likert 1–5 문구 고정"],
        ["레퍼 없이 임의 문항 위험", "축마다 출처·원 축 이름 명시"],
        ["25 OX 합산 금지·단순화", "3축만. 합산은 평균+소프트 게이트"],
        ["사람 → AI 일치 후 위임", "팩 사람 채점 → 같은 프롬프트 Astra"],
        ["Astra 되면 로컬 평가모델 불필요", "위임 시 Astra 유지(학습 강제 안 함)"],
        ["삼단/전후", "화장 전|화장 후 나란히 (pack)"],
    ], [58 * mm, 112 * mm]))

    story.append(_p("4. 다음 실행 순서", styles["h"]))
    story.append(_p(
        "① research/data/lip_rubric/mentor_pack/index.html 사람 채점(소수) → "
        "② mentor_astra_prompt.md로 Astra → "
        "③ 축별 일치·Spearman → "
        "④ 충분하면 Astra 위임 고정 → "
        "⑤ 생성/렌더 개선은 A1–A3만으로 전후 비교. "
        "기술 보조(ΔE·IoU·SSIM)는 점수–사진 괴리 시 교차검증.",
        styles["body"],
    ))

    story.append(_p("5. 파일", styles["h"]))
    story.append(_p(
        "· 기준: research/lip_rubric/criteria_mentor_likert_v1.json<br/>"
        "· Astra: research/lip_rubric/mentor_astra_prompt.md<br/>"
        "· 채점 팩: research/data/lip_rubric/mentor_pack/<br/>"
        "· Ext-B(참고): research/lip_rubric/criteria_vlm_ext_b_v1.json",
        styles["foot"],
    ))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT2.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title="VISHUE AR mentor Likert v1.0",
    )
    doc.build(story)
    shutil.copyfile(OUT, OUT2)
    return OUT


if __name__ == "__main__":
    print(build())
