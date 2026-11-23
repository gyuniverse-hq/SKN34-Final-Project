# VISHUE AR 최신 메이크업 생성 모델 탐색 및 적용 가능성

조사일: 2026-11-20. 실행 상태: 추론 미실행. 출처 URL은 본문 표에 적는다.

스펙 10장과 멘토 요청은 층이 다르다. `docs/AR_SPEC.md` 10장은 생성형 메이크업을 **앱과 숙제 02 비교 표**에 넣지 않는다. 2026-11-19 멘토는 **품질 상한**을 최신 공개 모델로 보고, 실시간 구현과 **따로** 설명하라고 했다. 이 문서는 `research/` 보고이며 런타임에 넣지 않는다.

## 1. 멘토링 요구

출처: `VISHUE_2026-11-19_멘토링_요약.pdf` (6쪽). 저장소 안에는 사본이 없다.

- 2쪽: 25문항 O/X 총점은 외부 근거가 없고 핵심 오류를 가릴 수 있다. 도메인 근거를 갖추거나 지표 2~3개와 1~5점 정의로 줄인다.
- 3쪽: 립 제품 1개. 전후 사진 부족. 논문의 데이터·공개 추론을 확인하고 돌아가는 후보 1~2개를 눈으로 비교한다. GPU가 안 되면 무거운 모델로 상한을 본 뒤 시연 품질과 경량 구현을 구분한다.
- 6쪽 (11/21 10:00): 후보 실제 시험, 사용 데이터, 구현 가능성, 육안 결과.

이미 있는 것: 4모델 논문·저장소 조사, Gray World AR, 환경 13조건. 없는 것: 동일 조건 제품 전후, 생성 결과, CIEDE2000, 실행 캡처.

## 2. 현재 VISHUE AR

| 요소 | 경로 |
|---|---|
| 페이지·셰이더 | `components/ar/faceTrackerHtml.ts` |
| UV | `components/ar/faceUV.ts` (MediaPipe canonical_face_model.obj, Apache 2.0, 468점) |
| 호스트 | `components/ar/ArFaceView.tsx`. `compare`는 화면 반만 카메라 (`type: compare`) |
| One Euro | `faceTrackerHtml.ts`의 `euroAlpha`. 별도 `tracking/oneEuro.ts` 없음 |
| 조명 | 배경 Gray World + Gray-Edge, `glideLight`. `lib/arEnv.ts` 문구는 보정을 안 읽음 |
| 립 | 층 쌓기 (`AR_SPEC` 6-5-3). 균일 불투명 스티커면 실패 |

강점: 프레임마다 랜드마크·UV, 제품 hex 유지, 얼굴 영상 비전송, Expo Go.  
한계: 생성 참조 질감을 가져오는 경로 없음. 카탈로그 hex에 estimated가 있음.

생성형 vs AR: 입력은 정지 쌍 vs 연속 카메라, 출력은 한 장 vs 16~24fps WebGL, 화장은 샘플링 vs 셰이더 파라미터.

적용 방식 A(폰 직접)·B(프레임마다 서버)는 하지 않음. C(오프라인 후 파라미터)는 별도 승인. D(나란히 보기)가 이 보고서.

## 3. 네 모델 (실행 미검증)

| | MagicMakeup | Stable-Makeup | ART | DreamMakeup |
|---|---|---|---|---|
| 논문 | arXiv:2607.20924 ECCV 2026 | arXiv:2403.07764 SIGGRAPH 2025 | arXiv:2606.31089 ECCV 2026 | arXiv:2510.10918 WACV 2026 |
| 저장소 | github.com/vivoCameraResearch/Magic-Makeup | github.com/Xiaojiu-z/Stable-Makeup | github.com/csbowei/ART | dreammakeup.github.io (Code 링크 없음) |
| 추론 | `test_single.py` | `infer_kps.py`, Gradio | `infer.py` mt/demakeup | 보충 Algorithm 1 |
| 학습 코드 | README에 없음 | `train.sh` | 체크리스트 미공개 | 화장 모델 학습 없음 (설계) |
| 가중치 | HF Anyou/MagicMakeup + FLUX.1-Kontext-dev | Google Drive 3 bin + SD v1.5 | HF csbowei/ART LoRA 512·1024 + FLUX | 화장 전용 체크포인트 없음. SD/SDXL + CivitAI LoRA |
| 데이터 | 학습 6772쌍 비공개. MakeupHQ gated DUA | Makeup-real 20k 비공개 | MF2K 메타+URL. 평가 MT, Wild, LADN | 평가 MT, LADN. QnA 46만 비공개 |

공식 공개와 이 PC에서 실행됨은 별개다. 아래는 전부 **실행 미검증**.

## 4. ART (보조, 1순위 아님)

개요: Stage I pseudo-target, Stage II 실제 참조 복원 사이클. 2K 주장, 공개 LoRA는 512·1024.

공개: 추론·LoRA·MF2K 메타 공식 공개. 학습 코드 공식 미공개. 실행 미검증.

재현: 공개 가중치로 이미지 추론은 가능하다고 README가 말한다. 우리 화장품으로 Stage II를 다시 학습할 수는 없다.

실시간 장애: FLUX, 한 장 다스텝. Expo Go 불가. 서버 프레임은 원칙 1-4.

제외가 아니라 **보조**. 학습 코드 없음은 재학습 제약이지 성능 판정이 아니다. 재검토: FLUX가 한 번 돌면 MagicMakeup과 같은 소스·참조 1장.

## 5. DreamMakeup (보류)

개요: Training-free. 조기 중단 DDIM inversion 후 RGB·참조·텍스트.

공개: 논문·프로젝트 페이지 공식 공개. 공식 GitHub 추론 진입점 **미공개 확인**(2026-11-20, 저자 페이지 Code 없음). 화장 전용 가중치가 없는 것은 설계와 맞다. SD 가중치가 없다는 뜻이 아니다.

재현: 의사코드만으로 논문과 같다고 말할 수 없음 (**추정**).

실시간: 프레임마다 inversion 불가. 색만 옮기는 원리는 이미 층 쌓기와 같다.

재검토: 저자 저장소가 생기면 Stable-Makeup과 같은 프로토콜.

## 6. 최종 후보

MagicMakeup: 눈·입술·얼굴 라벨. TARG는 부위 밖 어텐션 차단. 앱에 합치지 않음. 비용 FLUX 1024 28 step.

Stable-Makeup: 화장 인코더 + 내용/구조 ControlNet. SD 1.5 512라 **먼저 돌리기** 쉽다. 학습쌍은 합성 화장. 생성 결과는 정답이 아니라 상한 사진.

결정: **평가·참고만 (D).** 셰이더 숫자 자동 추출은 가설, 미측정.

## 7. 11/21 최소 자료

이 탐색 문서, 환경 점검(로컬 GPU 없음), 제품 전후 **없음**, 후보 2개와 **실행 전**, AR과 생성의 차이 한 표. 추론 캡처는 없음.

CIEDE2000·IoU·SSIM·LPIPS는 립 ROI, 전후가 있을 때만. FID는 장 수 부족으로 쓰지 않음.
