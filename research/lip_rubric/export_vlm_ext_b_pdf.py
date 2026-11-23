"""Export Plan-B VLM naturalness criteria PDF (E1–E6, v1.2.1) with reference mapping.

  ml/.venv/Scripts/python.exe research/lip_rubric/export_vlm_ext_b_pdf.py
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
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "VISHUE_AR_vlm_naturalness_extB_v1.2.1_20261120.pdf"
OUT2 = ROOT / "research" / "data" / "lip_rubric" / "learn_astra" / "VISHUE_AR_vlm_naturalness_extB_v1.2.1_20261120.pdf"
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
    styles = _styles()
    story = []

    story.append(_p("립 AR 자연스러움 VLM/Astra 채점표 — 안 B v1.2.1 (E1–E6)", styles["title"]))
    story.append(_p(
        "외부 레퍼 축 → 예/아니오 · 게이트+가중 · E1 통합 · 가중 리밸런스 · E8 제외 · 2026-11-20",
        styles["sub"],
    ))

    story.append(_p("0. 이 문서가 말하는 것", styles["h"]))
    story.append(_p(
        "사람 → Astra 일치 검증 → 이후 Astra 위임 파이프라인용 <b>트랙 A 자연스러움</b> 간이 채점표다. "
        "레퍼런스에는 보통 <b>축 이름·짧은 정의·Likert</b>가 있고, 아래 E1–E6 문장은 "
        "그 축을 립 try-on에 맞게 <b>다시 쓴 것</b>이다. "
        "논문/블로그에 동일한 한글 문항이 있는 것이 아니다.",
        styles["body"],
    ))
    story.append(_p(
        "범위: 보이는 자연스러움만. <b>색이 실물과 같은지</b>는 ΔE(트랙 B)로 분리하며 이 표에 넣지 않는다 "
        "(프로젝트 AR_SPEC 8-B-3과 동일).",
        styles["body"],
    ))

    story.append(_p("1. 답·집계 규칙 (게이트 + 가중) — v1.2.1", styles["h"]))
    story.append(_p(
        "v1.2에서 구 E1(배치)과 E2(번짐)를 <b>E1 한 문항</b>으로 합쳤고, "
        "v1.2.1에서 E1 가중 0.40을 풀어 제형·텍스처·조명으로 분산했다 "
        "(치명도는 게이트 E1·E6이 담당). 가중치는 팀 초안이며 공개 논문 역치가 아니다.",
        styles["body"],
    ))
    story.append(_table([
        ["항목", "규칙"],
        ["답", "예 / 아니오 / 해당없음 (E2만, 제형 미표기 시)"],
        ["통과", "문항별 ‘통과 답’과 일치 → pass_i = 1, 아니면 0"],
        ["게이트", "E1·E6 중 하나라도 실패 → 전체 fail"],
        ["가중 점수 S", "S = Σ(w_i·pass_i) / Σ(w_i)  (NA 항 제외·재정규화)"],
        ["보고", "gate_pass · S · 문항별 0/1 벡터"],
        ["입력", "입술 crop + (가능하면) 얼굴 전체 · 제형 문자열"],
        ["제외", "E8 · 색 일치 · 1~5 총평 Likert"],
    ], [32 * mm, 138 * mm]))

    story.append(_p("1-1. 가중치 표 (합=1.0, v1.2.1)", styles["h"]))
    story.append(_table([
        ["ID", "역할", "w", "왜 이 가중인가"],
        ["E1", "게이트", "0.22", "영역 밖·번짐·딱딱한 경계 — 치명도는 게이트"],
        ["E6", "게이트", "0.22", "떠 있는 색·이중선 → 필터 티 (구 E7)"],
        ["E2", "점수", "0.16", "제형·광택 (구 E3)"],
        ["E3", "점수", "0.16", "텍스처 vs 페인트 (구 E4)"],
        ["E4", "점수", "0.14", "조명·하이라이트 (구 E5)"],
        ["E5", "점수", "0.10", "형태 왜곡 (구 E6)"],
    ], [14 * mm, 18 * mm, 14 * mm, 124 * mm]))

    story.append(_p("2. 평가지표 (E1–E6)", styles["h"]))
    story.append(_table([
        ["ID", "문항 (채점에 그대로 사용)", "통과", "w", "역할"],
        ["E1", "입술 색이 윤곽 안에만 있고, 밖으로 번지거나 끊긴 경계 없이 윤곽을 따르는가?\n(피부·이·수염 이탈 + 번짐/가위질 경계)",
         "예", "0.22", "게이트"],
        ["E2", "화면에 적힌 제형(매트/새틴/글로시)과 광택 정도가 맞는가?",
         "예", "0.16", "점수"],
        ["E3", "입술 표면이 피부·립 텍스처처럼 보이고, 플라스틱·페인트처럼 보이지 않는가?",
         "예", "0.16", "점수"],
        ["E4", "입술의 밝은 곳·하이라이트 방향이 얼굴 조명 방향과 같은가?",
         "예", "0.14", "점수"],
        ["E5", "입술·입 주변 형태가 일그러지지 않았는가?",
         "예", "0.10", "점수"],
        ["E6", "합성 아티팩트가 눈에 띄지 않는가?\n(떠 있는 색, 이중 테두리, 얼룩, AI/필터 티)",
         "예", "0.22", "게이트"],
    ], [12 * mm, 92 * mm, 12 * mm, 14 * mm, 20 * mm]))

    story.append(PageBreak())
    story.append(_p("3. 레퍼런스에 있던 표현 → 우리가 만든 문항", styles["h"]))
    story.append(_p(
        "왼쪽은 출처에 가깝게 요약한 <b>원 표현/축</b>, 오른쪽은 <b>재작성한 E문항</b>이다.",
        styles["body"],
    ))
    story.append(_table([
        ["레퍼런스 (원 축·표현 요약)", "유형", "우리 문항"],
        ["Banuba Edge precision (no smear) + spatial placement",
         "SDK 루브릭", "E1 경계·배치\n(구 E1+E2 통합)"],
        ["Banuba: Texture truth — matte/satin/glossy distinct",
         "SDK 루브릭", "E2 제형·광택"],
        ["Banuba: Skin-tone honesty",
         "SDK 루브릭", "채택 안 함 → ΔE"],
        ["FFHQ-Makeup: texture, color, spatial placement",
         "데이터셋", "texture→E3\nplacement→E1\ncolor→ΔE"],
        ["FFHQ-Makeup: Facial consistency",
         "데이터셋", "E5 형태\n(E8 제외)"],
        ["LipAT: finish / specular",
         "립 VTO", "E2 finish\nE4 하이라이트"],
        ["Q-REAL: material/lighting/distortion yes-no",
         "AIGC", "E3·E4·E6"],
        ["Makeup transfer Likert: identity / artifacts",
         "사람", "E5·E6"],
        ["VTONQA fit / compatibility",
         "VTON", "fit≈E1\ncompat≈E5"],
        ["ModiFace placement / lighting",
         "업계", "E1·E4"],
    ], [72 * mm, 22 * mm, 76 * mm]))

    story.append(PageBreak())
    story.append(_p("4. 문항별 상세 (레퍼 → 재작성 이유)", styles["h"]))

    details = [
        ("E1 경계·배치 (구 E1+E2 통합)",
         "원 표현: Banuba Edge precision·no smear; FFHQ-Makeup spatial placement; ModiFace 잘못된 배치.",
         "재작성: 영역 이탈과 윤곽 번짐/가위질을 한 문항으로. 사람·Astra에서 구 E1·E2가 비슷하고 일치가 낮아 통합."),
        ("E2 제형·광택 (구 E3)",
         "원 표현: Banuba Texture truth; LipAT finish/roughness.",
         "재작성: 제형 문자열 + 광택 일치. 제형 없으면 해당없음."),
        ("E3 재질·텍스처 (구 E4)",
         "원 표현: FFHQ-Makeup texture; Q-REAL material/texture.",
         "재작성: 피부·립 텍스처 vs 플라스틱·페인트."),
        ("E4 조명·하이라이트 (구 E5)",
         "원 표현: Q-REAL lighting; ModiFace; LipAT specular.",
         "재작성: 입술 밝은 쪽 = 얼굴 조명 방향."),
        ("E5 형태 보존 (구 E6)",
         "원 표현: Identity consistency; Facial consistency; VTONQA compatibility.",
         "재작성: 입술·입 주변 왜곡만. E8 제외."),
        ("E6 아티팩트 (구 E7)",
         "원 표현: Image quality / artifacts; Q-REAL distortion·AI look.",
         "재작성: 떠 있는 색, 이중 테두리, 얼룩, 필터 티."),
    ]
    for title, src, ours in details:
        story.append(_p(title, styles["h2"]))
        story.append(_p(src, styles["body"]))
        story.append(_p(ours, styles["body"]))

    story.append(_p("5. 의도적으로 넣지 않은 것", styles["h"]))
    story.append(_table([
        ["레퍼에 있는 축", "처리", "이유"],
        ["Skin-tone / shade honesty (Banuba 등)", "제외", "ΔE·트랙 B (AR_SPEC)"],
        ["Makeup similarity to reference face (transfer)", "제외", "제품 try-on엔 참고 얼굴 없음 → E3만"],
        ["1–5 Overall naturalness Likert", "제외", "이번 파이프라인은 예/아니오"],
        ["E8 bare–AR consistency", "제외", "요청에 따라 이번 버전에서 뺌"],
        ["기존 R5 25체크 문장", "비사용", "안 B는 외부 축 기반 별도 셋"],
    ], [58 * mm, 28 * mm, 84 * mm]))

    story.append(_p("6. 다음 단계 (이 문서 이후)", styles["h"]))
    story.append(_p(
        "① 이 기준으로 채점용 이미지 세트 준비 → ② 사람 평가(정답) → "
        "③ 같은 문항으로 Astra 평가 → ④ 문항·게이트 일치율 확인 → "
        "⑤ 충분하면 이 채점표·프롬프트를 Astra 평가 절차로 고정.",
        styles["body"],
    ))

    story.append(Spacer(1, 3 * mm))
    story.append(_p("7. 출처 목록", styles["h"]))
    story.append(_p(
        "· Banuba: Makeup-fidelity rubric / What Makes AR Cosmetics Look Real? (블로그)<br/>"
        "· FFHQ-Makeup: arXiv:2508.03241<br/>"
        "· LipAT: Silva et al., WACV 2024<br/>"
        "· Q-REAL: arXiv:2511.16908<br/>"
        "· Makeup transfer human rubric: arXiv:2606.31089<br/>"
        "· VTONQA: arXiv:2601.02945<br/>"
        "· ModiFace realism/placement: WWD 인터뷰·제품 소개<br/>"
        "· 기계 판독: research/lip_rubric/criteria_vlm_ext_b_v1.json (v1.2.1, 가중 리밸런스)",
        styles["foot"],
    ))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT2.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=11 * mm, bottomMargin=11 * mm,
        title="VISHUE AR VLM naturalness ext-B v1.2.1",
        author="VISHUE",
    )
    doc.build(story)
    shutil.copyfile(OUT, OUT2)
    return OUT


if __name__ == "__main__":
    print(build())
