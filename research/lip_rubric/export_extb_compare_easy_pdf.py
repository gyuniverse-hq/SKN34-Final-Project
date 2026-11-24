"""Easy 1–2 page interpretation of Ext-B human vs Astra compare.

  ml/.venv/Scripts/python.exe research/lip_rubric/export_extb_compare_easy_pdf.py
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
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "VISHUE_AR_extB_human_astra_해석요약_20261120.pdf"
OUT2 = ROOT / "research" / "data" / "lip_rubric" / "learn_astra" / "VISHUE_AR_extB_human_astra_해석요약_20261120.pdf"
FONT = r"C:\Windows\Fonts\malgun.ttf"
FONT_B = r"C:\Windows\Fonts\malgunbd.ttf"


def _styles():
    pdfmetrics.registerFont(TTFont("Malgun", FONT))
    pdfmetrics.registerFont(TTFont("MalgunBold", FONT_B))
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "t", parent=base["Title"], fontName="MalgunBold", fontSize=14,
            leading=18, alignment=TA_CENTER, spaceAfter=4,
        ),
        "sub": ParagraphStyle(
            "s", parent=base["Normal"], fontName="Malgun", fontSize=8.2,
            leading=11, alignment=TA_CENTER, textColor=colors.HexColor("#555"), spaceAfter=8,
        ),
        "h": ParagraphStyle(
            "h", parent=base["Normal"], fontName="MalgunBold", fontSize=10.5,
            leading=14, spaceBefore=8, spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "b", parent=base["Normal"], fontName="Malgun", fontSize=8.5,
            leading=12, alignment=TA_JUSTIFY, spaceAfter=3,
        ),
        "big": ParagraphStyle(
            "big", parent=base["Normal"], fontName="MalgunBold", fontSize=9.5,
            leading=13, alignment=TA_LEFT, spaceAfter=4,
            textColor=colors.HexColor("#1b4f72"),
        ),
        "cell": ParagraphStyle(
            "c", parent=base["Normal"], fontName="Malgun", fontSize=7.2, leading=9.5, alignment=TA_LEFT,
        ),
        "cell_h": ParagraphStyle(
            "ch", parent=base["Normal"], fontName="MalgunBold", fontSize=7.2,
            leading=9.5, textColor=colors.white, alignment=TA_CENTER,
        ),
        "ok": ParagraphStyle(
            "ok", parent=base["Normal"], fontName="MalgunBold", fontSize=8.5,
            leading=12, textColor=colors.HexColor("#1b7a6e"), spaceAfter=2,
        ),
        "warn": ParagraphStyle(
            "warn", parent=base["Normal"], fontName="MalgunBold", fontSize=8.5,
            leading=12, textColor=colors.HexColor("#b35c00"), spaceAfter=2,
        ),
        "bad": ParagraphStyle(
            "bad", parent=base["Normal"], fontName="MalgunBold", fontSize=8.5,
            leading=12, textColor=colors.HexColor("#a33"), spaceAfter=2,
        ),
        "foot": ParagraphStyle(
            "f", parent=base["Normal"], fontName="Malgun", fontSize=7.0,
            leading=9.5, textColor=colors.HexColor("#555"),
        ),
    }


def _p(text, style):
    return Paragraph(str(text).replace("\n", "<br/>"), style)


def _table(rows, widths):
    styles = _styles()
    data = [[_p(c, styles["cell_h"] if i == 0 else styles["cell"]) for c in row]
            for i, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#ccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f7f7")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    return t


def build():
    styles = _styles()
    story = []

    story.append(_p("사람 vs Astra 채점 — 이렇게 읽으면 됩니다", styles["title"]))
    story.append(_p(
        "Ext-B 10장 · 사람 5명 · Astra 1회 · 자세한 표는 원본 비교 PDF · 2026-11-20",
        styles["sub"],
    ))

    story.append(_p("30초 결론", styles["h"]))
    story.append(_p(
        "① 채점표 방향은 맞다 → 스티커(나쁨) &lt; 렌더 &lt; 실립(좋음)<br/>"
        "② Astra는 <b>합격/불합격(게이트)만</b> 사람과 잘 맞음 (90%)<br/>"
        "③ 점수(S)까지 사람 대신 맡기기엔 이름 → Astra가 나쁜 장을 <b>더 후하게</b> 줌",
        styles["big"],
    ))

    story.append(_p("숫자 카드 (의미만)", styles["h"]))
    story.append(_table([
        ["숫자", "뜻 (쉽게)", "그래서?"],
        ["게이트 일치\n90% (9/10)",
         "열 장 중 아홉 장,\n합격·불합격이 사람과 같음",
         "통과/실패 걸러내기는\n쓸 만함"],
        ["문항 일치\n평균 74%",
         "세부 yes/no는\n네 번 중 세 번 정도 맞음",
         "문항별로는\n아직 흔들림"],
        ["S 상관\n0.58",
         "점수 순위가\n사람과 ‘대충’ 같음\n(1.0=완벽)",
         "순위 참고용"],
        ["S 오차 0.18\n편향 +0.11",
         "점수 차이가 평균 0.18\nAstra가 +0.11 더 후함",
         "나쁜 장에서\n특히 후함"],
    ], [36 * mm, 68 * mm, 66 * mm]))

    story.append(_p("종류별로 보면 (핵심)", styles["h"]))
    story.append(_table([
        ["종류", "사람 S", "Astra S", "한 줄 해석"],
        ["스티커 (실패 앵커)", "0.17", "0.46", "게이트 fail은 같음. 점수는 Astra가 훨씬 후함"],
        ["렌더 (중간)", "0.56", "0.64", "대체로 비슷. 한 장은 Astra만 만점급으로 어긋남"],
        ["실립 (좋은 앵커)", "0.94", "0.93", "거의 동일 → 좋은 장은 잘 맞춤"],
    ], [40 * mm, 28 * mm, 28 * mm, 74 * mm]))

    story.append(_p("신호등으로 정리", styles["h"]))
    story.append(_p("초록 — 잘된 것", styles["ok"]))
    story.append(_p(
        "· 사람끼리도 스티커 &lt; 렌더 &lt; 실립 순서가 나옴 → 채점표가 상·중·하를 가름<br/>"
        "· Astra 게이트 90% 일치 → “이 장 통과/실패” 보조로 후보",
        styles["body"],
    ))
    story.append(_p("노랑 — 주의", styles["warn"]))
    story.append(_p(
        "· 경계·배치 문항(당시 E1·E2)은 사람끼리도 일치가 낮고, Astra와도 60%만 맞음<br/>"
        "· 그래서 나중에 E1로 합친 것(영역+번짐 한 문항)이 타당함",
        styles["body"],
    ))
    story.append(_p("빨강 — 아직 안 됨", styles["bad"]))
    story.append(_p(
        "· Astra 점수만으로 “이 렌더가 0.8점”처럼 절대 점수 쓰기<br/>"
        "· 실패 장(스티커·어색한 렌더)을 사람만큼 엄하게 깎기",
        styles["body"],
    ))

    story.append(_p("멘토/팀에게 한 문장", styles["h"]))
    story.append(_p(
        "“사람 정답과 비교해 보니, Astra는 <b>합격·불합격 게이트는 90%로 쓸 만하고</b>, "
        "세부 점수·실패 장 엄격함은 아직 사람보다 헐렁합니다. "
        "지금은 게이트 보조로 두고, 점수 위임은 예시·장수를 더 넣은 뒤 다시 보겠습니다.”",
        styles["body"],
    ))

    story.append(Spacer(1, 3 * mm))
    story.append(_p(
        "원본(표·그래프): reports/VISHUE_AR_extB_human_astra_20261120.pdf<br/>"
        "채점 기준(현행 E1–E6): reports/VISHUE_AR_vlm_naturalness_extB_v1.2.1_20261120.pdf<br/>"
        "※ 이 비교는 E1–E7 당시 기준으로 돌린 1회 결과입니다. v1.2.1로 재채점하면 숫자가 달라질 수 있습니다.",
        styles["foot"],
    ))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT2.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title="Ext-B human vs Astra easy interpretation",
    )
    doc.build(story)
    shutil.copyfile(OUT, OUT2)
    return OUT


if __name__ == "__main__":
    print(build())
