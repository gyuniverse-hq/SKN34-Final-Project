"""Create the 10-image model comparison PDF from the checked experiment summary."""
import csv
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "reports/AR_lip_model_comparison_10.pdf"
pdfmetrics.registerFont(TTFont("Malgun", "C:/Windows/Fonts/malgun.ttf"))
pdfmetrics.registerFont(TTFont("MalgunBold", "C:/Windows/Fonts/malgunbd.ttf"))
NAVY = colors.HexColor("#17253d")
MUTED = colors.HexColor("#66738a")
TEAL = colors.HexColor("#168c88")
PALE = colors.HexColor("#eff8f6")
LINE = colors.HexColor("#dce4ed")

styles = {
    "eyebrow": ParagraphStyle("eyebrow", fontName="MalgunBold", fontSize=9, leading=13, textColor=TEAL),
    "title": ParagraphStyle("title", fontName="MalgunBold", fontSize=23, leading=32, textColor=NAVY, wordWrap="CJK"),
    "subtitle": ParagraphStyle("subtitle", fontName="Malgun", fontSize=10, leading=17, textColor=MUTED, wordWrap="CJK"),
    "h": ParagraphStyle("h", fontName="MalgunBold", fontSize=13, leading=20, textColor=NAVY, spaceBefore=6, spaceAfter=8, wordWrap="CJK"),
    "body": ParagraphStyle("body", fontName="Malgun", fontSize=9.1, leading=16, textColor=NAVY, wordWrap="CJK"),
    "small": ParagraphStyle("small", fontName="Malgun", fontSize=8, leading=13, textColor=MUTED, wordWrap="CJK"),
    "table_head": ParagraphStyle("table_head", fontName="MalgunBold", fontSize=8, leading=12, textColor=colors.white, alignment=TA_CENTER, wordWrap="CJK"),
    "table_cell": ParagraphStyle("table_cell", fontName="Malgun", fontSize=8.2, leading=13, textColor=NAVY, alignment=TA_CENTER, wordWrap="CJK"),
    "table_left": ParagraphStyle("table_left", fontName="Malgun", fontSize=8.2, leading=13, textColor=NAVY, alignment=TA_LEFT, wordWrap="CJK"),
}


def para(text, style="body"):
    return Paragraph(text, styles[style])


def footer(canvas, doc):
    canvas.setStrokeColor(LINE)
    canvas.line(20 * mm, 17 * mm, 190 * mm, 17 * mm)
    canvas.setFont("Malgun", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(20 * mm, 11 * mm, "VISHUE  |  AR 모델 비교 · 예비 실험")
    canvas.drawRightString(190 * mm, 11 * mm, str(doc.page))


def chart():
    data = [("FaRL LaPa", .844), ("FaRL CelebM", .675), ("MediaPipe 윤곽", .668),
            ("BiSeNet R18", .667), ("SegFormer", .630), ("MediaPipe + SAM 2", .347)]
    d = Drawing(170 * mm, 63 * mm)
    x0, width = 49 * mm, 99 * mm
    for i, (name, value) in enumerate(data):
        y = (56 - i * 9) * mm
        d.add(String(0, y + 1 * mm, name, fontName="Malgun", fontSize=8.7, fillColor=NAVY))
        d.add(Rect(x0, y, width, 4.4 * mm, fillColor=colors.HexColor("#e9eef3"), strokeColor=None))
        d.add(Rect(x0, y, width * value, 4.4 * mm, fillColor=TEAL if i == 0 else colors.HexColor("#91a7bd"), strokeColor=None))
        d.add(String(x0 + width + 3 * mm, y + 0.7 * mm, f"{value:.3f}", fontName="MalgunBold", fontSize=9, fillColor=NAVY))
    return d


def photo_page(photo_ids, title):
    cells = []
    for number, photo_id in photo_ids:
        image_path = ROOT / "research/data/LaPa/test/images" / f"{photo_id}.jpg"
        if not image_path.is_file():
            raise FileNotFoundError(image_path)
        width, height = ImageReader(str(image_path)).getSize()
        scale = min(72 * mm / width, 55 * mm / height)
        photo = Image(str(image_path), width=width * scale, height=height * scale)
        photo.hAlign = "CENTER"
        cells.append([photo, Spacer(1, 2*mm), para(f"{number:02d}  ·  {photo_id}", "small")])
    if len(cells) % 2:
        cells.append("")
    rows = [[cells[i], cells[i + 1]] for i in range(0, len(cells), 2)]
    gallery = Table(rows, colWidths=[85*mm, 85*mm])
    gallery.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP"),
                                  ("ALIGN", (0,0), (-1,-1), "CENTER"),
                                  ("TOPPADDING", (0,0), (-1,-1), 5),
                                  ("BOTTOMPADDING", (0,0), (-1,-1), 9)]))
    return [PageBreak(), para(title, "h"),
            para("모델별 결과 파일의 사진 ID와 일치하는 LaPa test 원본 사진입니다.", "small"),
            Spacer(1, 3*mm), gallery,
            para("사진 출처: LaPa Dataset · 비상업적 연구 및 교육 목적의 자료", "small")]


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(OUTPUT), pagesize=A4, leftMargin=20*mm, rightMargin=20*mm,
                            topMargin=17*mm, bottomMargin=22*mm, title="LaPa 입술 모델 비교 — 10장 예비 결과", author="VISHUE")
    story = [para("VISHUE  /  RESEARCH NOTE", "eyebrow"), Spacer(1, 3*mm),
             para("입술 영역 모델 비교", "title"),
             para("LaPa 정답 마스크 기반 · 10장 예비 실험", "subtitle"), Spacer(1, 7*mm)]
    meta = Table([[para("평가 데이터", "small"), para("측정 환경", "small"), para("평가 기준", "small")],
                  [para("LaPa test 10장", "body"), para("RunPod · RTX 4090", "body"), para("이미지별 IoU 중앙값", "body")]], colWidths=[56*mm, 58*mm, 56*mm])
    meta.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#f4f7fa")), ("TOPPADDING", (0,0), (-1,0), 9), ("BOTTOMPADDING", (0,-1), (-1,-1), 10), ("LEFTPADDING", (0,0), (-1,-1), 10)]))
    story += [meta, Spacer(1, 7*mm), para("01  입술 영역 일치도", "h"),
              para("여섯 방식이 동일한 10장의 사진과 정답을 사용했습니다. 값이 높을수록 정답 입술 영역과 더 많이 겹칩니다.", "body"), Spacer(1, 3*mm), chart(), Spacer(1, 3*mm)]
    callout = Table([[para("관찰", "eyebrow"), para("FaRL LaPa가 이 표본에서 가장 높았지만, 같은 출처의 데이터로 학습한 모델입니다. 10장 결과만으로 최종 우열을 결정할 수 없습니다.", "body")]], colWidths=[22*mm, 148*mm])
    callout.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), PALE), ("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 10), ("RIGHTPADDING", (0,0), (-1,-1), 10), ("TOPPADDING", (0,0), (-1,-1), 10), ("BOTTOMPADDING", (0,0), (-1,-1), 10)]))
    story += [callout, PageBreak(), para("02  수치와 해석", "h")]
    raw = [("FaRL LaPa", "0.844", "7.3%", "8.2%"), ("FaRL CelebM", "0.675", "17.5%", "19.3%"), ("MediaPipe 윤곽", "0.668", "16.7%", "18.2%"), ("BiSeNet R18", "0.667", "24.2%", "13.3%"), ("SegFormer", "0.630", "20.3%", "14.6%"), ("MediaPipe + SAM 2", "0.347", "63.9%", "0.0%")]
    rows = [[para("방식", "table_head"), para("IoU", "table_head"), para("넘침", "table_head"), para("누락", "table_head")]] + [[para(r[0], "table_left")] + [para(v, "table_cell") for v in r[1:]] for r in raw]
    table = Table(rows, colWidths=[80*mm, 30*mm, 30*mm, 30*mm], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), NAVY), ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f5f8fb")]), ("LINEBELOW", (0,-1), (-1,-1), .6, LINE), ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("TOPPADDING", (0,0), (-1,-1), 7), ("BOTTOMPADDING", (0,0), (-1,-1), 7), ("LEFTPADDING", (0,0), (-1,-1), 8)]))
    story += [table, Spacer(1, 2*mm), para("넘침: 예측 면적 중 정답 밖의 비율. 누락: 정답 면적 중 예측하지 못한 비율. 각 수치는 사진별 값의 중앙값입니다. 예측이 없는 경우 넘침은 제외합니다.", "small"), Spacer(1, 3*mm)]
    sections = [
        ("결과를 볼 때", "MediaPipe·BiSeNet·FaRL CelebM은 이 소표본에서 비슷했습니다. SAM 2 조합은 입술을 놓치기보다 입술 밖을 넓게 포함하는 경향을 보였습니다. 다른 힌트 방식의 SAM 2 성능을 뜻하지는 않습니다."),
        ("비교의 한계", "파일명순 앞 10장이며 같은 사람의 사진이 포함될 수 있습니다. FaRL LaPa는 LaPa 학습 버전이고 CelebM과 얼굴 검출 입력 크기도 다릅니다. MediaPipe는 앱의 입술 윤곽을 정지 사진에 적용한 근사치입니다."),
        ("속도와 다음 확인", "실행 시간은 모델마다 얼굴 검출·전처리·전송 포함 범위가 달라 직접 순위를 매길 수 없습니다. RTX 4090 결과는 iPhone 성능이 아닙니다. 더 많은 동일 사진과 다른 출처 데이터, iPhone 실시간 화면을 확인해야 합니다."),
    ]
    for title, body in sections:
        story.append(KeepTogether([para(title, "h"), para(body, "body"), Spacer(1, 2*mm)]))
    story += [Spacer(1, 3*mm), para("출처: LaPa test 정답 마스크와 2026-11-09 RunPod 실험 CSV. 모델별 측정 조건과 사진별 수치는 원본 분석 문서 참조.", "small")]
    metrics = ROOT / "research/data/ar_model_compare/runpod-results-10/mediapipe/metrics.csv"
    with metrics.open(encoding="utf-8", newline="") as f:
        photo_ids = [row["id"] for row in csv.DictReader(f)]
    if len(photo_ids) != 10 or len(set(photo_ids)) != 10:
        raise ValueError("Expected exactly 10 unique evaluated photographs")
    enumerated = list(enumerate(photo_ids, start=1))
    story.extend(photo_page(enumerated[:6], "03  실험에 사용한 사진  1–6"))
    story.extend(photo_page(enumerated[6:], "04  실험에 사용한 사진  7–10"))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(OUTPUT)


if __name__ == "__main__":
    main()
