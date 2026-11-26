"""Export Ext-B pipeline summary PDF (criteria → human → Astra).

  ml/.venv/Scripts/python.exe research/lip_rubric/export_extb_report_pdf.py
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "research" / "data" / "lip_rubric" / "extb_pack"
HUM = PACK / "human_results"
AST = PACK / "astra_results"
CHARTS = HUM / "charts"
OUT = ROOT / "reports" / "VISHUE_AR_extB_human_astra_20261120.pdf"
OUT2 = ROOT / "research" / "data" / "lip_rubric" / "learn_astra" / "VISHUE_AR_extB_human_astra_20261120.pdf"
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
        "body": ParagraphStyle(
            "b", parent=base["Normal"], fontName="Malgun", fontSize=8.3,
            leading=11.5, alignment=TA_JUSTIFY, spaceAfter=3,
        ),
        "cell": ParagraphStyle(
            "c", parent=base["Normal"], fontName="Malgun", fontSize=6.8, leading=9.0,
        ),
        "cell_h": ParagraphStyle(
            "ch", parent=base["Normal"], fontName="MalgunBold", fontSize=6.8,
            leading=9.0, textColor=colors.white, alignment=TA_CENTER,
        ),
        "cap": ParagraphStyle(
            "cap", parent=base["Normal"], fontName="Malgun", fontSize=7.5,
            leading=10, textColor=colors.HexColor("#555"), alignment=TA_CENTER, spaceAfter=6,
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


def _img(path: Path, max_w_mm: float = 170, max_h_mm: float = 90):
    if not path.is_file():
        return None
    im = Image(str(path))
    w, h = im.imageWidth, im.imageHeight
    scale = min((max_w_mm * mm) / w, (max_h_mm * mm) / h)
    im.drawWidth = w * scale
    im.drawHeight = h * scale
    return im


def build():
    styles = _styles()
    hum = json.loads((HUM / "aggregate.json").read_text(encoding="utf8"))
    cmp_ = json.loads((AST / "compare_human.json").read_text(encoding="utf8"))
    story = []

    story.append(_p("Ext-B 자연스러움 채점 — 사람 vs Astra 정리", styles["title"]))
    story.append(_p(
        "트랙 A · E1–E7 예/아니오 · 게이트+가중 S · 10장 · 사람 5명(R1–R5) · Astra 1회 · 2026-11-20",
        styles["sub"],
    ))

    story.append(_p("0. 한 줄 요약", styles["h"]))
    story.append(_p(
        "채점표(안 B)로 사람 5명이 10장을 채점했을 때 <b>스티커 &lt; 렌더 &lt; 실립</b> 순서가 유지됐다. "
        "같은 프롬프트로 Astra를 돌리면 <b>게이트(합격/불합격)는 사람 다수결과 90% 일치</b>한다. "
        "가중 점수 S는 순위 상관 0.58·평균 오차 0.18이며, Astra가 실패 장(스티커·일부 렌더)을 "
        "<b>사람보다 후하게</b> 주는 경향이 있다. 절대 점수 위임은 이르고, 게이트 보조로는 후보 수준이다.",
        styles["body"],
    ))

    story.append(_p("1. 무엇을 했나 (파이프라인)", styles["h"]))
    story.append(_table([
        ["단계", "내용"],
        ["① 기준", "외부 레퍼 축 → E1–E7 예/아니오 재작성 (색 일치·E8 제외)"],
        ["② 가중", "게이트 E1·E2·E7 + 가중 S (합 1.0, 팀 초안)"],
        ["③ 이미지", "기존 lip_rubric pack에서 10장 (스티커2·렌더6·실립2), kind 숨김"],
        ["④ 사람", "R1–R5 동일 UI 채점 → CSV"],
        ["⑤ Astra", "한국어 프롬프트 + crop/full + finish만 제공 → JSON → CSV"],
        ["⑥ 비교", "사람 다수결 vs Astra (게이트·문항·S)"],
    ], [28 * mm, 142 * mm]))

    story.append(_p("2. 채점표 E1–E7 (요약)", styles["h"]))
    story.append(_table([
        ["ID", "역할", "w", "문항 요지", "통과"],
        ["E1", "게이트", "0.22", "색이 입술 안에만 (피부·이·수염으로 안 나감)", "yes"],
        ["E2", "게이트", "0.18", "외곽 번짐 없음", "yes"],
        ["E3", "점수", "0.14", "제형(매트/새틴/글로시)과 광택 일치", "yes"],
        ["E4", "점수", "0.12", "페인트/플라스틱 아님, 텍스처 있음", "yes"],
        ["E5", "점수", "0.10", "하이라이트 방향 = 얼굴 조명", "yes"],
        ["E6", "점수", "0.06", "입술 형태 왜곡 없음", "yes"],
        ["E7", "게이트", "0.18", "합성 아티팩트 없음", "yes"],
    ], [12 * mm, 16 * mm, 12 * mm, 108 * mm, 14 * mm]))
    story.append(_p(
        "게이트 fail = E1·E2·E7 중 하나라도 no. "
        "S = Σ(w·pass)/Σ(w) (na 제외). 색=실물인지는 묻지 않음(ΔE/트랙 B).",
        styles["body"],
    ))

    story.append(PageBreak())
    story.append(_p("3. 사람 채점 결과 (R1–R5)", styles["h"]))
    story.append(_table([
        ["kind", "장수×평가", "평균 S", "게이트 통과율"],
        ["sticker", "2×5", f"{hum['mean_S_by_kind']['sticker']['mean_S']:.2f}",
         f"{hum['gate_rate_by_kind']['sticker']*100:.0f}%"],
        ["render", "6×5", f"{hum['mean_S_by_kind']['render']['mean_S']:.2f}",
         f"{hum['gate_rate_by_kind']['render']*100:.0f}%"],
        ["real", "2×5", f"{hum['mean_S_by_kind']['real']['mean_S']:.2f}",
         f"{hum['gate_rate_by_kind']['real']*100:.0f}%"],
    ], [30 * mm, 35 * mm, 40 * mm, 45 * mm]))
    story.append(_p(
        f"평가자 게이트 쌍 일치 {hum['gate_pairwise_mean']:.0%}. "
        "문항 쌍 일치: E5 {e5:.0%} · E7 {e7:.0%} · E1·E2 {e1:.0%}(가장 낮음). "
        "스티커&lt;렌더&lt;실립 순서 유지 → 채점표 방향 검증.".format(
            e5=hum["item_agreement"]["E5"]["pair_mean"],
            e7=hum["item_agreement"]["E7"]["pair_mean"],
            e1=hum["item_agreement"]["E1"]["pair_mean"],
        ),
        styles["body"],
    ))

    im = _img(CHARTS / "00_overview.png", 170, 105)
    if im:
        story.append(im)
        story.append(_p("그림 1. 사람 채점 요약 (kind별 S·게이트 · 문항 일치)", styles["cap"]))

    im = _img(CHARTS / "03_per_image_S.png", 170, 95)
    if im:
        story.append(im)
        story.append(_p("그림 2. 장별 평균 S (테두리=게이트 다수결 통과)", styles["cap"]))

    story.append(PageBreak())
    story.append(_p("4. Astra 채점 · 사람 다수결과 비교", styles["h"]))
    story.append(_p(
        "Astra 입력: 한국어 System/User 프롬프트 + 입술 crop + 얼굴 full + finish만. "
        "kind·사람 정답 미제공. 출력 JSON → gate/S는 코드 계산.",
        styles["body"],
    ))
    story.append(_table([
        ["지표", "값", "해석"],
        ["게이트 일치", f"{cmp_['gate_agree_vs_human_majority']:.0%} (9/10)",
         "합격/불합격은 사람과 잘 맞음"],
        ["문항 평균 일치", f"{cmp_['item_agree_mean']:.0%}", "세부 yes/no는 중간"],
        ["S Spearman", f"{cmp_['spearman_S_astra_vs_human_mean']:.2f}", "순위는 대충 맞음"],
        ["S MAE / bias", "0.18 / +0.11", "Astra가 평균적으로 후함"],
    ], [36 * mm, 42 * mm, 92 * mm]))

    story.append(_p("문항별 Astra↔사람 일치", styles["h"]))
    ia = cmp_["item_agree"]
    story.append(_table([
        ["E1", "E2", "E3", "E4", "E5", "E6", "E7"],
        *[
            [f"{ia[q]:.0%}" for q in ["E1", "E2", "E3", "E4", "E5", "E6", "E7"]],
        ],
    ], [24 * mm] * 7))
    story.append(_p("E5는 전부 일치. E1·E2가 가장 낮음(사람끼리도 흔들리던 문항).", styles["body"]))

    story.append(_p("kind별 점수만 비교", styles["h"]))
    bk = cmp_["by_kind"]
    story.append(_table([
        ["kind", "사람 평균 S", "Astra S", "게이트 일치"],
        ["sticker", f"{bk['sticker']['mean_human_S']:.2f}", f"{bk['sticker']['mean_astra_S']:.2f}",
         f"{bk['sticker']['gate_agree']:.0%}"],
        ["render", f"{bk['render']['mean_human_S']:.2f}", f"{bk['render']['mean_astra_S']:.2f}",
         f"{bk['render']['gate_agree']:.0%}"],
        ["real", f"{bk['real']['mean_human_S']:.2f}", f"{bk['real']['mean_astra_S']:.2f}",
         f"{bk['real']['gate_agree']:.0%}"],
    ], [30 * mm, 40 * mm, 40 * mm, 40 * mm]))
    story.append(_p(
        "실립은 점수·게이트 모두 거의 동일. 스티커는 게이트 fail은 같으나 "
        "Astra S(0.46) ≫ 사람(0.17). 렌더 한 장(0b1f… matte)에서 Astra만 게이트 통과·S=1.00 "
        "(사람 평균 S 0.36)으로 크게 어긋남.",
        styles["body"],
    ))

    story.append(_p("장별 S 대조", styles["h"]))
    imgs = sorted(cmp_["images"], key=lambda x: -x["human_mean_S"])
    rows = [["kind", "finish", "사람 S", "Astra S", "Δ", "게이트 일치"]]
    for c in imgs:
        dlt = c["astra_S"] - c["human_mean_S"]
        rows.append([
            c["kind"], c["finish"],
            f"{c['human_mean_S']:.2f}", f"{c['astra_S']:.2f}",
            f"{dlt:+.2f}", "Y" if c["gate_match"] else "N",
        ])
    story.append(_table(rows, [22 * mm, 22 * mm, 24 * mm, 24 * mm, 22 * mm, 28 * mm]))

    story.append(PageBreak())
    story.append(_p("5. 해석 · 다음에 할 일", styles["h"]))
    story.append(_p(
        "· 사람 쪽: 채점표가 상·중·하를 가르므로 <b>정답 라벨로 쓸 수 있다</b> "
        "(표본 10장이라 확정 통계는 아님).<br/>"
        "· Astra 쪽: <b>게이트 보조</b>로는 쓸 만함(90%). "
        "<b>절대 S·실패 장 엄격함</b>은 아직 사람 대체 불가.<br/>"
        "· 개선: E1·E2 통과/실패 예시 crop을 프롬프트에 추가, 이상치 장 재검, "
        "장수 확대 후 재측정.<br/>"
        "· 위임 조건(제안): 게이트 일치 ≥0.85 유지 + 스티커/실패 장 S 편향 축소 + "
        "이상치 재발 없음 — 이번 1회만으로는 미충족.",
        styles["body"],
    ))

    story.append(_p("6. 산출물 경로", styles["h"]))
    story.append(_p(
        "· 기준: research/lip_rubric/criteria_vlm_ext_b_v1.json<br/>"
        "· 프롬프트: research/lip_rubric/extb_astra_prompt.md<br/>"
        "· 채점팩: research/data/lip_rubric/extb_pack/<br/>"
        "· 사람 집계: …/human_results/aggregate.json · charts/<br/>"
        "· Astra CSV: …/astra_results/extb_scores_Astra.csv<br/>"
        "· 비교: …/astra_results/compare_human.json<br/>"
        "· 기준 설명 PDF: reports/VISHUE_AR_vlm_naturalness_extB_v1.1_20261120.pdf",
        styles["foot"],
    ))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT2.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=11 * mm, bottomMargin=11 * mm,
        title="Ext-B human vs Astra 2026-11-20",
        author="VISHUE",
    )
    doc.build(story)
    shutil.copyfile(OUT, OUT2)
    return OUT


if __name__ == "__main__":
    print(build())
