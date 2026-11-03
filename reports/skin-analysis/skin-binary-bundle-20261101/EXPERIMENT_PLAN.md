# 색소침착·주름 직접 이진 학습 및 4모델 번들 준비

2026-11-01. 현재 상태는 **색소침착·주름 학습 및 최종 Test 평가 완료, 4모델 번들 검증 완료**이다.

## 학습 대상과 정답

| 모델 | 처리 | 양호(0) | 유의(1) | 입력 ROI |
|---|---|---|---|---|
| 모공 | 이번 고정 전처리 이진 checkpoint 유지(best epoch 24) | 0~2등급 | 3~5등급 | 좌·우 볼 |
| 색소침착 | ImageNet에서 새 직접 이진 학습 | 0~2등급 | 3~5등급 | 이마·좌·우 볼 |
| 주름 | ImageNet에서 새 직접 이진 학습 | 0~2등급 | 3~6등급 | 이마·미간·좌·우 눈가 |
| 피부타입 ROI | 기존 checkpoint 유지 | 건성·중성·지성 3클래스 softmax | 해당 없음 | 이마·좌·우 볼 |

원본 등급은 추가 추출과 등급별 분석에 보존한다. 색소침착·주름의 학습 손실은 이진 정답을 직접 사용한다. 주름은 6등급도 존재하므로 3~6등급을 모두 유의로 묶는다.

## 학습 설정

| 항목 | 값 |
|---|---|
| 실행 장비 | 로컬 RTX 4070 Ti SUPER, 기존 GPU UUID 지정 |
| Backbone / 초기 가중치 | MobileNetV3-Large / ImageNet1K V2 |
| Head | 960 → 1280 → Hardswish → Dropout(0.2) → 1 logit → sigmoid |
| Batch / 최대 epoch / patience | 16 / 100 / 10 |
| 동결 | Head-only 1 epoch 후 전체 미세조정 99 epoch 이내 |
| Optimizer | AdamW + SAM, ρ=0.05, weight decay=0.0001 |
| LR | Head-only 0.001 → 미세조정 Head 0.0001 / Backbone 0.00001 |
| Scheduler | ReduceLROnPlateau, Validation Macro-F1 최대화, factor 0.5, patience 2, threshold 0.0001, min LR 1e-7 |
| Loss | 원본 Train 이진 빈도 역수 가중 BCEWithLogitsLoss |
| 가중치 정의 | `w_c = N / (2 × n_c)`; 모공 이진 실험과 동일. 예전 등급 Huber의 α=0.5 가중치를 추가하지 않음 |
| Checkpoint | Validation 이진 Macro-F1 최대, 동률이면 비가중 BCE 최소 |
| 학습 seed / 분할 seed | 42 / 42 |
| 고정 전처리 | 공식 정사각형 256px JPEG ROI, Unsharp radius 1 / 75% / threshold 0 → Contrast ×1.4 → ImageNet 정규화 |
| Train 무작위 증강 | 회전 ±5°, 이동 ±2%, 밝기·대비 ±10%, 채도 ±5%, 좌우 반전 없음 |
| 입력 캐시 | 위 고정 전처리를 한 번 적용한 기존 `pixels-fixed.npy` 재사용. 학습에서 Unsharp/Contrast 재적용 없음 |
| DataLoader | train worker 1, eval worker 0, pin_memory, 학습 AMP. 고정 전처리를 epoch마다 CPU에서 반복하지 않음 |
| 추론 | sigmoid ≥0.5이면 유의, 미만이면 양호. 원본 등급을 복원하지 않음 |

## 데이터와 분할

실제 스마트폰 원본의 정면·좌측·우측 사진에서 얻은 부위별 ROI를 사용한다. 합성 이미지와 10만건 사전 증강 데이터는 포함하지 않는다.

모공의 새 사람 단위 seed-42 분할을 공유한다. 이 기준 분할은 모공 원본 등급으로 만든 StratifiedGroupKFold 7개 중 Train 5 / Validation 1 / Test 1인 고정 분할이며, 이번 실험은 7회 교차검증이 아니다. 색소침착·주름을 별도의 stratify로 다시 나누지 않고 같은 인물이 세 모델 사이에서도 같은 분할에 속하게 한다.

제외 목록의 적용 범위는 모공 0427번 ROI뿐이다. 0427번은 색소침착·주름에서 원래 Test 소속으로 유지하므로 이 두 작업은 총 965명이다. 모공은 제외 후 964명이다. 세 작업을 합쳐 subject/group/원본 사진 hash/pixel hash가 분할 간 겹치지 않는지 확인한다.

| 모델 | Split | 인물 | ROI | 양호 / 유의 | 원본 등급별 ROI |
|---|---|---:|---:|---|---|
| 색소침착 | Train | 687 | 6,153 | 4,162 / 1,991 | 531 / 2,215 / 1,416 / 1,304 / 485 / 202 |
| 색소침착 | Validation | 139 | 1,244 | 881 / 363 | 108 / 478 / 295 / 265 / 77 / 21 |
| 색소침착 | Test | 139 | 1,245 | 867 / 378 | 108 / 405 / 354 / 254 / 76 / 48 |
| 주름 | Train | 687 | 6,931 | 4,414 / 2,517 | 720 / 2,567 / 1,127 / 959 / 524 / 588 / 446 |
| 주름 | Validation | 139 | 1,413 | 910 / 503 | 127 / 523 / 260 / 202 / 103 / 113 / 85 |
| 주름 | Test | 139 | 1,410 | 913 / 497 | 141 / 537 / 235 / 204 / 100 / 72 / 121 |

## 샘플링·가중치

각 epoch에서 원본 Train을 전부 사용한 후 희소 원본 등급을 제곱근 기준으로 추가 추출한다. 원본 등급 g의 총 노출 횟수는 `ceil(sqrt(n_g × 최대 등급 표본 수))`이며, 추가분에는 같은 강도의 결정적 무작위 증강을 적용한다. 배치는 남아 있는 등급을 최대한 다양하게 포함한다. 균등 노출 방식은 아니다.

| 모델 | 원본 수 | 0등급부터의 epoch 노출 횟수 | epoch 총 노출 | SAM 업데이트 | 양호 / 유의 Loss 가중치 |
|---|---:|---|---:|---:|---|
| 색소침착 | 6,153 | 1,085 / 2,215 / 1,771 / 1,700 / 1,037 / 669 | 8,477 | 530 | 0.7392 / 1.5452 |
| 주름 | 6,931 | 1,360 / 2,567 / 1,701 / 1,569 / 1,160 / 1,229 / 1,070 | 10,656 | 666 | 0.7851 / 1.3768 |

## 기록·평가·보고서

각 epoch마다 weighted Train loss, 원본 전체 Train·Validation의 Accuracy/Macro Precision/Recall/F1·비가중 BCE, 양호·유의 클래스별 P/R/F1, 혼동행렬, 원본 등급별 유의 예측률, 4등급 이상 놓침률, LR, 노출 수, SAM 업데이트 수, 소요 시간을 기록한다. 0~2등급의 유의 예측률은 오탐률이며 3등급 이상에서는 유의 Recall이다.

Test 추론은 학습 종료 후 Validation에서 고른 checkpoint에 대해 명시적인 `evaluate` 명령으로 한 번 수행한다. Test 결과로 checkpoint나 임계값을 바꾸지 않는다. 학습 곡선에는 정수 epoch를 표시하고 Train/Validation 곡선, loss, 원본 등급별 분석을 보고서에 포함한다. 모델마다 원본 등급 수가 다르므로 주름의 6등급도 분석한다.

## 번들 구성

완성 번들은 `ml/runs/skin-binary-bundle-20261101/bundle/`에 있다. 4개 모델의 최소 추론 가중치, SHA-256 manifest, 독립 실행 추론기, 상세 사양서, 모델별 보고서·그래프와 통합 성능 문서를 포함한다. 동일한 번들을 `bundle.zip`으로 압축했고, 가중치 일치와 추론 출력 형태를 검증했다.

```text
bundle/
  weights/
    pore.pt                 # 새 분할 + 고정 전처리 직접 이진 모델
    pigmentation.pt         # 이번에 새로 학습할 직접 이진 모델
    wrinkle.pt              # 이번에 새로 학습할 직접 이진 모델
    skin_type_roi.pt        # 기존 피부타입 모델
  manifest.json             # 가중치 준비 완료 후에만 생성
  bundle-plan.json
  predict.py
  MODEL_SPEC.md
  INTEGRATED_EVALUATION.md
```

기존 피부타입은 이전 인물 분할로 학습됐다. 네 모델 전체가 동일한 공통 held-out 인물 평가를 통과했다고 표시하지 않는다. 각 모델 지표를 같은 문서에 모으며 서로 다른 정답의 정확도를 임의로 합치지 않는다. 한 얼굴 사진에서 모델별로 필요한 ROI는 다르다. 입력은 고정 전처리 전의 256px ROI이고 번들 실행기에서 전처리를 한 번 적용한다.

## 실행 순서

재현 학습에 사용할 명령은 아래와 같다. 이번 실험은 실행을 마쳤으며 결과물 경로는 문서 아래에 기록했다.

```powershell
& .\ml\.venv\Scripts\python.exe ml/experiments/skin-binary-bundle-20261101/experiment.py setup
& .\ml\.venv\Scripts\python.exe ml/experiments/skin-binary-bundle-20261101/bundle.py prepare

# 모든 학습이 끝난 뒤 최종 Test 평가와 번들 생성
& .\ml\.venv\Scripts\python.exe ml/experiments/skin-binary-bundle-20261101/experiment.py train --task all
& .\ml\.venv\Scripts\python.exe ml/experiments/skin-binary-bundle-20261101/experiment.py evaluate --task all
& .\ml\.venv\Scripts\python.exe ml/experiments/skin-binary-bundle-20261101/bundle.py build
```


## 실행 결과

| 모델 | 선택 epoch / 종료 epoch | Validation Macro-F1 | Test Macro-F1 | Test Accuracy | Test 유의 Recall |
|---|---:|---:|---:|---:|---:|
| 모공(고정 전처리 기준) | 24 / 34 | 0.6259 | 0.6459 | 0.7336 | 0.6139 |
| 색소침착 | 18 / 28 | 0.8290 | 0.8030 | 0.8217 | 0.8466 |
| 주름 | 19 / 29 | 0.8553 | 0.8724 | 0.8809 | 0.8853 |
| 피부타입 ROI(기존 모델) | 20 / 30 | 0.4602 | 0.4698 | 0.4977 | 해당 없음 |

색소침착과 주름은 Macro-F1 기준으로 선택한 Validation checkpoint를 Test에 한 번 평가했다. Test 결과는 모델·threshold 선택에 사용하지 않았다. 색소침착은 Test macro-F1 0.8030 (양호/유의 Recall 0.8108/0.8466), 주름은 0.8724 (0.8784/0.8853)였다. 두 모델 모두 Train 지표가 Validation보다 높은 학습 곡선을 보여 과적합 간격을 보고서에 남겼다.

번들 상태: `complete`. 모델 파일은 최소 추론 가중치만 담았고 원본 데이터는 포함하지 않는다. `EXPORT_VERIFICATION.json`은 네 가중치의 SHA-256과 source tensor 일치, 출력 shape 및 독립 추론기 parity 검증이 통과했음을 기록한다.
