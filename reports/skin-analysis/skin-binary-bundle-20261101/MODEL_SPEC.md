# 피부 분석 4모델 번들 사양서

모공·색소침착·주름은 양호/유의 직접 이진 모델이고 피부타입은 기존 ROI 3클래스 모델이다.
입력은 고정 전처리 전의 256×256 RGB 공식 ROI다. 한 얼굴 사진에서 각 부위 ROI를 추출한 뒤 모델별로 사용한다.

| 모델 | ROI | 학습 정답 / 출력 |
|---|---|---|
| 모공 | 좌·우 볼 | 0~2 양호 / 3~5 유의, sigmoid |
| 색소침착 | 이마·좌·우 볼 | 0~2 양호 / 3~5 유의, sigmoid |
| 주름 | 이마·미간·좌·우 눈가 | 0~2 양호 / 3~6 유의, sigmoid |
| 피부타입 ROI | 이마·좌·우 볼 | 건성·중성·지성, softmax |

## 공통 구조와 입력

MobileNetV3-Large, ImageNet1K V2 초기화, Dropout 0.2. 이진 Head는 960→1280→Hardswish→Dropout→1 logit이며 피부타입의 마지막 출력은 3개다.
ROI 256px JPEG RGB → Unsharp radius 1 / 75% / threshold 0 → Contrast ×1.4 → ImageNet mean [0.485,0.456,0.406], std [0.229,0.224,0.225]. 고정 전처리는 입력에 한 번만 적용한다.

## 이진 모델 학습

원본 등급별 제곱근 추가 추출로 매 epoch 원본 전체를 사용한다. 원본 Train 이진 빈도 기준 w=N/(2×n_c) 가중 BCEWithLogitsLoss를 사용한다. 원본 등급은 추가 추출 및 진단용이며 모델은 이진 정답을 직접 학습한다.
Batch 16, head-only 1 epoch 후 전체 미세조정, 최대 100 epoch, patience 10. AdamW+SAM ρ=0.05, weight decay=0.0001. Head-only LR=0.001, 미세조정 Head LR=0.0001 / Backbone LR=0.00001. ReduceLROnPlateau factor=0.5 / patience=2 / min LR=1e-7. 학습 seed=42, Validation Macro-F1 최대, 동률이면 비가중 BCE 최소 checkpoint.
Train 증강은 회전 ±5°, 이동 ±2%, 밝기·대비 ±10%, 채도 ±5%이고 좌우 반전은 사용하지 않았다.
모공의 새 인물 seed42 고정 분할을 세 이진 모델이 공유한다. 0427번은 모공에서만 제외했고 나머지 두 작업에는 원래 Test 소속으로 유지했다.

| 모델 | Train / Valid / Test ROI | best / 종료 epoch | Validation Macro-F1 |
|---|---|---|---:|
| pore | 4092 / 827 / 822 | 24 / 34 | 0.6259 |
| pigmentation | 6153 / 1244 / 1245 | 18 / 28 | 0.8290 |
| wrinkle | 6931 / 1413 / 1410 | 19 / 29 | 0.8553 |

## 피부타입 ROI 모델

기존 선택 checkpoint(best epoch 20 / 종료 30)를 유지했다. Train 4,368 / Validation 874 / Test 852 ROI, 인물 488 / 98 / 95명. 건성·중성·지성의 제곱근 추가 추출과 원본 빈도 α=0.5 가중 cross-entropy를 사용했다. Head/Batch/최대 epoch/patience/AdamW+SAM/LR/Scheduler는 위와 같다. Validation Macro-F1 0.4602, ROI Test Macro-F1 0.4698 / Accuracy 0.4977. 복합성과 심한 건성은 학습 범위에 포함되지 않는다.

피부타입은 이전 인물 분할을 유지하므로 새 이진 모델들과 같은 공통 held-out 평가가 아니다.

## 실행

```powershell
python predict.py --task pore --image pore_roi.jpg
python predict.py --task pigmentation --image pigmentation_roi.jpg
python predict.py --task wrinkle --image wrinkle_roi.jpg
python predict.py --task skin_type_roi --image forehead_roi.jpg --image cheek_roi.jpg
```

이진 출력은 label 0(양호)/1(유의), probability_caution, threshold=0.5다. 피부타입은 복수 ROI의 softmax 평균을 출력한다. 점수는 보정되지 않은 모델 점수다. 0~5/6등급 출력 규격과 다르다.
Python·PyTorch·torchvision·Pillow로 독립 실행하며 원본 프로젝트 import가 필요 없다. 자동 얼굴/ROI 추출 및 Expo 앱 통합은 이 번들의 범위 밖이다.

세부 설정은 [training-setup.json](training-setup.json), 평가는 [통합 성능 문서](INTEGRATED_EVALUATION.md)를 참조한다.
