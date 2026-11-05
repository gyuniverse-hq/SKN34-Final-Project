# -*- coding: utf-8 -*-
"""One-off builder for the mentor AR brief. Output: docs/ar-mentor-brief.pdf"""
from reportlab.lib.colors import Color, white
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    KeepTogether, ListFlowable, ListItem, HRFlowable,
)

pdfmetrics.registerFont(TTFont("Malgun", r"C:\Windows\Fonts\malgun.ttf"))
pdfmetrics.registerFont(TTFont("MalgunBd", r"C:\Windows\Fonts\malgunbd.ttf"))

INK = Color(0.12, 0.13, 0.15)
MUTED = Color(0.33, 0.35, 0.38)
RULE = Color(0.82, 0.78, 0.74)
ACCENT = Color(0.45, 0.22, 0.24)
BAND = Color(0.96, 0.94, 0.92)
ROW = Color(0.98, 0.97, 0.96)

PAGE_W, PAGE_H = A4
OUT = r"c:\Users\playdata2\SKN34-Final-Project\docs\ar-mentor-brief.pdf"


def S(name, font, size, leading, color=INK, align=TA_LEFT, space_before=0, space_after=6, first_indent=0):
    return ParagraphStyle(
        name, fontName=font, fontSize=size, leading=leading, textColor=color,
        alignment=align, spaceBefore=space_before, spaceAfter=space_after,
        firstLineIndent=first_indent,
    )


styles = {
    "kicker": S("kicker", "Malgun", 9, 12, ACCENT, space_after=2),
    "h1": S("h1", "MalgunBd", 18, 24, INK, space_after=4),
    "h2": S("h2", "MalgunBd", 13, 18, INK, space_before=12, space_after=6),
    "h3": S("h3", "MalgunBd", 11, 15, ACCENT, space_before=8, space_after=3),
    "body": S("body", "Malgun", 9.5, 14.5, INK, TA_JUSTIFY, space_after=6),
    "small": S("small", "Malgun", 8.5, 12.5, MUTED, TA_LEFT, space_after=4),
    "th": S("th", "MalgunBd", 8, 11, white, TA_LEFT, space_after=0),
    "td": S("td", "Malgun", 8, 11.2, INK, TA_LEFT, space_after=0),
    "footer": S("footer", "Malgun", 8, 10, MUTED),
    "bullet": S("bullet", "Malgun", 9.5, 14, INK, TA_LEFT, space_after=1),
}


def P(text, style="body"):
    return Paragraph(text, styles[style])


def bullets(items):
    flow = []
    for item in items:
        flow.append(Paragraph("·  " + item, styles["bullet"]))
    return flow


def table(headers, rows, col_widths):
    head = [P(h, "th") for h in headers]
    data = [head] + [[P(c, "td") for c in row] for row in rows]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("BACKGROUND", (0, 1), (-1, -1), white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, ROW]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 0, ACCENT),
        ("LINEBELOW", (0, 1), (-1, -2), 0.2, RULE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.4, RULE),
    ]))
    return t


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(ACCENT)
    canvas.rect(0, PAGE_H - 8 * mm, PAGE_W, 8 * mm, fill=1, stroke=0)
    canvas.setFillColor(white)
    canvas.setFont("Malgun", 8)
    canvas.drawString(18 * mm, PAGE_H - 5.4 * mm, "AR 가상 메이크업  ·  멘토 전달")
    canvas.drawRightString(PAGE_W - 18 * mm, PAGE_H - 5.4 * mm, "2026-10-26")
    canvas.setFillColor(RULE)
    canvas.rect(0, 0, PAGE_W, 10 * mm, fill=1, stroke=0)
    canvas.setFillColor(MUTED)
    canvas.setFont("Malgun", 8)
    canvas.drawString(18 * mm, 4.2 * mm, "숙제 01–04와 구현 내용  ·  영상은 서버로 전송하지 않음")
    canvas.drawRightString(PAGE_W - 18 * mm, 4.2 * mm, f"{doc.page}")
    canvas.restoreState()


def build():
    doc = SimpleDocTemplate(
        OUT, pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title="AR 가상 메이크업 작업 보고",
        author="SKN34",
    )
    W = PAGE_W - 32 * mm
    story = []

    story.append(Spacer(1, 4 * mm))
    story.append(P("멘토 전달용", "kicker"))
    story.append(P("AR 가상 메이크업 작업 보고", "h1"))
    story.append(P(
        "폰 안에서 돌아가는 립 시착을 만들고, 그 결과를 숙제 01부터 04의 데이터·모델·평가와 어떻게 연결했는지 정리한 문서입니다. "
        "기간은 2026-10-21부터 10-25이고, 확인 기기는 갤럭시 플립(Expo Go)입니다.",
        "body",
    ))
    story.append(HRFlowable(width="100%", thickness=0.6, color=ACCENT, spaceAfter=8))

    story.append(P("1. 한 줄로 보는 위치", "h2"))
    story.append(P(
        "주 기능은 전면 카메라 위 입술에만 제품 색을 올리는 시착입니다. 얼굴 영상은 서버로 나가지 않고, WebView 안의 MediaPipe와 WebGL이 처리합니다. "
        "고른 색을 입술 전체에 한 톤으로 덮지 않고, 맨입술 밝기 위에 립스틱 층을 쌓아서 주름과 제형 윤기가 남게 했습니다. "
        "피부와 배경 조명은 카메라 그대로입니다.",
        "body",
    ))
    story.append(table(
        ["숙제", "주제", "이번 작업에서 한 일"],
        [
            ["01", "실제 화장 전후와 시뮬레이션 검증", "본인 1명이 약 30장을 찍어 화면을 고침. 입술 정답이 있는 연구용 얼굴 약 2,000장으로 위치와 칠한 영역을 검증. PPT 파일은 없음."],
            ["02", "시뮬레이션용 CV 모델 조사", "앱은 MediaPipe Face Landmarker. 2,000장 중 200장으로 분할 모델과 비교해 얼굴 점을 유지."],
            ["03", "화장품 이미지·성분 데이터", "올리브영 색 시트 30제품·371색을 추정값으로 가져옴. 이미지와 리뷰 원문, 성분 DB는 넣지 않음."],
            ["04", "평가 방법론", "색차(CIEDE2000), 결(SSIM), 영역(IoU) 도구를 만듦. 사람 평가와 VLM 심사는 아직 없음."],
        ],
        [18 * mm, 42 * mm, W - 60 * mm],
    ))
    story.append(Spacer(1, 3 * mm))

    story.append(P("2. 시착이 하는 일", "h2"))
    story.append(P(
        "Expo Go에서 전면 카메라를 WebView로 띄웁니다. MediaPipe가 얼굴 478점 중 입술 바깥 20점과 안쪽 20점으로 윤곽을 잡고, 그 안에만 색을 칠합니다. "
        "입을 벌리면 안쪽 구멍은 비웁니다. 조명은 배경의 색으로 추정하고, 그 색은 립·볼·눈에만 씁니다. 장면 전체의 색은 바꾸지 않습니다.",
        "body",
    ))
    for b in bullets([
        "제형(매트, 새틴, 글로시, 시어 등)마다 한 번에 덮는 정도와 윤기 상한이 다릅니다. 윤기는 하얀 점이 아니라 제품 색이 밝아진 반사입니다.",
        "연하게·중간·진하게는 바르는 횟수에 대응합니다. 비교 도구에서는 1번을 진하기 1/3, 3번을 진하기 1로 둡니다.",
        "이후 아이라인, 마스카라, 블러셔, 아이섀도, 하이라이터, 쉐딩을 같은 추적 위에 올렸습니다. 파운데이션은 피부 보정과 경계가 겹쳐 넣지 않았습니다.",
        "개발 모드에서 백엔드 제품이 없을 때만 올리브영 추정 색으로 고를 수 있습니다. 배포 빌드는 백엔드 카탈로그만 봅니다. 지금 시드 카탈로그는 비어 있습니다.",
    ]):
        story.append(b)
    story.append(Spacer(1, 2 * mm))

    story.append(P("3. 본인 촬영에서 고친 화면", "h2"))
    story.append(P(
        "약 30장은 갤럭시 플립에서 시착 결과를 찍은 확인용입니다. 정면, 측면, 입 벌림, 클로즈업이 있고, 유리아쥬 R02, 퓌 글로시·피치, 라카 코랄처럼 매트와 글로시를 오갔습니다. "
        "삼각대로 맨입술과 1번·3번을 짝 지은 정량 세트는 아니고, 같은 얼굴에서 바른 것처럼 보이는지를 보고 셰이더를 고친 사진입니다.",
        "body",
    ))
    story.append(table(
        ["화면에서 보인 것", "원인", "고친 방향"],
        [
            ["윗입술이 하얗게 뜸", "입술 UV의 위아래를 반대로 읽어 윤기가 윗입술 전체에 깔림", "위아래를 뒤집고, 반사는 아랫입술 중앙의 색 있는 점으로 제한"],
            ["위·아래가 두 색으로 갈라짐", "층 쌓기 비율을 입술 평균색 하나로 계산", "픽셀별 맨입술 색으로 층을 쌓음"],
            ["글로시 위에 흰 막", "아랫입술의 넓은 밝은 면을 반사광으로 잘못 분리", "주변보다 튀고 채도가 낮은 점만 반사로 봄"],
            ["입술 밖으로 번짐, 끝선이 울퉁불퉁", "붉은 피부를 입술로 확장하고, UV 윤곽이 삼각형마다 꺾임", "화면 좌표에서 윤곽을 다시 그림. 붉기로 확장하던 단계는 끔"],
            ["크게 벌리면 안쪽이 안 칠해짐", "실제 입술 일부가 얼굴 점 안쪽 선 안에 있음", "벌린 정도에 따라 안쪽 선까지 칠함"],
            ["고개를 흔들면 늦게 따라옴", "기준점까지 필터에 넣음", "입 위치는 바로 따라가고, 잔떨림만 부드럽게 함"],
            ["시어 누드가 맨입술보다 어두운 빨강", "맨입술 빨강에 제품 색을 곱하기만 함", "덮는 만큼 먼저 제품 색으로 섞고, 비치는 몫만 맨입술 색을 거름"],
        ],
        [38 * mm, 58 * mm, W - 96 * mm],
    ))
    story.append(Spacer(1, 2 * mm))
    story.append(P(
        "색 값(hex)과 한 번에 덮는 비율의 출발값은 유지하고, 명암·결·반사로 맞췄습니다. 갤럭시에서 본 프레임은 대략 초당 16장에서 24장 사이였습니다.",
        "small",
    ))

    story.append(P("4. 숙제 01. 실제 화장 전후와 시뮬레이션 검증", "h2"))
    story.append(P(
        "주제는 실제로 바른 모습과 시착이 얼마나 가까운지 보는 것입니다. 이번 범위는 팀원 여러 명이 아니라 본인 1명입니다. "
        "직접 확인은 약 30장이고, 입술 위치의 숫자 검증은 연구용 얼굴 약 2,000장입니다.",
        "body",
    ))
    story.append(P("본인이 찍은 약 30장", "h3"))
    story.append(P(
        "Expo Go 시착 화면입니다. 이 사진으로 위 표의 실패를 찾고, 고친 뒤 같은 조건으로 다시 봤습니다. "
        "여러 사람의 피부톤, 고정 조명, 맨입술과 바른 입술의 짝은 이 30장에 들어 있지 않습니다.",
        "body",
    ))
    story.append(P("참고로 쓰게 한 약 2,000장", "h3"))
    story.append(P(
        "LaPa 시험 세트입니다. 비상업 연구용이라 저장소 밖 폴더에만 두고, 앱과 서버로는 보내지 않았습니다. "
        "입술 정답(윗입술, 아랫입술)이 있어서, 본인 사진으로는 재기 어려운 입술 위치를 숫자로 봤습니다. 제품이 사람마다 다르고 화장 전후 짝이 없으므로 색의 정답은 아닙니다.",
        "body",
    ))
    story.append(table(
        ["쓴 양", "본 것", "결과"],
        [
            ["2,000장 전체", "앱과 같은 얼굴 점이 입술 정답과 겹치는 정도", "IoU 0.705. 입 벌림 0.68, 다문 입 0.75. 얼굴 인식 99.2%."],
            ["정면 200장", "폰 크기(720×960)로 점, 측정 윤곽, 분할 모델 비교", "얼굴 점 0.736이 가장 나음. 붉기로 다시 그린 윤곽은 0.703으로 더 나빠져 앱에서 끔."],
            ["200장에 색을 입힌 결과", "윤곽이 아니라 실제로 색이 올라간 픽셀", "칠한 영역 IoU가 수정 과정에서 대략 0.61에서 0.66 근처로 움직임. 입 벌린 장만 보면 빠짐이 줄었음."],
            ["벌린 입 1,132장", "실제 입술이 얼굴 점 안쪽에 있는지", "약 13%가 안쪽 선 안에 있어, 벌린 입은 안쪽까지 칠하게 바꿈."],
        ],
        [32 * mm, 62 * mm, W - 94 * mm],
    ))
    story.append(Spacer(1, 3 * mm))
    story.append(P("만든 검증 도구", "h3"))
    for b in bullets([
        "촬영 규칙과 파일 이름 검사. 나중에 맨입술, 1번, 3번, 정면·30도·45도를 짝지을 때 쓰기 위한 준비입니다. 이번 30장은 그 규칙의 완성 세트가 아닙니다.",
        "오프라인 렌더. 맨입술 사진에 앱과 같은 셰이더를 PC 브라우저로 입힙니다. 프레임은 PC 밖으로 나가지 않습니다. 폰 카메라 경로와는 다릅니다.",
        "비교 스크립트. 입술 평균색 CIEDE2000, 밝기 폭, 하이라이트 밝기, 얼굴을 맞춘 뒤 밝기 SSIM을 냅니다. CIEDE2000은 공개 검증값 4쌍과 일치했습니다.",
        "파이프라인 시험은 2,000장 중 3명×2색으로만 돌렸습니다. 정답을 AR 렌더로 두면 색차 0.26, SSIM 0.99이고, 맨입술은 색차 11.6이었습니다. 도구가 동작한다는 확인입니다.",
    ]):
        story.append(b)
    story.append(Spacer(1, 2 * mm))
    story.append(P(
        "PPT 시뮬레이션은 명세서에 폴더 이름만 있고, 만든 파일은 없습니다. 비교에 쓴 시뮬레이션은 PPT가 아니라 앱 셰이더입니다.",
        "body",
    ))

    story.append(P("5. 숙제 02. 메이크업 시뮬레이션 CV 모델", "h2"))
    story.append(P(
        "주제는 입술을 찾는 모델 중 무엇을 실시간으로 쓸지 정하는 것입니다. 색을 칠하기 전에 반드시 지나가는 단계라, 여기가 틀리면 색 비교도 입술 밖을 재게 됩니다.",
        "body",
    ))
    story.append(table(
        ["모델", "라이선스", "이번 역할"],
        [
            ["MediaPipe Face Landmarker, 478점", "Apache 2.0", "앱의 기본안. 입술 점, 고개, 입 벌림. 영상은 폰 안에만 있음."],
            ["MediaPipe 셀피 분할", "Apache 2.0", "입술 탐지가 아니라 배경과 피부를 갈라 조명 색을 추정."],
            ["BiSeNet ResNet18, 512px", "코드 MIT, 학습 데이터 비상업", "비교만. 앱에 넣지 않음. 명세서의 SegFormer 대신 실제로 돌린 모델."],
        ],
        [48 * mm, 38 * mm, W - 86 * mm],
    ))
    story.append(Spacer(1, 3 * mm))
    story.append(P(
        "폰 크기 200장에서 얼굴 점 IoU 0.736, BiSeNet 0.714(CPU 약 170ms)였습니다. 분할이 점보다 낫지 않고 매 프레임에 넣기 무거워, 앱은 얼굴 점을 유지했습니다. "
        "생성형으로 화장한 얼굴을 새로 그리는 모델은 비교에서 빼 두었습니다. 제품 색이 바뀌고, 같은 입력에도 결과가 달라지며, 피부와 얼굴형을 건드릴 수 있기 때문입니다. "
        "팀 사진과 사람이 칠한 마스크로 된 공식 비교 보고서, 각도별 Dice, 정지 10초 떨림 수치는 아직 없습니다. 2,000장 숫자는 공개 데이터 예비 측정입니다.",
        "body",
    ))

    story.append(P("6. 숙제 03. 화장품 이미지·성분 데이터", "h2"))
    story.append(P(
        "주제는 시착에 쓸 색과 이미지를 어디서 가져오고, 성분과 어떻게 연결할지 정하는 것입니다. 이번 구현은 색만 가져왔습니다.",
        "body",
    ))
    for b in bullets([
        "올리브영 색 시트를 개발용 카탈로그로 변환했습니다. 제품 30개, 셰이드 371개. 색은 컬러칩 추정값이고 확인일은 2026-10-21입니다. 가격은 시트에 없어 0으로 두고 미확인으로 표시합니다.",
        "옵션 이미지 주소와 리뷰 문장은 가져오지 않습니다. 입술, 블러셔, 아이섀도만 칠하고, 립라이너와 아이브로, 아이라이너, 마스카라는 목록에만 둡니다.",
        "이 목록은 개발 모드에서 백엔드가 비어 있을 때만 AR에 나옵니다. 정식 시드 카탈로그는 현재 비어 있습니다.",
        "색 계열 칩(레드, 코랄, 핑크, 베리, 누드, 브라운)은 추정 hex를 색 공간으로 나눈 찾기 기능입니다. 실측 발색이 아닙니다.",
        "질감 참고로 Openverse에서 237장을 받아 60장을 봤고, 실사 입술은 3장이었습니다. 윤기 방향만 보고 색의 정답으로 쓰지 않습니다.",
        "성분 화면 문구는 있으나, 식약처 성분 원본과 가져오기 스크립트는 없습니다. 측정 CSV가 생기면 추정 색을 덮도록 설계만 해 두었습니다.",
    ]):
        story.append(b)

    story.append(P("7. 숙제 04. 평가 방법론", "h2"))
    story.append(P(
        "주제는 자연스러움과 실제 색을 한 점수로 섞지 않고, 질문마다 지표를 나누는 것입니다. 숫자 도구는 만들어 두었고, 사람 평가와 모델 심사는 아직입니다.",
        "body",
    ))
    story.append(table(
        ["질문", "지표", "상태"],
        [
            ["색이 같은가", "입술 평균 CIEDE2000", "계산은 공개 검증값과 일치. 본인 30장에는 아직 적용하지 않음."],
            ["주름과 명암이 남았는가", "밝기 SSIM, 밝기 폭, 하이라이트", "같은 비교 도구에 있음. 팀 전후 짝이 없어 성적은 없음."],
            ["입술 제자리인가", "IoU, 넘침, 빠짐", "2,000장과 200장으로 측정함. 위 01의 표."],
            ["사람 눈에 자연스러운가", "1점에서 5점, 진짜 사진인지", "폼 없음. 본인 30장이 그 역할을 눈대중으로 대신한 상태."],
            ["VLM이 사람을 대신하는가", "같은 질문, 순서 바꿈, 3회 반복", "설계만 있음. 실행 없음. 용어가 LLM-as-a-Judge가 맞는지 확인이 필요."],
            ["생성 이미지 품질 FID", "사용하지 않음", "사진 수가 적어 이유만 명세에 적음."],
        ],
        [42 * mm, 52 * mm, W - 94 * mm],
    ))
    story.append(Spacer(1, 3 * mm))
    story.append(P(
        "읽는 법은 이렇습니다. 색차만 낮고 결 점수가 낮으면 색은 맞는데 스티커처럼 덮인 것입니다. 결만 높고 색차가 크면 주름은 사는데 색이 틀린 것입니다. "
        "숫자 둘 다 괜찮은데 사람이 어색하면 경계나 떨림입니다. 이미지 모델에게는 색이 맞는지, 피부가 바뀌었는지를 묻지 않습니다. 그 둘은 색차와 SSIM이 맡습니다. "
        "외부 모델에 사진을 보내는 실험은 동의한 사진이고, 별도 스위치가 켜져 있을 때만 하도록 정해 두었습니다.",
        "body",
    ))
    story.append(P(
        "공개 얼굴에 셰이더를 입혀 본 상대 지표도 있습니다. 시어 누드가 맨입술보다 어두워지던 계산을 고친 뒤, 제품과의 색 방향 차이가 시어 누드 8.2에서 5.3, 매트 레드 34.1에서 19.9로 줄었습니다. "
        "조명과 노출이 섞인 값이라 절대 성적은 아닙니다. 고개 흔들림 모의(초당 30장, 좌우 60px)에서는 2Hz 최대 오차가 20.8px에서 2.2px로 줄었습니다.",
        "body",
    ))

    story.append(P("8. 멘토님께 확인할 것과 남은 일", "h2"))
    for b in bullets([
        "숙제 04에서 말씀하신 평가가 LLM-as-a-Judge가 맞는지.",
        "본인 약 30장과 연구용 2,000장으로 01을 이 범위까지 본 것이 맞는지. 여러 사람, 고정 조명, 맨입술과 1번·3번 짝은 아직 없습니다.",
        "PPT 시뮬레이션은 만들지 않았고, 앱 셰이더를 시뮬레이션으로 썼습니다.",
        "성분 데이터와 정식 제품 DB는 비어 있습니다. 지금 AR에서 고르는 올리브영 색은 개발용 추정값입니다.",
        "사람 평가 폼, VLM 상관표, 모델 조사 보고서는 01의 짝 사진이 있어야 닫힙니다.",
    ]):
        story.append(b)
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=0.4, color=RULE, spaceBefore=4, spaceAfter=6))
    story.append(P(
        "근거 파일. 시착 셰이더는 components/ar/faceTrackerHtml.ts. 진행 기록은 docs/AR_PROGRESS.md, 평가 원칙은 docs/AR_SPEC.md 8장. "
        "01 도구는 research/protocol/hw01_capture.md, research/lip_reference/render_ar_offline.py, hw01_compare.py, eval_lapa.py. "
        "03 변환은 scripts/data/import_oliveyoung.py 와 lib/devCatalog/oliveyoung.ts.",
        "small",
    ))

    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    print(OUT)


if __name__ == "__main__":
    build()
