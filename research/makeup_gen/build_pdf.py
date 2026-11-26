"""Build survey and compare-protocol PDFs. Korean via Malgun Gothic. No generated faces."""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parent
FONT = Path(r"C:\Windows\Fonts\malgun.ttf")
FONT_B = Path(r"C:\Windows\Fonts\malgunbd.ttf")
pdfmetrics.registerFont(TTFont("Malgun", str(FONT)))
pdfmetrics.registerFont(TTFont("MalgunBd", str(FONT_B)))

NAVY = colors.HexColor("#1a2744")
TEAL = colors.HexColor("#2a6f7f")
LINE = colors.HexColor("#c5cdd6")
HEAD_BG = colors.HexColor("#eef2f6")
WARN_BG = colors.HexColor("#fff6e8")


def styles():
    base = getSampleStyleSheet()
    s = {
        "cover": ParagraphStyle(
            "cover", fontName="MalgunBd", fontSize=16, leading=22, textColor=NAVY, alignment=TA_CENTER, spaceAfter=8
        ),
        "sub": ParagraphStyle(
            "sub", fontName="Malgun", fontSize=10, leading=14, textColor=TEAL, alignment=TA_CENTER, spaceAfter=16
        ),
        "h1": ParagraphStyle("h1", fontName="MalgunBd", fontSize=13, leading=18, textColor=NAVY, spaceBefore=12, spaceAfter=6),
        "h2": ParagraphStyle("h2", fontName="MalgunBd", fontSize=11, leading=15, textColor=TEAL, spaceBefore=8, spaceAfter=4),
        "body": ParagraphStyle(
            "body", fontName="Malgun", fontSize=9, leading=13, textColor=colors.HexColor("#222"), alignment=TA_JUSTIFY, spaceAfter=6
        ),
        "note": ParagraphStyle(
            "note", fontName="Malgun", fontSize=8, leading=11, textColor=colors.HexColor("#444"), backColor=WARN_BG, borderPadding=4, spaceAfter=8
        ),
        "cell": ParagraphStyle("cell", fontName="Malgun", fontSize=7, leading=9.5, textColor=colors.HexColor("#222")),
        "cellh": ParagraphStyle("cellh", fontName="MalgunBd", fontSize=7, leading=9.5, textColor=NAVY),
        "foot": ParagraphStyle("foot", fontName="Malgun", fontSize=7.5, leading=10, textColor=colors.HexColor("#666")),
        "url": ParagraphStyle("url", fontName="Malgun", fontSize=7.5, leading=10, textColor=TEAL),
        "li": ParagraphStyle("li", fontName="Malgun", fontSize=9, leading=13, leftIndent=0),
    }
    return s


S = styles()


def P(text: str, style="body"):
    return Paragraph(text.replace("&", "&amp;"), S[style])


def bullets(items: list[str]):
    return ListFlowable(
        [ListItem(P(x, "li"), leftIndent=12, bulletColor=TEAL) for x in items],
        bulletType="bullet",
        start="•",
        leftIndent=16,
        bulletFontName="Malgun",
        bulletFontSize=9,
        spaceAfter=6,
    )


def tbl(headers: list[str], rows: list[list[str]], col_w: list[float] | None = None):
    h = [P(x, "cellh") for x in headers]
    data = [h] + [[P(c, "cell") for c in r] for r in rows]
    t = Table(data, colWidths=col_w, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
                ("GRID", (0, 0), (-1, -1), 0.3, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return t


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Malgun", 7.5)
    canvas.setFillColor(colors.HexColor("#666"))
    canvas.drawString(18 * mm, 12 * mm, "VISHUE research/makeup_gen  ·  2026-11-20  ·  추론 미실행")
    canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, str(doc.page))
    canvas.restoreState()


def build_survey(path: Path):
    story = []
    story.append(P("VISHUE AR 최신 메이크업 생성 모델 탐색 및 적용 가능성", "cover"))
    story.append(P("멘토링 11월 19일 반영  ·  조사일 2026-11-20  ·  실행 상태: 추론 미실행", "sub"))
    story.append(
        P(
            "스펙 10장은 생성형 메이크업을 앱과 숙제 02 표에 넣지 않는다. 멘토는 품질 상한을 최신 공개 모델로 보고 "
            "실시간 구현과 따로 설명하라고 했다. 이 PDF는 research/ 보고이며 런타임에 넣지 않는다.",
            "note",
        )
    )

    story.append(P("1. 멘토링 요구", "h1"))
    story.append(
        P(
            "출처: VISHUE_2026-11-19 멘토링 요약 PDF(6쪽). 저장소 안 사본 없음. "
            "G 드라이브 취업 특강 PDF는 이 조사에서 열지 못함."
        )
    )
    story.append(
        tbl(
            ["쪽", "핵심"],
            [
                ["2", "25문항 O/X 총점은 외부 근거가 없고 핵심 오류를 가릴 수 있음. 도메인 근거 또는 지표 2~3개와 1~5점 정의."],
                ["3", "립 제품 1개. 전후 사진 부족. 논문 데이터·공개 추론 확인 후 돌아가는 후보 1~2개를 눈으로 비교. GPU가 안 되면 상한과 경량 구현을 구분."],
                ["6", "11/21 10:00. 후보 실제 시험, 사용 데이터, 구현 가능성, 육안 결과. 이 PC는 GPU 없어 시험 캡처 없음."],
            ],
            [18 * mm, 162 * mm],
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        P(
            "있는 것: 4모델 논문·저장소 조사, Gray World AR, 환경 13조건. "
            "없는 것: 동일 조건 제품 전후, 생성 결과, CIEDE2000, 실행 캡처. "
            "첨부 맨얼굴 셀카는 바른 뒤가 아니므로 정답·생성 입력으로 쓰지 않음."
        )
    )

    story.append(P("2. 현재 VISHUE AR", "h1"))
    story.append(
        tbl(
            ["요소", "경로·동작"],
            [
                ["페이지·셰이더", "components/ar/faceTrackerHtml.ts. MediaPipe Face Landmarker + Image Segmenter, WebGL이 HTML 문자열 안."],
                ["UV", "components/ar/faceUV.ts. canonical_face_model.obj, Apache 2.0, 468점 UV, 입·눈 구멍."],
                ["호스트", "components/ar/ArFaceView.tsx. compare는 화면 반만 카메라 (post type compare)."],
                ["One Euro", "faceTrackerHtml.ts euroAlpha. 별도 tracking/oneEuro.ts 없음."],
                ["조명", "배경 Gray World + Gray-Edge, glideLight. lib/arEnv.ts 문구는 보정을 안 읽음."],
                ["립", "층 쌓기 (AR_SPEC 6-5-3). 카메라 밝기·주름을 남기고 제품색을 덮는 양만큼. 균일 불투명이면 실패."],
            ],
            [32 * mm, 148 * mm],
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        P(
            "강점: 프레임마다 랜드마크·UV, 제품 hex 유지, 얼굴 영상 비전송, Expo Go. "
            "한계: 생성 참조 질감을 가져오는 경로 없음. 카탈로그 hex에 estimated가 있음. "
            "성능 HUD(fps, perf)와 생성 모델 추론 시간은 따로 적는다."
        )
    )
    story.append(P("생성형 이미지 vs 실시간 AR", "h2"))
    story.append(
        tbl(
            ["항목", "생성형 메이크업", "VISHUE AR"],
            [
                ["입력", "정지 소스 + 참조", "연속 전면 카메라"],
                ["출력", "화장이 그려진 한 장", "프레임마다 WebGL"],
                ["움직임·표정", "이미지마다 재생성", "랜드마크·UV 갱신"],
                ["조명", "생성 과정에 섞임", "0.5초 Gray World + 방향 적합"],
                ["속도", "수십 스텝 GPU", "목표 16~24 fps, Expo Go"],
                ["제품색", "참조 스타일 샘플링", "카탈로그 hex·Lab 유지 (1-1)"],
                ["기기", "데스크톱·서버 GPU", "모바일 WebView"],
            ],
            [28 * mm, 76 * mm, 76 * mm],
        )
    )
    story.append(Spacer(1, 6))
    story.append(P("적용 경로 A(폰 직접)·B(프레임마다 서버)는 하지 않음 (Expo Go, 원칙 1-4). C(오프라인 후 파라미터)는 별도 승인. D(나란히 보기)가 이 보고의 본체.", "body"))

    story.append(P("3. 네 모델 공개 현황", "h1"))
    story.append(P("조사일 2026-11-20. 공식 공개와 이 PC에서 실행됨은 별개. 아래 실행 칸은 전부 미검증."))
    story.append(
        tbl(
            ["", "MagicMakeup", "Stable-Makeup", "ART", "DreamMakeup"],
            [
                ["논문", "arXiv:2607.20924 ECCV 2026", "arXiv:2403.07764 SIGGRAPH 2025", "arXiv:2606.31089 ECCV 2026", "arXiv:2510.10918 WACV 2026"],
                ["저장소", "vivoCameraResearch/Magic-Makeup", "Xiaojiu-z/Stable-Makeup", "csbowei/ART", "dreammakeup.github.io. Code 링크 없음"],
                ["추론", "test_single.py", "infer_kps.py, Gradio", "infer.py mt/demakeup", "보충 Algorithm 1"],
                ["학습 코드", "README에 없음", "train.sh", "체크리스트 미공개", "화장 모델 학습 없음 (설계)"],
                ["가중치", "HF Anyou/MagicMakeup + FLUX.1-Kontext-dev", "Drive 3 bin + SD v1.5", "HF csbowei/ART LoRA 512·1024 + FLUX", "화장 전용 ckpt 없음. SD/SDXL + CivitAI LoRA"],
                ["데이터", "학습 6772쌍 비공개. MakeupHQ gated DUA", "Makeup-real 20k 비공개", "MF2K 메타+URL. 평가 MT, Wild, LADN", "평가 MT, LADN. QnA 46만 비공개"],
                ["상태", "추론 공개, 실행 미검증", "추론·학습 공개, 실행 미검증", "추론 공개, 학습 미공개, 실행 미검증", "공식 구현 미공개 확인"],
            ],
            [22 * mm, 40 * mm, 40 * mm, 39 * mm, 39 * mm],
        )
    )
    story.append(Spacer(1, 4))
    story.append(P("https://github.com/vivoCameraResearch/Magic-Makeup", "url"))
    story.append(P("https://github.com/Xiaojiu-z/Stable-Makeup", "url"))
    story.append(P("https://github.com/csbowei/ART", "url"))
    story.append(P("https://dreammakeup.github.io/", "url"))

    story.append(P("4. ART — 보조 (코드 없음으로 빼지 않음)", "h1"))
    story.append(
        P(
            "개요: Stage I은 교사 모델의 pseudo-target, Stage II는 실제 참조를 맨얼굴에서 복원하는 미분 가능 사이클. "
            "2K 주장이 있으나 공개 LoRA는 512와 1024. README 2026-07: 더 높은 해상도 가중치는 이번 릴리스 계획에 없음."
        )
    )
    story.append(
        bullets(
            [
                "공식 공개: 추론, LoRA, MF2K 메타·크롭 스크립트, HF Space 데모.",
                "공식 미공개: 학습 코드. 학습 재현 불가는 우리 화장품으로 Stage II를 다시 돌릴 수 없다는 뜻이지, 일반 전이 비교가 불가능하다는 뜻이 아님.",
                "재현 가능성: README 기준으로 공개 가중치 이미지 추론은 가능. 이 PC 실행 미검증.",
                "장점: 미세 화장 디테일·2K 데이터(MF2K 8,573, URL 재수집).",
                "VISHUE와 차이: 한 장 생성 vs 프레임 셰이더. 부위 라벨(눈/입술)이 없음.",
                "실시간 장애: FLUX.1-Kontext-dev 라이선스·VRAM. Expo Go 불가. 서버 프레임은 1-4.",
                "부담: MagicMakeup과 같은 백본이라 11/21 전 GPU를 둘에 나누기 어려움.",
                "이번 MVP: 1순위가 아니라 보조. 성능이 낮다고 판단하지 않음.",
                "재검토: FLUX가 한 번 돌면 같은 소스·참조로 MagicMakeup 옆에 1장.",
            ]
        )
    )

    story.append(P("5. DreamMakeup — 보류 (학습 안 함이 결함이 아님)", "h1"))
    story.append(
        P(
            "Training-free는 설계다. 조기 중단 DDIM inversion으로 얼굴 구조를 남기고, 픽셀에서 RGB·참조 히스토그램을 맞춘 뒤 "
            "텍스트 크로스 어텐션을 섞는다. 화장 전용 체크포인트가 없는 것은 가중치가 전혀 없다는 뜻이 아니다. "
            "기반은 SD v1.5 / SDXL과 CivitAI LoRA다."
        )
    )
    story.append(
        bullets(
            [
                "공식 공개: 논문, WACV 2026, 프로젝트 페이지, 보충 Algorithm 1.",
                "공식 미공개 확인(2026-11-20): 저자 페이지에 Code 링크 없음. 공식 추론 진입점 없음.",
                "재현: 의사코드와 CivitAI 목록만으로 논문과 같다고 말할 수 없음 (추정).",
                "장점: 색만 옮김. 우리 층 쌓기와 같은 방향. RGB·문장 조건.",
                "실시간: inversion 200~400 스텝을 프레임마다 불가.",
                "우선순위: 재현 진입점이 없어 MagicMakeup·Stable-Makeup보다 뒤.",
                "재검토: 저자 저장소가 생기면 같은 프로토콜로 1장.",
            ]
        )
    )

    story.append(P("6. 최종 후보와 가져올 원리", "h1"))
    story.append(
        P(
            "멘토의 ‘돌아가는 1~2개’는 저자 추론 스크립트가 있는 MagicMakeup과 Stable-Makeup이다. "
            "코드를 AR에 합치지 않는다. 생성 이미지에서 셰이더 숫자를 자동 추출하는 것은 가설이며 미측정."
        )
    )
    story.append(
        tbl(
            ["모델", "검증 질문", "가져올 원리", "가져오지 않음"],
            [
                [
                    "MagicMakeup",
                    "부위별 전이가 우리 존 번짐 평가에 쓰이는가?",
                    "TARG: 마스크 밖은 참조 화장을 보지 않음. 비편집 영역 오차.",
                    "FLUX를 폰·서버 프레임에 넣음. 학습 6772쌍(비공개).",
                ],
                [
                    "Stable-Makeup",
                    "생성 립의 색·하이라이트가 셰이더 참고가 되는가?",
                    "내용 / 구조 / 화장 인코더 분리. 512라 먼저 돌리기 쉬움.",
                    "합성 20k를 정답으로. 피부 결을 다시 그린 결과를 실물로.",
                ],
            ],
            [28 * mm, 50 * mm, 51 * mm, 51 * mm],
        )
    )

    story.append(P("7. 실험 설계 (실행 전)", "h1"))
    story.append(
        P(
            "제품명은 전후 파일이 확인되기 전 미확정. 스펙 후보는 힌스 무드인핸서이나 확정하지 않음. "
            "5칸(맨얼굴, 실제 발색, AR, MagicMakeup, Stable-Makeup)은 자료가 있는 칸만. "
            "실제 발색을 생성 참조로 넣고 같은 사진을 정답 CIEDE2000에 쓰지 않음. "
            "립 ROI만: CIEDE2000, 사람 마스크가 있으면 IoU, SSIM, LPIPS. FID는 장 수 부족으로 쓰지 않음. "
            "논문 숫자와 우리 측정은 칸을 나눈다. 못 재면 미측정."
        )
    )
    story.append(P("연결 파이프라인은 가설이다. 생성 하이라이트와 피부 그림자를 자동 구분하지 않는다. 정면 1장으로 측면·입 벌림 UV를 펴는 것은 추가 데이터 없으면 불가.", "body"))

    story.append(P("8. 환경 점검과 11/21", "h1"))
    story.append(
        tbl(
            ["항목", "결과"],
            [
                ["nvidia-smi / CUDA", "없음. torch.cuda.is_available() == False"],
                ["FLUX 라이선스·가중치", "미다운로드. 동의 여부 이 PC에서 확인 불가"],
                ["Stable-Makeup Drive", "미다운로드"],
                ["research/data/hw01_raw", "경로 없음"],
                ["립 제품 통제 전후", "미확정"],
            ],
            [45 * mm, 135 * mm],
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        P(
            "11/21에 보여줄 것: 이 탐색 문서, GPU 없음, 후보 2개와 실행 전, 스펙 10장과 멘토의 층 구분, "
            "실시간 AR과 생성의 차이 표. 추론 캡처는 없음. 최소 실험은 GPU가 생기면 공개 샘플로 Stable-Makeup 1장. "
            "사용자 얼굴은 참조/정답 분리 후에만."
        )
    )
    story.append(P("문서: research/makeup_gen/SURVEY.md, env_check.md, COMPARE_PROTOCOL.md", "foot"))

    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title="VISHUE AR 최신 메이크업 생성 모델 탐색",
        author="VISHUE research",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def build_compare(path: Path):
    story = []
    story.append(P("MagicMakeup vs Stable-Makeup: 실제 화장품 재현 비교 프로토콜", "cover"))
    story.append(P("생성 결과 없음  ·  모든 측정칸 미측정  ·  2026-11-20", "sub"))
    story.append(
        P(
            "추론을 돌리기 전에는 생성 그림을 만들지 않는다. 이 문서는 공정 조건과 빈 결과 표다. "
            "env_check.md: 이 PC에 CUDA GPU 없음.",
            "note",
        )
    )
    story.append(P("1. 목적", "h1"))
    story.append(
        P(
            "같은 소스·참조로 두 모델과 현재 VISHUE AR, 실제 발색을 나란히 본다. "
            "앱에 모델을 넣지 않는다. 성공 기준은 ‘사용자가 그 제품을 발랐을 때와 얼마나 유사한가’이며 "
            "생성 이미지의 예쁨과 실시간 fps를 한 점수로 합치지 않는다."
        )
    )
    story.append(P("2. 공정 조건", "h1"))
    story.append(
        bullets(
            [
                "제품: 전후 파일 확인 전 미확정.",
                "가능하면 동일 인물·카메라·거리·조명·화이트밸런스·정면·표정.",
                "실제 발색을 생성 참조로 넣고 같은 사진을 정답 CIEDE2000에 쓰지 않음.",
                "사용자 맨얼굴 셀카는 바른 뒤가 없어 정답이 아님.",
                "공개 샘플 추론이 먼저다. 사용자 얼굴은 동의·분리 설계 후.",
            ]
        )
    )
    story.append(P("3. 결과 표", "h1"))
    story.append(
        tbl(
            ["칸", "파일", "CIEDE2000 립ROI", "IoU", "SSIM", "LPIPS", "육안"],
            [
                ["맨얼굴", "없음", "—", "—", "—", "—", "미측정"],
                ["실제 발색", "없음", "정답", "—", "—", "—", "미측정"],
                ["VISHUE AR", "없음", "미측정", "미측정", "미측정", "미측정", "미측정"],
                ["MagicMakeup", "추론 미실행", "미측정", "미측정", "미측정", "미측정", "미측정"],
                ["Stable-Makeup", "추론 미실행", "미측정", "미측정", "미측정", "미측정", "미측정"],
            ],
            [28 * mm, 28 * mm, 28 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm],
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        P(
            "논문 MakeupHQ의 DINO-I, CLIP-I, Face-ID, L2M, FID는 저자 벤치 숫자다. "
            "우리 한 장 실험과 칸을 나눈다. 한 장 FID는 쓰지 않는다."
        )
    )
    story.append(P("4. VISHUE 적용 (가설)", "h1"))
    story.append(
        tbl(
            ["출처", "쓸 수 있는 것", "지금 불가"],
            [
                ["MagicMakeup TARG", "부위 밖 픽셀은 카메라 유지. 이미 UV·가림 마스크가 함. 번짐을 비편집 오차로 본다.", "생성 텍스처를 정면 1장으로 측면·입 벌림 UV에 펴기."],
                ["Stable-Makeup", "립 색 분포·하이라이트를 셰이더 참고 후보로 육안 비교.", "인코더를 WebGL에 이식. 합성 화장을 실물 정답으로."],
                ["둘 다", "평가·참고 이미지 (경로 D).", "Expo Go 직접 실행, 프레임마다 서버 (1-4)."],
            ],
            [36 * mm, 72 * mm, 72 * mm],
        )
    )
    story.append(P("5. 로드맵", "h1"))
    story.append(
        bullets(
            [
                "GPU·Drive·FLUX 동의가 있으면 Stable-Makeup 공개 테스트 이미지 1쌍.",
                "이어서 MagicMakeup 같은 쌍. 실패 로그를 남김.",
                "제품 전후가 있을 때만 CIEDE2000. 없으면 육안과 미측정.",
                "셰이더 반영은 별도 승인. 기본은 하지 않음.",
                "이 표를 채운 뒤에만 비교 PDF를 결과본으로 바꾼다.",
            ]
        )
    )
    story.append(P("research/makeup_gen/COMPARE_PROTOCOL.md  ·  env_check.md", "foot"))

    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title="MagicMakeup vs Stable-Makeup 비교 프로토콜",
        author="VISHUE research",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def main():
    p1 = ROOT / "VISHUE_2026-11-20_makeup-gen-survey.pdf"
    p2 = ROOT / "VISHUE_2026-11-20_candidate-compare-protocol.pdf"
    build_survey(p1)
    build_compare(p2)
    print(p1)
    print(p2)


if __name__ == "__main__":
    main()
