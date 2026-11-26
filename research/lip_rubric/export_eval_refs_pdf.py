"""Saturday handout: 1-2 page external evaluation reference sheet.

  ml/.venv/Scripts/python.exe research/lip_rubric/export_eval_refs_pdf.py
"""
from __future__ import annotations

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
OUT = ROOT / "research" / "data" / "lip_rubric" / "learn_astra" / "lip_eval_external_refs_1p_20261120.pdf"
# also copy-friendly path under reports (no face images)
OUT_REPORTS = ROOT / "reports" / "lip_eval_external_refs_1p_20261120.pdf"
FONT = r"C:\Windows\Fonts\malgun.ttf"
FONT_B = r"C:\Windows\Fonts\malgunbd.ttf"


def _styles():
    pdfmetrics.registerFont(TTFont("Malgun", FONT))
    pdfmetrics.registerFont(TTFont("MalgunBold", FONT_B))
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "t", parent=base["Title"], fontName="MalgunBold", fontSize=13,
            leading=18, alignment=TA_CENTER, spaceAfter=4,
        ),
        "sub": ParagraphStyle(
            "s", parent=base["Normal"], fontName="Malgun", fontSize=8.5,
            leading=11, alignment=TA_CENTER, textColor=colors.HexColor("#555"), spaceAfter=6,
        ),
        "h": ParagraphStyle(
            "h", parent=base["Normal"], fontName="MalgunBold", fontSize=9.5,
            leading=13, spaceBefore=5, spaceAfter=3, textColor=colors.HexColor("#1f4e79"),
        ),
        "body": ParagraphStyle(
            "b", parent=base["Normal"], fontName="Malgun", fontSize=8.2,
            leading=11.5, alignment=TA_JUSTIFY, spaceAfter=3,
        ),
        "cell": ParagraphStyle(
            "c", parent=base["Normal"], fontName="Malgun", fontSize=6.8, leading=9,
        ),
        "cell_h": ParagraphStyle(
            "ch", parent=base["Normal"], fontName="MalgunBold", fontSize=6.8,
            leading=9, textColor=colors.white, alignment=TA_CENTER,
        ),
        "foot": ParagraphStyle(
            "f", parent=base["Normal"], fontName="Malgun", fontSize=7,
            leading=9, alignment=TA_LEFT, textColor=colors.HexColor("#666"),
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
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fa")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def build():
    styles = _styles()
    story = []

    story.append(_p("AR·가상 메이크업 평가지표 외부 레퍼런스 (제출용 요약)", styles["title"]))
    story.append(_p(
        "VISHUE · 2026-11-20 · 목적: 자체 채점표만이 아니라 논문·업계에서 쓰는 평가 축을 정리하고, "
        "러프 세팅 후보 2가지를 제안",
        styles["sub"],
    ))

    story.append(_p("1. 한 줄 결론", styles["h"]))
    story.append(_p(
        "Perfect Corp·ModiFace 등 상용 AR사는 <b>공개 평가 벤치마크·채점표를 거의 내지 않는다</b>. "
        "학술(메이크업 전이·립 시뮬레이션)과 인접 분야(의류 가상피팅)에는 "
        "<b>SSIM / L1·LPIPS / ΔE / Patch-FID / 사람평가 / VLM-as-Judge</b>가 반복된다. "
        "따라서 ‘우리만의 25체크’는 세부 진단용으로 두고, 바깥 보고·러프 검증은 아래 외부 축을 인용하는 것이 맞다.",
        styles["body"],
    ))

    story.append(_p("2. 출처별 공개 여부", styles["h"]))
    story.append(_table([
        ["출처", "공개 평가지표·벤치", "비고"],
        ["Perfect Corp / YouCam", "없음 (API·마케팅)", "색·텍스처·피니시 주장만"],
        ["ModiFace / L’Oréal", "거의 없음", "피부톤 내부 수치 등만 간헐 인용"],
        ["학술 — 립/메이크업", "있음", "LipAT, BeautyGAN 계열, 파운데이션 VTO"],
        ["학술 — 의류 VTON", "최근 활발", "VTON-IQA, Taobao VLM Judge (메이크업 전용 아님)"],
        ["우리 AR_SPEC 8장", "이미 후보 표기", "ΔE, IoU, LPIPS, SSIM, 사람, VLM"],
    ], [38 * mm, 48 * mm, 84 * mm]))

    story.append(_p("3. 논문에서 반복되는 지표 (레퍼런스 표)", styles["h"]))
    story.append(_table([
        ["지표", "보는 것", "↑/↓", "대표 출처", "우리 적용"],
        ["SSIM", "구조·명암 유사", "↑", "LipAT; 파운데이션 VTO", "립 마스크/박스 안"],
        ["L1 / MAE", "픽셀 절대 오차", "↓", "LipAT", "실바르기 쌍이 있을 때"],
        ["LPIPS", "지각 유사도", "↓", "파운데이션 VTO; TinyBeauty", "립 crop 보조"],
        ["ΔE CIE2000", "색 차이", "↓", "파운데이션 VTO; AR_SPEC 트랙 B", "제품/실물 색"],
        ["Patch-FID", "립 패치 리얼리즘", "↓", "LipAT (사람평가와 상관 높음)", "표본 늘린 뒤"],
        ["FID (전체)", "분포 거리", "↓", "BeautyREC 등", "표본 적으면 비추 (AR_SPEC도 동일)"],
        ["IoU / 경계", "부착·마스크", "↑", "시스템·세그 논문", "트랙 A 부착"],
        ["사람 1~5 / A/B", "자연스러움", "—", "거의 모든 논문", "기준값(GT 감각)"],
        ["VLM-as-Judge", "무참조 품질", "—", "Taobao-Tryon; VTON-IQA 계열", "Astra API 러프 평가"],
    ], [28 * mm, 32 * mm, 12 * mm, 48 * mm, 50 * mm]))

    story.append(_p("4. 데이터·모델이 쓰는 것 (짧게)", styles["h"]))
    story.append(_table([
        ["이름", "데이터/설정", "비고"],
        ["MT (BeautyGAN 계열)", "비메이크업~1.1k + 메이크업~2.7k", "전이 벤치의 사실상 표준 데이터"],
        ["LipAT", "립스틱 before–after 쌍 + 속성", "립 박스 SSIM/L1, Patch-FID"],
        ["파운데이션 VTO (2507.07333)", "10명 before/after + 컬러체커", "ΔE·SSIM·LPIPS"],
        ["VTON-QBench", "의류 try-on 6만+장·대규모 사람평가", "메이크업 아님, 무참조 IQA 참고"],
    ], [42 * mm, 72 * mm, 56 * mm]))

    story.append(_p("5. 토요일까지 제안 — 러프 평가 세팅 2가지 (하나만 쓰지 않음)", styles["h"]))
    story.append(_table([
        ["#", "방법", "하는 일", "성공 판정(러프)"],
        ["1", "Astra VLM-as-Judge\n(로컬 말고 API)",
         "같은 사진에 짧은 질문 3~5개\n(결·떠 보임·실제처럼 1~5).\n순서 바꿔 2회 → 편향 체크.\n눈으로 점수↔화면 대조.",
         "극단(스티커 vs 실립)이 갈리고,\n순서를 바꿔도 같은 쪽을 고침"],
        ["2", "기술 지표 러프 세트\n(논문 공통축)",
         "립 마스크 IoU(부착),\n가능 시 ΔE(색),\n립 crop LPIPS/SSIM\n(실바르기 또는 before–after).",
         "수치 방향이 상식과 같음\n(스티커↑오차, 실립↓오차).\n사람/Astra와 대략 같은 순위"],
    ], [10 * mm, 38 * mm, 72 * mm, 50 * mm]))
    story.append(_p(
        "내부 25체크 채점표는 ‘세부 품질 분해’로 유지하고, "
        "외부 설명·멘토 보고에는 <b>표3 축 + 위 2세팅</b>을 전면에 둔다. "
        "화장품 자극 이미지는 ChatGPT 생성으로 보조 가능(정답 쌍 대체 아님).",
        styles["body"],
    ))

    story.append(_p("6. 주요 링크", styles["h"]))
    story.append(_p(
        "• LipAT (WACV 2024): openaccess.thecvf.com … Lipstick_WACV_2024_paper.pdf<br/>"
        "• Foundation VTO: arxiv.org/abs/2507.07333<br/>"
        "• VTON-IQA: arxiv.org/html/2603.13057v1 · github.com/litelightlite/VTON-IQA<br/>"
        "• Taobao-Tryon-Benchmark: huggingface.co/datasets/TaoTianGroup/Taobao-Tryon-Benchmark<br/>"
        "• 우리 설계: docs/AR_SPEC.md 8장 평가 방법 후보 표",
        styles["foot"],
    ))
    story.append(Spacer(1, 2 * mm))
    story.append(_p(
        "본 1쪽 요약은 공개 문헌·문서 조사 결과이며, 상용사 비공개 프로토콜을 주장하지 않는다. "
        "재생성: ml/.venv/Scripts/python.exe research/lip_rubric/export_eval_refs_pdf.py",
        styles["foot"],
    ))

    import shutil

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORTS.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title="AR 평가지표 외부 레퍼런스",
        author="VISHUE",
    )
    doc.build(story)
    shutil.copyfile(OUT, OUT_REPORTS)
    return OUT, OUT_REPORTS


if __name__ == "__main__":
    a, b = build()
    print(a)
    print(b)
