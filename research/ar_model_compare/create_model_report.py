"""Build a private PDF report from saved, verified model comparison results."""
import csv
import json
import statistics
from pathlib import Path

import pymupdf
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research/data/ar_model_compare"
STILL = DATA / "runpod-results-10"
VIDEO = DATA / "video-input"
OUT = DATA / "모델_비교_종합_예비보고서.pdf"
MOVIE = VIDEO / "comparison-five-models.mp4"

pdfmetrics.registerFont(TTFont("Malgun", "C:/Windows/Fonts/malgun.ttf"))
pdfmetrics.registerFont(TTFont("MalgunBold", "C:/Windows/Fonts/malgunbd.ttf"))
NAVY = colors.HexColor("#17253d")
MUTED = colors.HexColor("#64748b")
TEAL = colors.HexColor("#138b87")
PALE = colors.HexColor("#eff8f6")
LINE = colors.HexColor("#dce5ed")
AMBER = colors.HexColor("#8a5819")
STYLES = {
    "eyebrow": ParagraphStyle("eyebrow", fontName="MalgunBold", fontSize=9, leading=13, textColor=TEAL),
    "title": ParagraphStyle("title", fontName="MalgunBold", fontSize=23, leading=32, textColor=NAVY, wordWrap="CJK"),
    "h": ParagraphStyle("h", fontName="MalgunBold", fontSize=13, leading=19, textColor=NAVY, spaceBefore=4, spaceAfter=7, wordWrap="CJK"),
    "body": ParagraphStyle("body", fontName="Malgun", fontSize=9.1, leading=15.6, textColor=NAVY, wordWrap="CJK"),
    "small": ParagraphStyle("small", fontName="Malgun", fontSize=7.7, leading=12, textColor=MUTED, wordWrap="CJK"),
    "th": ParagraphStyle("th", fontName="MalgunBold", fontSize=7.6, leading=11, textColor=colors.white, alignment=TA_CENTER, wordWrap="CJK"),
    "tc": ParagraphStyle("tc", fontName="Malgun", fontSize=7.7, leading=12, textColor=NAVY, alignment=TA_CENTER, wordWrap="CJK"),
    "tl": ParagraphStyle("tl", fontName="Malgun", fontSize=8, leading=12, textColor=NAVY, wordWrap="CJK"),
}


def P(text, style="body"):
    return Paragraph(str(text), STYLES[style])


def rows_at(path):
    with path.open(encoding="utf8", newline="") as f:
        return list(csv.DictReader(f))


def table(rows, widths, compact=False):
    t = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    padding = 4 if compact else 6
    t.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), NAVY),
                           ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f3f7fa")]),
                           ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                           ("TOPPADDING", (0,0), (-1,-1), padding),
                           ("BOTTOMPADDING", (0,0), (-1,-1), padding),
                           ("LEFTPADDING", (0,0), (-1,-1), 5), ("RIGHTPADDING", (0,0), (-1,-1), 5),
                           ("LINEBELOW", (0,-1), (-1,-1), .5, LINE)]))
    return t


def img(path, max_width, max_height):
    w, h = ImageReader(str(path)).getSize()
    scale = min(max_width / w, max_height / h)
    photo = Image(str(path), width=w*scale, height=h*scale)
    photo.hAlign = "CENTER"
    return photo


def footer(c, doc):
    c.setStrokeColor(LINE)
    c.line(20*mm, 16*mm, 190*mm, 16*mm)
    c.setFont("Malgun", 7.5)
    c.setFillColor(MUTED)
    c.drawString(20*mm, 10*mm, "VISHUE  |  모델 비교 예비 실험 · 영상 및 사진 포함")
    c.drawRightString(190*mm, 10*mm, str(doc.page))


def still_data():
    order = [("farl-lapa", "FaRL LaPa"), ("farl-celebm", "FaRL CelebM"), ("mediapipe", "MediaPipe"),
             ("bisenet", "BiSeNet"), ("segformer", "SegFormer"), ("sam2", "SAM 2 + MediaPipe")]
    data = {}
    common = None
    for key, label in order:
        records = rows_at(STILL / key / "metrics.csv")
        data[key] = {r["id"]: r for r in records}
        ids = set(data[key])
        common = ids if common is None else common & ids
        if len(ids) != 10:
            raise ValueError(f"Unexpected still sample count: {key}")
    if len(common) != 10:
        raise ValueError("The still comparison must have 10 matching image IDs")
    return order, data, sorted(common)


def summary_table(order, data, ids):
    rows = [[P(x, "th") for x in ["입술 영역 방식", "IoU ↑", "넘침 ↓", "누락 ↓"]]]
    stats = []
    for key, label in order:
        records = [data[key][i] for i in ids]
        med = lambda col: statistics.median(float(r[col]) for r in records if r.get(col))
        iou, spill, miss = med("iou"), med("spill"), med("miss")
        stats.append((label, iou))
        rows.append([P(label, "tl"), P(f"{iou:.3f}", "tc"), P(f"{100*spill:.1f}%", "tc"), P(f"{100*miss:.1f}%", "tc")])
    return table(rows, [76*mm, 30*mm, 32*mm, 32*mm]), stats


def graph(stats):
    d = Drawing(170*mm, 60*mm)
    for i, (label, value) in enumerate(stats):
        y = (53 - i*9) * mm
        d.add(String(0, y+2, label, fontName="Malgun", fontSize=8, fillColor=NAVY))
        d.add(Rect(51*mm, y, 100*mm, 4*mm, fillColor=colors.HexColor("#e9eef3"), strokeColor=None))
        d.add(Rect(51*mm, y, 100*mm*value, 4*mm, fillColor=TEAL if i == 0 else colors.HexColor("#8fa5ba"), strokeColor=None))
        d.add(String(154*mm, y+2, f"{value:.3f}", fontName="MalgunBold", fontSize=8, fillColor=NAVY))
    return d


def per_image_table(order, data, ids):
    headers = ["사진 ID", "FaRL<br/>LaPa", "FaRL<br/>CelebM", "Media<br/>Pipe", "BiSe<br/>Net", "Seg<br/>Former", "SAM 2"]
    rows = [[P(v, "th") for v in headers]]
    for name in ids:
        rows.append([P(name, "tl")] + [P(f"{float(data[k][name]['iou']):.3f}", "tc") for k, _ in order])
    return table(rows, [43*mm] + [21.16*mm]*6, compact=True)


def video_table():
    mapping = [("mediapipe-1fps", "MediaPipe"), ("segformer-1fps", "SegFormer"),
               ("farl-lapa", "FaRL LaPa"), ("bisenet", "BiSeNet"), ("sam2", "SAM 2 + MediaPipe")]
    rows = [[P(x, "th") for x in ["방식", "처리", "빈 마스크", "처리 시간 중앙값*"]]]
    hashes = set()
    indices = None
    for name, label in mapping:
        root = VIDEO / "runpod-results" / name
        meta = json.loads((root / "metadata.json").read_text(encoding="utf8"))
        records = rows_at(root / "frames.csv")
        hashes.add(meta["video_sha256"])
        current = [r["frame"] for r in records]
        if indices is None:
            indices = current
        if current != indices or len(current) != 12:
            raise ValueError("Video frame lists differ")
        empty = sum(int(r["mask_pixels"]) == 0 for r in records)
        ms = statistics.median(float(r["elapsed_ms"]) for r in records)
        rows.append([P(label, "tl"), P("12장", "tc"), P(f"{empty}장", "tc"), P(f"{ms:.1f} ms", "tc")])
    if len(hashes) != 1:
        raise ValueError("Video hashes differ")
    return table(rows, [71*mm, 25*mm, 31*mm, 43*mm])


def gallery(ids, start):
    cells = []
    for index, photo_id in enumerate(ids, start=start):
        photo = ROOT / "research/data/LaPa/test/images" / f"{photo_id}.jpg"
        cells.append([img(photo, 72*mm, 55*mm), Spacer(1, 2*mm), P(f"{index:02d} · {photo_id}", "small")])
    if len(cells) % 2:
        cells.append("")
    t = Table([[cells[i], cells[i+1]] for i in range(0,len(cells),2)], colWidths=[85*mm,85*mm])
    t.setStyle(TableStyle([("VALIGN", (0,0),(-1,-1),"TOP"), ("ALIGN", (0,0),(-1,-1),"CENTER"),
                           ("TOPPADDING", (0,0),(-1,-1),4), ("BOTTOMPADDING", (0,0),(-1,-1),8)]))
    return t


def main():
    order, data, ids = still_data()
    summary, stats = summary_table(order, data, ids)
    story = [P("VISHUE  /  AR RESEARCH REPORT", "eyebrow"), Spacer(1,3*mm),
             P("입술 모델 비교", "title"), P("사진 정답 평가와 동영상 렌더링 예비 실험", "body"), Spacer(1,5*mm)]
    meta = Table([[P("평가일", "small"),P("정지 사진", "small"),P("동영상", "small")],
                  [P("2026. 11. 09", "body"),P("LaPa test 10장", "body"),P("1개 · 12개 시점", "body")]], colWidths=[56*mm,57*mm,57*mm])
    meta.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#f3f7fa")),("TOPPADDING",(0,0),(-1,-1),7), ("BOTTOMPADDING",(0,0),(-1,-1),7), ("LEFTPADDING",(0,0),(-1,-1),9)]))
    story += [meta, Spacer(1,4*mm), P("01  정답 입술과의 일치도", "h"),
              P("같은 사진 10장에 대한 IoU 중앙값입니다. 1에 가까울수록 모델이 찾은 입술 영역과 정답이 더 많이 겹칩니다."),
              Spacer(1,2*mm), graph(stats), Spacer(1,1*mm), summary, Spacer(1,2*mm),
              P("※ 사진별 지표의 중앙값. FaRL LaPa는 LaPa 출처 학습 모델이며, 이 소표본으로 최종 우열을 확정할 수 없습니다.", "small")]

    story += [PageBreak(), P("02  사진별 정확도", "h"),
              P("모든 방식은 동일한 LaPa test 사진 10장의 정답과 비교했습니다. 아래 값은 사진별 IoU입니다."), Spacer(1,4*mm),
              per_image_table(order,data,ids), Spacer(1,4*mm),
              P("지표 읽는 법", "h"),
              P("• IoU: 정답 입술과 예측 입술이 얼마나 겹치는지 나타냅니다. 높을수록 좋습니다.<br/>"
                "• 넘침: 모델이 입술이라고 표시한 영역 중 실제 정답 밖에 있는 비율입니다.<br/>"
                "• 누락: 정답 입술 중 모델이 놓친 비율입니다. 넘침이 정의되지 않는 빈 예측은 넘침 중앙값에서 제외했습니다."),
              Spacer(1,3*mm), P("해석 제한", "h"),
              P("파일명순 첫 10장으로, 같은 사람의 사진이 포함될 수 있습니다. FaRL LaPa 원본 결과와 CelebM의 얼굴 검출 입력 크기도 다릅니다. "
                "SAM 2는 MediaPipe가 예측한 점과 상자를 힌트로 사용한 조합입니다. 사진의 실제 메이크업 재현력이나 iPhone 성능을 뜻하지 않습니다.")]

    story += [PageBreak(), P("03  동영상에서 확인한 결과", "h"),
              P("동의받은 영상 1개를 1초 간격으로 추출한 12개 시점입니다. 원본은 약 11초·30fps이며, 음성을 제거하고 540×960 크기로 처리했습니다. 립 설정은 #B3202E · satin · 강도 0.6으로 고정했습니다."),
              Spacer(1,4*mm), video_table(), Spacer(1,3*mm),
              P("* 입력 프레임을 불러온 뒤 모델별 마스크를 만드는 데 걸린 시간의 중앙값입니다. 첫 실행이 포함되고 방식별 계산·하드웨어가 달라 직접적인 모델 속도 순위가 아닙니다. "
                "영상 디코딩, 앱 렌더링 및 네트워크 왕복은 제외됐습니다. 이번 영상 결과 파일에는 GPU 기종이 기록되지 않았습니다.", "small"),
              Spacer(1,3*mm), P("빈 마스크와 미검출", "h"),
              P("2초의 옆얼굴에서 MediaPipe와 SAM 2 조합은 얼굴을 찾지 못했고, BiSeNet은 입술 픽셀이 없는 마스크를 냈습니다. "
                "SegFormer·FaRL LaPa는 마스크가 비어 있지 않았지만, 정답이 없어 해당 마스크가 정확하다고 단정할 수 없습니다."),
              Spacer(1,3*mm), P("실제 화면 해석", "h"),
              P("렌더러의 얼굴 메시와 추적은 모든 방식에서 MediaPipe를 사용합니다. 따라서 공통 추적을 놓치면 다른 모델이 마스크를 만들어도 화장이 보이지 않을 수 있습니다. "
                "모델별 화면은 별도 추적으로 렌더링해 기준점이 완전히 고정된 결과는 아닙니다."),
              Spacer(1,3*mm), P("비교 영상은 PDF 첨부 파일에도 포함했습니다. PDF 앱이 첨부 파일을 지원하지 않으면 별도 MP4를 열어 주세요.", "small")]

    for title, file, text in [
        ("04  영상 장면 · 옆얼굴", "comparison-five-side.png", "2초 시점. 공통 MediaPipe 얼굴 추적이 이 장면을 놓쳐 모든 렌더에서 색이 보이지 않습니다. 다른 모델의 비어 있지 않은 마스크가 곧 렌더 성공을 뜻하지는 않습니다."),
        ("05  영상 장면 · 입 벌리기", "comparison-five-check.png", "9초 시점. SAM 2 조합에서는 입 안쪽에도 붉은색이 보입니다. 다섯 결과 모두 입술 색이 평평하고 스티커처럼 보이는 문제가 있어 자연스러운 발색 품질을 충족했다고 볼 수 없습니다."),
    ]:
        story += [PageBreak(), P(title,"h"), P("동일한 색상 · 제형 · 강도로 렌더링한 예비 비교", "small"), Spacer(1,3*mm),
                  img(VIDEO / file, 155*mm, 194*mm), Spacer(1,3*mm), P(text,"body")]

    story += [PageBreak(), P("06  판단과 다음 단계", "h"),
              P("이번에 확인한 것", "eyebrow"), Spacer(1,2*mm),
              P("• FaRL LaPa는 10장 정답 비교에서 가장 높은 중앙 IoU를 보였습니다. 다만 학습 데이터 출처가 같아 다른 출처 사진으로도 검증해야 합니다.<br/>"
                "• MediaPipe·BiSeNet·FaRL CelebM은 10장 중앙값이 비슷했습니다. 적은 표본에서 미세한 순위를 결정하기 어렵습니다.<br/>"
                "• SAM 2는 이번 점·상자 힌트 조건에서 넓은 영역을 포함하는 경향을 보였습니다. 다른 힌트 조건까지 일반화할 수 없습니다."),
              Spacer(1,5*mm), P("아직 확인하지 못한 것", "eyebrow"), Spacer(1,2*mm),
              P("• 동영상에는 입술 정답 마스크가 없어 영상 정확도 점수는 산출하지 않았습니다.<br/>"
                "• 1fps 결과는 시간별 비교 장면입니다. 30fps 추적 안정성이나 실시간 서버 왕복 지연을 보여주지 않습니다.<br/>"
                "• FaRL CelebM 영상은 가중치 다운로드가 두 차례 시간 초과돼 제외됐습니다.<br/>"
                "• 실제 iPhone 13에서 다른 모델을 실행하거나 비교한 결과는 없습니다."),
              Spacer(1,5*mm), P("권장 후속", "eyebrow"), Spacer(1,2*mm),
              P("① 렌더러의 입술 명암·결·반사를 개선한 뒤 같은 색으로 재확인합니다.<br/>"
                "② 동일 조건으로 더 많은 LaPa test 이미지와 다른 출처 데이터를 평가합니다.<br/>"
                "③ 실제 영상 프레임의 정답을 일부 표시해 넘침·치아 침범·누락을 측정합니다.<br/>"
                "④ iPhone과 서버를 연결해 지연·추적 안정성·비용을 따로 측정합니다."),
              Spacer(1,6*mm), P("자료 및 사용 범위", "h"),
              P("출처: LaPa Dataset test 이미지·마스크, 사용자 동의 영상, RunPod와 로컬 실험 결과 CSV. LaPa는 비상업적 연구·교육 용도 조건을 따릅니다. "
                "이 PDF에는 얼굴 사진과 영상이 포함되어 있으므로 공유 범위는 데이터 사용 조건과 촬영 동의를 따릅니다.", "small"),
              Spacer(1,3*mm),
              P('<link href="https://github.com/jd-opensource/lapa-dataset" color="#138b87">LaPa 데이터와 사용 조건</link> · '
                '<link href="https://huggingface.co/jonathandinu/face-parsing" color="#138b87">SegFormer 모델 카드</link> · '
                '<link href="https://github.com/FacePerceiver/facer" color="#138b87">FaRL 실행 도구</link> · '
                '<link href="https://github.com/facebookresearch/sam2" color="#138b87">SAM 2 공식 자료</link>', "small")]

    for number, sub in [(0,ids[:6]),(6,ids[6:])]:
        story += [PageBreak(), P(f"07  LaPa 평가 사진 · {number+1}–{number+len(sub)}", "h"),
                  P("정답 기반 IoU 비교에 실제 사용된 사진과 파일 ID", "small"), Spacer(1,3*mm), gallery(sub,number+1),
                  P("사진 출처: LaPa Dataset · 비상업적 연구 및 교육 목적의 자료", "small")]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_name("model_report_base.pdf")
    doc = SimpleDocTemplate(str(tmp), pagesize=A4, leftMargin=20*mm, rightMargin=20*mm,
                            topMargin=17*mm, bottomMargin=22*mm,
                            title="입술 모델 비교 — 사진 및 영상 예비 실험", author="VISHUE")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    with pymupdf.open(str(tmp)) as pdf:
        pdf.embfile_add("video_comparison_5models.mp4", MOVIE.read_bytes(), filename="video_comparison_5models.mp4",
                        desc="동의 영상 5방식 비교: 1fps 예비 실험")
        pdf.save(str(OUT), deflate=True)
    print(OUT)


if __name__ == "__main__":
    main()
