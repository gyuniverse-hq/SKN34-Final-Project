# 모델별 입력·출력 구조 (8회차 멘토링 우선 1번, 2026-11-23)

소스는 실제로 실행한 커밋 기준이다(MagicMakeup `b4d16f5`, Stable-Makeup `88c8ca5`). 11-20 실행 기록은
`research/data/makeup_gen/out_*/run_log.json`, `out_magicmakeup/logs/run_mm.py`(git 제외)에 있다.

## 1. 한 줄 요약

| | 입력 | 출력 | 텍스트 입력 | 부위 지정 |
|---|---|---|---|---|
| VISHUE AR | 카메라 영상(매 프레임) + 부위별 `ZoneSetting`(제품 hex, 질감, 진하기, 모양 옵션) | 화장을 칠한 영상(매 프레임, WebGL) | 없음 | 10개 부위 각각 |
| MagicMakeup | 맨얼굴 사진 + 화장 레퍼런스 사진 + 두 사진의 마스크 + `--label` | 화장을 옮긴 사진 1장(1024) | **있음: label에 따라 고정 영어 프롬프트를 코드가 자동으로 넣음** | eyes / lip / 전체(eyes,lip,face) 3가지만 |
| Stable-Makeup | 맨얼굴 사진 + 화장 레퍼런스 사진 + 맨얼굴의 얼굴 구조선(SPIGA) | 화장을 옮긴 사진 1장(512) | **없음**: 레퍼런스 사진의 CLIP 이미지 특징이 텍스트 프롬프트 자리를 대신함 | 없음(얼굴 전체) |

| FPMT (11-23 추가) | 맨얼굴 사진 + 화장 레퍼런스 사진 + 두 사진의 19클래스 얼굴 분할 맵(zllrunning BiSeNet) | 화장을 옮긴 사진 1장(512, 입력을 1.12배 확대·중앙 crop한 화면) | **없음** | 없음(피부·눈썹·눈 주변·입술 영역을 나눠 처리하지만 결과는 얼굴 전체) |

제품 hex를 직접 받는 생성 모델은 없다. 둘 다 "그 제품을 바른 사람 사진"이 있어야 한다.

## 2. MagicMakeup 상세

- **고정 프롬프트** (`prompt.py` `build_prompt`). 사용자가 쓰는 캡션 입력은 없고 label로 셋 중 하나가 골라진다.
  - `lip`: "Apply lipstick from image 2 to image 1. Keeping image 1's identity, facial features, eyes, cheek, complexion, hair, pose, lighting, composition, and background unchanged, no face replacement."
  - `eyes`: "Apply eye shadow, eyeliner, lashes, brows from image 2 to image 1. Keeping … lip, cheek, complexion … unchanged …"
  - `eyes,lip,face`: "Apply eye shadow, eyeliner, lashes, brows, lipstick, blush, cheek painting from image 2 to image 1. Keeping … complexion … unchanged …"
- **label 조합 제한:** 위 3가지만 정상이다. `face` 하나만(블러셔만) 넣으면 기본 분기가 값 3개만 돌려줘서 `test_single.py`의 5개 풀기에서 오류가 난다(코드 읽기 기준, 실행 확인 안 함). 그래서 블러셔는 전체 모드로만 옮길 수 있다.
- **마스크:** README는 label마다 마스크를 따로 만든다(`mask/face` = 얼굴 분할 모델, `mask/eyes`·`mask/lip` = `preprocess/regionmask.py`, MediaPipe). 마스크는 레퍼런스 사진을 그 영역만 남기고 지우는 데(`apply_mask_to_image`)와 어텐션 영역 제한에 쓰인다.
  - **11-20 실행은 `label='lip'`에 얼굴 전체 마스크(`mask/face`)를 넣었다.** README 예시는 전체 모드에만 face 마스크를 보여 주고, lip 마스크를 따로 만드는 절차가 있다. lip 모드에는 lip 마스크가 맞는 입력일 가능성이 있다(가설). 11-20 결과에서 입술 변화가 작았던 것(입술 ΔE00 3.50, 맨얼굴 3.94)과 관련이 있을 수 있다. GPU 재실행으로 확인해야 한다.
- 설정: 1024×1024, 28 steps, guidance 2.5, `model_offload`, seed 0/1/2.

## 3. Stable-Makeup 상세

- `infer_kps.py`: 맨얼굴과 레퍼런스를 512로 줄이고, 맨얼굴에서 SPIGA 얼굴 구조선 이미지를 만든다. `makeup_encoder.generate(id_image=[맨얼굴, 구조선], makeup_image=레퍼런스, guidance_scale=1.6)`.
- `detail_encoder/encoder_plus.py` `generate`: 레퍼런스를 CLIP ViT 이미지 인코더 → resampler로 바꿔 `prompt_embeds`로 넣는다. 텍스트 인코더는 쓰지 않는다.
- 부위 옵션이 없어 레퍼런스의 화장 전체(피부·안경 같은 비화장 특징 포함)가 옮겨진다.
- 설정: 512, 30 steps DDIM, guidance 1.6, fp32, seed 0/1/2.

## 3-1. FPMT 상세 (11-23, 커밋 538fb44)

- 논문: Sun, Xiong, Rong, *FPMT: Fast and precise high-resolution makeup transfer via Laplacian pyramid*, Pattern Recognition 2026. 코드·가중치 github.com/Snowfallingplum/FPMT, CC BY-NC-SA 4.0.
- 입력 준비(`quick_start/dataset.py`): 사진을 573으로 키우고 중앙 512를 자른다. 분할 맵을 7채널(배경, 피부(안경 포함), 눈썹, 눈 주변(눈을 키운 띠), 코, 입술, 목)로 나눈다.
- 모델: 라플라시안 피라미드. 저주파는 작은 인코더·디코더로 화장을 옮기고, 고주파(결)는 맨얼굴 것을 보정해 더한다. L=3, 512 가중치는 파라미터 947,189개, 3.6MB다.
- 공개 코드는 CUDA 전용 두 곳이 있다(`utils.init_net`의 assert, `Lap_Pyramid_Conv.gauss_kernel`의 'cuda'). `research/makeup_gen/run_fpmt.py`가 실행할 때만 CPU 함수로 바꾼다. 저자 예제 25쌍은 PSNR 41~44 dB로 재현됐다.
- 텍스트 입력·부위 선택·hex 입력은 없다. 출력은 원본보다 1.12배 확대된 화면이라 `_srcframe.png`로 원래 위치에 되돌려 평가했다.
- 시간: 노트북 CPU(i5-1135G7) 장당 3.1~4.1 s, 얼굴 분할 0.23 s. 팀 공유의 "42 FPS"는 확인하지 못했다(논문 유료, README에 없음).

## 4. 부위별 비교 가능 여부

| VISHUE 부위 | MagicMakeup | Stable-Makeup | 비고 |
|---|---|---|---|
| 입술 | `lip` | 전체만 | |
| 립 오일·밤 | `lip`(프롬프트는 lipstick) | 전체만 | 광택은 색 지표로 평가 불가 |
| 블러셔 | 전체 모드에만 포함("blush, cheek painting") | 전체만 | 블러셔만 따로 불가 |
| 아이섀도우·아이라이너·마스카라 | `eyes` | 전체만 | 셋을 따로 나눌 수 없음 |
| 눈썹 | `eyes`("brows" 포함) | 전체만 | |
| 하이라이터·쉐딩 | 없음 | 전체만(의도 아님) | MagicMakeup 프롬프트가 complexion 유지를 명시 |
| 파운데이션 | 없음 | 전체만(의도 아님) | 같음. 11-20 D의 피부 미백은 이 특성 |

## 5. VISHUE AR 입력 (`types/index.ts`)

- 부위: `MakeupState` = lip, lipCare, blush, eyeshadow, eyeliner, mascara, highlighter, contour, brow, foundation.
- 부위마다 `ZoneSetting`: `hex`, `intensity`(0~1), `texture`(matte·velvet·glossy·satin·sheer·cream·shimmer), 아이섀도우 `hexTo`(투톤)·`particle`, 립 오일 `care`, 부위별 `geometry`(블러셔 위치·크기·번짐, 쉐딩 jawline/nose, 하이라이터 영역, 라이너 길이·각도·두께, 속눈썹 개수·컬 등), `applicationProfile`.
- 출력은 WebGL 셰이더 층이다. 카메라 픽셀 위에 부위별로 쌓으므로 부위 밖 픽셀은 바뀌지 않는다(11-20 립 실측: 입술 밖 ΔE00 0.00).

## 6. 11-20 보고서에서 고칠 점

- "C MagicMakeup 입력 … 텍스트 입력 없음"은 틀렸다. 사용자가 넣은 텍스트는 없지만 코드가 고정 프롬프트(lip용)를 넣는다.
- C 입력의 마스크가 README의 lip 절차와 다르다(위 2절). 재실행 전까지 C의 립 결과는 "얼굴 마스크로 실행한 값"으로 표시해야 한다.
