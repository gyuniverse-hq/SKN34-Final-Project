"""Export the twelve six-panel comparison frames to a private PDF appendix."""
from pathlib import Path

import cv2
import pymupdf
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research/data/ar_model_compare/video-input"
VIDEO = DATA / "comparison-five-models.mp4"
OUT = DATA / "모델별_영상_12장면_비교.pdf"
pdfmetrics.registerFont(TTFont("Malgun", "C:/Windows/Fonts/malgun.ttf"))
pdfmetrics.registerFont(TTFont("MalgunBold", "C:/Windows/Fonts/malgunbd.ttf"))
NAVY = colors.HexColor("#17253d")
MUTED = colors.HexColor("#64748b")
TITLE = ParagraphStyle("title", fontName="MalgunBold", fontSize=15, leading=22, textColor=NAVY)
BODY = ParagraphStyle("body", fontName="Malgun", fontSize=8.5, leading=14, textColor=MUTED, wordWrap="CJK")


def footer(canvas, doc):
    canvas.setFont("Malgun", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(20*mm, 11*mm, "VISHUE · 동일 색상 · 연구용 예비 비교")
    canvas.drawRightString(190*mm, 11*mm, str(doc.page))


def main():
    frames_dir = DATA / "report-12-frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(VIDEO))
    if not cap.isOpened() or round(cap.get(cv2.CAP_PROP_FRAME_COUNT)) != 12:
        raise ValueError("Expected a 12-frame comparison video")
    pages = []
    try:
        for i in range(12):
            ok, frame = cap.read()
            if not ok:
                raise ValueError(f"Could not decode frame {i}")
            path = frames_dir / f"{i:02d}.png"
            if not cv2.imwrite(str(path), frame):
                raise OSError(f"Could not write frame {i}")
            if i:
                pages.append(PageBreak())
            pages.extend([
                Paragraph(f"영상 장면 {i + 1:02d} / 12 · {i}초", TITLE),
                Paragraph("원본과 5가지 방식 · 같은 립 색상과 렌더러 설정", BODY),
                Spacer(1, 3*mm),
                Image(str(path), width=155*mm, height=155*mm*1352/1080, hAlign="CENTER"),
                Spacer(1, 3*mm),
                Paragraph("1초 간격의 예비 비교입니다. 다섯 결과의 얼굴 메시·추적에는 MediaPipe를 사용하며, "
                          "모델별 추적이 완전히 같은 상태로 고정된 것은 아닙니다. SAM 2는 MediaPipe 힌트와 결합한 결과입니다.", BODY),
            ])
    finally:
        cap.release()
    tmp = DATA / "frame_appendix_base.pdf"
    doc = SimpleDocTemplate(str(tmp), pagesize=A4, leftMargin=20*mm, rightMargin=20*mm,
                            topMargin=17*mm, bottomMargin=22*mm,
                            title="영상 12장면 모델 비교", author="VISHUE")
    doc.build(pages, onFirstPage=footer, onLaterPages=footer)
    with pymupdf.open(str(tmp)) as pdf:
        pdf.embfile_add("video_comparison_5models.mp4", VIDEO.read_bytes(),
                        filename="video_comparison_5models.mp4", desc="5가지 방식 비교 영상 · 1fps 예비 실험")
        pdf.save(str(OUT), deflate=True)
    print(OUT)


if __name__ == "__main__":
    main()
