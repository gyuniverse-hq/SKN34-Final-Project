"""Build the five-page Korean lip AR evaluation brief from the November 20 reports.

Run from the repository root: python research/lip_rubric/export_eval_flow_3docs_pdf.py
Requires ReportLab, PyMuPDF, and Windows Malgun Gothic.
"""

from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

import pymupdf
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle


ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
REFS = "lip_eval_external_refs_1p_20261120.pdf"
TECH = "VISHUE_AR_technical_metrics_v1.1_20261120.pdf"
EXTB = "VISHUE_AR_vlm_naturalness_extB_v1.2.1_20261120.pdf"
MENTOR = "VISHUE_AR_mentor_likert_v1_20261120.pdf"
OUTPUT = REPORTS / "VISHUE_AR_eval_flow_3docs_20261120.pdf"

PAGE_W, PAGE_H = A4
MARGIN = 44
WIDTH = PAGE_W - 2 * MARGIN
INK = colors.HexColor("#182931")
SLATE = colors.HexColor("#31454F")
MUTED = colors.HexColor("#4C606A")
LINE = colors.HexColor("#D8E1E4")
PAPER = colors.HexColor("#F5F7F8")
WHITE = colors.white
TEAL = colors.HexColor("#17695F")
TEAL_BG = colors.HexColor("#E8F3F0")
GATE = colors.HexColor("#973B2E")
GATE_BG = colors.HexColor("#F8EAE7")


def paragraph(text, size=10, leading=15, *, bold=False, color=INK):
    style = ParagraphStyle(
        "ko",
        fontName="MalgunBold" if bold else "Malgun",
        fontSize=size,
        leading=leading,
        textColor=color,
        wordWrap="CJK",
    )
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


class Page:
    def __init__(self, pdf, number, label):
        self.pdf = pdf
        self.rect(0, 0, PAGE_W, PAGE_H, WHITE)
        self.text("VISHUE  /  립 AR 평가", MARGIN, 31, 9, bold=True, color=TEAL)
        self.text("2026.11.20", PAGE_W - 103, 31, 9, color=MUTED)
        self.rule(54)
        self.rule(780)
        self.text(label, MARGIN, 800, 8.5, color=MUTED)
        self.text(f"{number:02d} / 05", PAGE_W - 88, 800, 8.5, bold=True, color=TEAL)

    def rect(self, x, y, w, h, color):
        self.pdf.setFillColor(color)
        self.pdf.rect(x, PAGE_H - y - h, w, h, fill=1, stroke=0)

    def rule(self, y):
        self.pdf.setStrokeColor(LINE)
        self.pdf.setLineWidth(0.65)
        self.pdf.line(MARGIN, PAGE_H - y, PAGE_W - MARGIN, PAGE_H - y)

    def text(self, text, x, y, size=10, *, bold=False, color=INK):
        self.pdf.setFillColor(color)
        self.pdf.setFont("MalgunBold" if bold else "Malgun", size)
        self.pdf.drawString(x, PAGE_H - y, text)

    def block(self, text, y, *, x=MARGIN, w=WIDTH, size=10, leading=15, bold=False, color=INK):
        content = paragraph(text, size, leading, bold=bold, color=color)
        _, h = content.wrap(w, PAGE_H)
        if y + h > 780:
            raise ValueError(f"Text exceeds the content area: {text[:40]}")
        content.drawOn(self.pdf, x, PAGE_H - y - h)
        return y + h

    def section(self, label, title, summary):
        self.text(label, MARGIN, 87, 10, bold=True, color=TEAL)
        self.text(title, MARGIN, 124, 26, bold=True)
        return self.block(summary, 146, size=11, leading=17)

    def table(self, y, widths, rows, *, gates=()):
        data = [
            [
                paragraph(str(cell), 9, 13, bold=(ri == 0 or ci == 0),
                          color=WHITE if ri == 0 else GATE if ri in gates and ci in (0, 2) else INK)
                for ci, cell in enumerate(row)
            ]
            for ri, row in enumerate(rows)
        ]
        table = Table(data, colWidths=[WIDTH * frac for frac in widths])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), SLATE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAPER, WHITE]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LINEBELOW", (0, -1), (-1, -1), 0.65, LINE),
            *[("BACKGROUND", (0, row), (-1, row), GATE_BG) for row in gates],
        ]))
        _, h = table.wrap(WIDTH, PAGE_H)
        if y + h > 748:
            raise ValueError("Table exceeds the content area")
        table.drawOn(self.pdf, MARGIN, PAGE_H - y - h)
        return y + h

    def note(self, y, h, title, text, *, gate=False):
        color = GATE if gate else TEAL
        self.rect(MARGIN, y, WIDTH, h, GATE_BG if gate else TEAL_BG)
        self.rect(MARGIN, y, 3, h, color)
        self.text(title, MARGIN + 13, y + 19, 10, bold=True, color=color)
        end = self.block(text, y + 26, x=MARGIN + 13, w=WIDTH - 26, size=9, leading=13)
        if end > y + h - 5:
            raise ValueError(f"Note exceeds its box: {title}")

    def source(self, filename, pages=""):
        self.text(f"원본  /  reports/{filename}{pages}", MARGIN, 764, 8, color=MUTED)

    def arrow(self, x1, x2, y):
        self.pdf.setStrokeColor(TEAL)
        self.pdf.setLineWidth(1.15)
        yy = PAGE_H - y
        self.pdf.line(x1, yy, x2, yy)
        self.pdf.line(x2 - 4, yy + 3, x2, yy)
        self.pdf.line(x2 - 4, yy - 3, x2, yy)


def overview(pdf):
    p = Page(pdf, 1, "전체 지도")
    p.text("립 AR 평가지표", MARGIN, 132, 38, bold=True)
    p.text("레퍼 확인 → 기술 → 자연스러움", MARGIN, 174, 25, bold=True, color=TEAL)
    p.block("참고할 평가 축을 고르고, 실물과의 차이는 수치로 재고, 실제로 바른 듯 보이는지는 문항으로 확인한다.",
            201, w=460, size=12, leading=19)

    gap = 17
    step_w = (WIDTH - 2 * gap) / 3
    steps = [
        ("1  레퍼런스 조사", "공개 사례에서 공통 평가 축을 골랐다.", REFS),
        ("2  테크니컬 지표", "입술색·모양의 차이를 숫자로 잰다.", TECH.replace("_20261120", "\n_20261120")),
        ("3  자연스러움 Ext-B", "보이는 결함을 6개 문항으로 확인한다.", EXTB.replace("_20261120", "\n_20261120")),
    ]
    for i, (title, line, filename) in enumerate(steps):
        x = MARGIN + i * (step_w + gap)
        p.rect(x, 281, step_w, 107, PAPER)
        p.rect(x, 281, step_w, 3, TEAL)
        p.text(title, x + 9, 305, 12, bold=True)
        p.text(line, x + 9, 328, 8.4)
        p.block(filename, 342, x=x + 9, w=step_w - 18, size=7.6, leading=11, color=MUTED)
        if i < 2:
            p.arrow(x + step_w + 2, x + step_w + gap - 2, 304)

    p.rect(MARGIN, 429, WIDTH, 100, TEAL_BG)
    p.text("두 질문, 두 트랙", MARGIN + 14, 451, 11, bold=True, color=TEAL)
    p.text("트랙 A   보이는 자연스러움", MARGIN + 14, 477, 11, bold=True)
    p.text("사람·VLM이 바른 것처럼 보이는지 평가", MARGIN + 211, 477, 10)
    p.text("트랙 B   색·구조 숫자", MARGIN + 14, 505, 11, bold=True)
    p.text("ΔE 등으로 실물 기준과의 차이를 측정", MARGIN + 211, 505, 10)

    p.text("이 PDF가 답하는 질문", MARGIN, 584, 17, bold=True)
    for i, question in enumerate((
        "① 남들은 뭘로 평가하나?",
        "② 숫자로 뭘 재나?",
        "③ 자연스러움은 어떤 문항으로 채점하나?",
    )):
        p.text(question, MARGIN + 1, 620 + i * 36, 13)
    p.text("원본 위치  /  C:/final_project/reports/", MARGIN, 764, 8, color=MUTED)
    pdf.showPage()


def references(pdf):
    p = Page(pdf, 2, "1단계  /  레퍼런스 조사")
    y = p.section("1단계", "레퍼런스에서 무엇을 가져왔나",
                  "논문과 업계 사례를 비교해 반복되는 평가 축을 골랐다. 상용 서비스의 공개 설명과 학술 논문의 측정 기준은 공개 수준이 다르다.")
    y = p.table(y + 24, (0.27, 0.36, 0.37), [
        ("출처", "반복되는 축", "우리가 쓰는 곳"),
        ("LipAT (WACV 2024)", "립 영역 구조·픽셀 오차, 립 패치 사실감", "기술  SSIM·MAE\n보류  Patch-FID는 표본 확보 뒤"),
        ("파운데이션 VTO\n(arXiv:2507.07333)", "실제 도포 전후의 색·구조·지각 차이", "기술  ΔE·SSIM·LPIPS"),
        ("메이크업 전이 사람 평가", "자연스러움 1–5 또는 A/B 비교, 합성 흔적", "자연스러움  사람 판단을 비교 기준으로 사용"),
        ("VTON-IQA·Taobao-Tryon\n(의류 가상피팅)", "정답 이미지 없이 보이는 품질을 판단", "자연스러움  VLM 평가 방식 참고"),
        ("Banuba·ModiFace\n(Ext-B 원본의 업계 사례)", "배치·윤곽, 제형·광택, 조명", "자연스러움  경계·질감 문항 작성\n기술  피부톤·색 재현은 ΔE 축"),
        ("Perfect Corp·ModiFace\n(상용 사례)", "색·질감·마감 설명, 공개 채점 기준은 제한적", "보류  상용사 합격표·가중 수치"),
    ])
    p.text("가져온 것", MARGIN, y + 32, 12, bold=True, color=TEAL)
    p.block("색·구조의 수치 측정과 사람이 보는 자연스러움. 외부 축을 입술에 맞는 짧은 문항으로 다시 썼다.",
            y + 41, w=WIDTH, size=10, leading=15)
    p.text("안 가져온 것", MARGIN, y + 85, 12, bold=True, color=TEAL)
    p.block("기존 내부 25체크를 본문항으로 옮기는 방식과 표본이 충분해야 해석할 수 있는 전체 FID. 피부톤·색 재현은 ΔE로 넘겼다.",
            y + 94, w=WIDTH, size=10, leading=15)
    p.note(y + 143, 52, "문항과 축은 레퍼런스에서", "Ext-B의 구체적인 가중 숫자는 대응하는 공개표가 없어 팀 초안으로 정했다.")
    p.source(REFS)
    pdf.showPage()


def representative_ssim_crop():
    # The SSIM ladder occupies the second image row on page 2. Its second tile is the 0.95 team anchor.
    with pymupdf.open(REPORTS / TECH) as source:
        tiles = sorted(source[1].get_image_info(xrefs=True),
                       key=lambda tile: (round(tile["bbox"][1], 1), tile["bbox"][0]))
        if len(tiles) != 10:
            raise ValueError("The source SSIM ladder layout changed")
        tile = tiles[6]
        if not (275 < tile["bbox"][1] < 277 and 170 < tile["bbox"][0] < 171):
            raise ValueError("The source SSIM ladder layout changed")
        return ImageReader(BytesIO(source.extract_image(tile["xref"])["image"]))


def technical(pdf):
    p = Page(pdf, 3, "2단계  /  트랙 B")
    y = p.section("2단계  ·  트랙 B", "색과 구조를 숫자로 잰다",
                  "같은 사람의 맨입술·AR·실제 도포를 맞춰 입술 영역(ROI)만 비교한다. 구조·픽셀 지표는 같은 조건의 합성 정답으로도 잴 수 있다.")
    y = p.table(y + 19, (0.17, 0.38, 0.45), [
        ("지표", "쉽게 말하면", "v1.1 판정과 팀 눈 목표"),
        ("ΔE CIE2000 ↓", "AR 입술과 실제로 바른 입술의 색이 눈에 얼마나 다르게 보이는지 잰다.",
         "중앙값 ≤1.8 및 상대 15/20.\n1.8은 치과 색 허용 역치에서 빌린 기준."),
        ("SSIM ↑", "두 사진의 입술 모양과 밝고 어두운 무늬가 얼마나 닮았는지 본다.",
         "상대 15/20. 절대값은 기록만.\n팀 눈 목표 ≥0.95."),
        ("MAE ↓", "같은 자리에 있는 픽셀끼리 얼마나 다른지 평균을 낸다.",
         "상대 15/20. 절대값은 기록만.\n팀 눈 목표 ≤0.04 (RGB 0–1), MSE도 기록."),
        ("mIoU ↑", "그려진 입술 영역이 정답 영역과 얼마나 겹치는지 본다.",
         "공개 비교선 ≥0.797 (SegFace LaPa).\n팀 눈 목표 ≥0.85."),
        ("LPIPS ↓", "입술 사진이 사람 눈에 얼마나 다르게 느껴질지 특징으로 비교한다.",
         "상대 15/20. 절대값은 기록만.\n팀 눈 앵커 미선택."),
    ])
    y += 15
    y = p.block("상대 15/20은 AR이 맨입술보다 실물에 가까운 사례가 20쌍 중 15쌍 이상이라는 뜻이다. "
                "입 주변 맨피부의 ΔE 중앙값이 1.8 이상이면 절대 색 판정은 보류한다.",
                y, size=9, leading=13)
    figure_y = y + 18
    p.pdf.drawImage(representative_ssim_crop(), MARGIN, PAGE_H - figure_y - 91, 91, 91)
    figure_text_x = MARGIN + 107
    p.text("SSIM 사다리와 눈 앵커", figure_text_x, figure_y + 14, 12, bold=True, color=TEAL)
    p.block("숫자만 보면 어느 정도가 눈에 괜찮은지 알기 어렵다. 점수대별 예시를 나란히 보고 팀이 목표 칸을 골랐다.",
            figure_y + 23, x=figure_text_x, w=WIDTH - 107, size=9, leading=13)
    for i, (value, label) in enumerate((
        ("0.66", "현재 AR 중앙값"), ("0.80", ""), ("0.90", ""),
        ("0.95", "팀 눈 목표"), ("0.98", ""),
    )):
        x = figure_text_x + 77 * i
        p.rect(x, figure_y + 53, 70, 20, TEAL_BG if i == 3 else PAPER)
        p.text(value, x + 8, figure_y + 67, 9, bold=True, color=TEAL if i == 3 else INK)
        if label:
            p.text(label, x, figure_y + 86, 8, color=TEAL if i == 3 else MUTED)
    p.text("SSIM 0.95 예시 · 실립(왼쪽) / 변형(오른쪽)", MARGIN, figure_y + 105, 8, color=MUTED)
    p.note(figure_y + 126, 53, "색이 실물과 비슷한가?  →  실제로 바른 듯 보이나?",
           "여기서는 색과 구조를 재고, 다음 장에서는 경계·표면·조명을 눈으로 판정한다.")
    p.source(TECH, "  pp. 1–4")
    pdf.showPage()


def naturalness(pdf):
    p = Page(pdf, 4, "3단계  /  트랙 A")
    y = p.section("3단계  ·  트랙 A", "바른 듯 보이는지 채점한다",
                  "Ext-B v1.2.1은 보이는 자연스러움을 여섯 문항으로 확인한다. 사람과 Astra(VLM, 사진을 보고 판단하는 모델)에 같은 질문을 준다.")
    y = p.table(y + 19, (0.09, 0.67, 0.13, 0.11), [
        ("ID", "한 줄 질문 · 통과 답은 모두 ‘예’", "역할", "가중 w"),
        ("E1", "색이 입술 윤곽에 맞고, 피부·치아·수염으로의 번짐이나 끊긴 경계가 없는가?", "게이트", "0.22"),
        ("E2", "제형(매트·새틴·글로시)과 보이는 광택이 맞는가?", "점수", "0.16"),
        ("E3", "표면에 실제 입술 결이 보이고 플라스틱·페인트처럼 보이지 않는가?", "점수", "0.16"),
        ("E4", "입술의 밝은 부분과 하이라이트가 얼굴 조명 방향과 맞는가?", "점수", "0.14"),
        ("E5", "입술과 입 주변의 형태가 일그러지지 않았는가?", "점수", "0.10"),
        ("E6", "떠 있는 색·이중선·얼룩 같은 합성 흔적이 보이지 않는가?", "게이트", "0.22"),
    ], gates=(1, 6))
    p.note(y + 12, 59, "E1·E6 중 하나라도 실패하면 전체 fail",
           "가중 점수는 별도 기록한다. 통과한 문항의 가중 합을 적용 문항의 가중 합으로 나눈다. "
           "제형 미표기 시 E2만 해당 없음으로 빼고 다시 계산한다.", gate=True)
    y = p.block("입술 crop(잘라낸 이미지)과 가능하면 얼굴 전체, 제형을 제공한다. "
                "kind(스티커·렌더·실물)는 숨긴다. 색 일치(ΔE), 1–5 총평, E8은 제외한다.",
                y + 82, size=9, leading=13)
    y = p.block("구 E1(배치)·E2(번짐)는 판단이 겹치고 사람–Astra 일치가 낮아 E1으로 통합했다.",
                y + 8, size=9, leading=13)
    p.text("레퍼런스 축을 문항으로 옮긴 예", MARGIN, y + 20, 11, bold=True, color=TEAL)
    p.table(y + 29, (0.64, 0.36), [
        ("외부 레퍼런스 축", "Ext-B 문항"),
        ("Banuba edge·placement / texture truth", "E1 경계 / E2 제형"),
        ("FFHQ-Makeup texture·facial consistency", "E3 표면 / E5 형태"),
        ("LipAT specular·Q-REAL lighting / makeup transfer artifacts", "E4 조명 / E6 합성 흔적"),
    ])
    p.source(EXTB, "  pp. 1–3")
    pdf.showPage()


def next_steps(pdf):
    p = Page(pdf, 5, "세 문서의 연결  /  다음 단계")
    p.section("정리", "세 문서가 이어지는 순서",
              "레퍼로 축을 고름 → 기술로 색과 구조를 숫자로 봄 → Ext-B로 자연스러움을 예·아니오로 채점.")
    p.text("지금 해석할 수 있는 범위", MARGIN, 223, 15, bold=True)
    p.note(244, 64, "Ext-B 가중치는 팀 초안",
           "외부 레퍼런스는 문항을 고르는 근거다. 여섯 문항의 가중치는 팀이 정했다. Astra 위임은 사람과 문항별·게이트 판정이 충분히 일치할 때 가능하다.")
    p.text("다음 산출물", MARGIN, 363, 15, bold=True)
    p.block("멘토가 요청한 최종 형식은 2~3개 축의 1–5점 평가다. 후속 Mentor Likert 초안은 영역 정확도·자연스러움·이미지 일관성의 세 축을 사용한다.",
            379, size=11, leading=18)
    p.text("다음에 할 일", MARGIN, 465, 15, bold=True)
    for i, line in enumerate((
        "소수의 사람이 같은 이미지 묶음을 채점한다.",
        "Astra에 같은 이미지와 같은 문항을 준다.",
        "사람–Astra 일치를 확인한 뒤 충분하면 위임한다.",
    )):
        y = 491 + 45 * i
        p.rect(MARGIN, y, WIDTH, 35, PAPER)
        p.pdf.setStrokeColor(TEAL)
        p.pdf.setLineWidth(0.9)
        p.pdf.rect(MARGIN + 13, PAGE_H - y - 22, 9, 9, fill=0, stroke=1)
        p.text(line, MARGIN + 33, y + 22, 11)
    p.source(MENTOR, "  pp. 1–2 · 다음 단계 참고")
    pdf.showPage()


def main():
    fonts = Path("C:/Windows/Fonts")
    pdfmetrics.registerFont(TTFont("Malgun", str(fonts / "malgun.ttf")))
    pdfmetrics.registerFont(TTFont("MalgunBold", str(fonts / "malgunbd.ttf")))
    pdf = canvas.Canvas(str(OUTPUT), pagesize=A4, pageCompression=1)
    pdf.setTitle("립 AR 평가지표 — 레퍼 확인 → 기술 → 자연스러움")
    pdf.setAuthor("VISHUE")
    overview(pdf)
    references(pdf)
    technical(pdf)
    naturalness(pdf)
    next_steps(pdf)
    pdf.save()
    print(OUTPUT)


if __name__ == "__main__":
    main()

