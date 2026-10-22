# 스마트폰 전용 세 항목 분류 모델 학습

## 목적과 상태

기존 NIA 가중치와 별도로 스마트폰 사진의 **모공·색소침착·주름 분류 모델 3개**를
학습합니다. 여드름 이진 분류 모델은 그대로 사용합니다. 수분·탄력·처짐·입술 건조와
회귀 모델은 이번 학습 대상에 포함하지 않습니다.

현재 이 문서는 실행 계획과 재현 방법입니다. 학습·최종 평가가 끝나면 실제 결과와
가중치 SHA-256을 추가합니다. 계획만으로 학습 완료나 서비스 반영을 의미하지 않습니다.

## 고정한 실험 조건

- ResNet-50 세 개를 각각 ImageNet V2 사전학습 가중치에서 시작합니다. 기존 NIA 가중치를
  초기화·전이학습·재개에 사용하지 않습니다. 기존 파일과 모델 묶음은 비교·복원용으로 보존합니다.
- 모공·색소침착은 0~5등급, 주름은 0~6등급입니다. 부위 매핑과 원래 등급 순서를 유지합니다.
- AI-Hub 원본 TS/VS 사진 및 TL/VL 라벨 중 스마트폰(`Equ_03`, JSON `device=2`)만 선택합니다.
  원본 ZIP과 이미지를 수정하지 않으며 새로운 Crop은 Git에서 제외한 실험 폴더에 저장합니다.
- 공식 정사각형 bbox Crop → OpenCV 256px/JPEG → RGB → ImageNet 정규화를 사용합니다.
  학습에만 ±5도 회전·2% 이동·약한 밝기/대비/채도 변화를 적용하고 좌우 반전은 사용하지 않습니다.
- 모든 사진의 인물 ID를 그룹으로 삼습니다. 바이트 또는 디코딩 픽셀이 같은 사진이 서로 다른
  인물 ID에 있으면 동일 그룹으로 연결합니다. 인물·원본 사진이 분할 사이에 중복되지 않아야 합니다.
- `StratifiedGroupKFold`, seed 42, 7개 fold 중 5개 학습·1개 검증·1개 최종 평가입니다.
  층화 라벨은 항목과 등급의 조합입니다. 이는 기존 공식 분할·논문 분할과 다른 새 연구 분할입니다.
- 전체 항목의 모든 등급이 각 분할에 존재하는지 검사합니다. 원본 라벨 누락과 유효하지 않은
  bbox는 집계해 공개하며, 누락된 원본 사진이나 모호한 라벨은 오류로 중단합니다.
- head만 2 epoch 학습한 뒤 전체 backbone을 최대 18 epoch 미세조정합니다.
  head 단계에서는 backbone BatchNorm의 통계도 고정합니다.
- AdamW, batch/effective batch 32, head LR 0.001, 미세조정 head LR 0.0001,
  backbone LR 0.00001, weight decay 0.0001, cosine scheduler, AMP를 사용합니다.
  클래스 가중치는 학습셋 빈도의 역제곱근으로 정하고 평균 정규화·상한 4를 적용합니다.
  중복 보정이 되지 않도록 별도 균형 샘플러는 사용하지 않습니다.
- 검증 macro-F1이 가장 높은 가중치를 선택하고, 동률이면 검증 Cross-Entropy가 낮은 것을
  선택합니다. 전체 backbone 단계에서 6 epoch 연속 개선되지 않으면 종료합니다.
  최종 평가셋으로 epoch·학습률·가중치·임계값을 고르지 않습니다.

## 실행과 산출물

저장소 루트에서 실행하며 Windows AMD64/Python 3.12 환경은 `ml/uv.lock`으로 고정합니다.
지정 GPU UUID는 RTX 4070 Ti SUPER 16GB입니다.

```powershell
uv run --project ml python -m skin_analysis.smartphone.prepare
uv run --project ml python -m skin_analysis.smartphone.cache
uv run --project ml python -m skin_analysis.smartphone.train
uv run --project ml python -m skin_analysis.smartphone.evaluate
```

데이터 준비 결과는 `ml/runs/nia-smartphone-data-v1-seed-42/`, 모델은
`ml/runs/nia-smartphone-seed-42/{pore,pigmentation,wrinkle}/`에 저장합니다.
동일 실험 폴더를 새 학습으로 덮어쓰지 않습니다. 재개는 한 항목을 명시합니다.

```powershell
uv run --project ml python -m skin_analysis.smartphone.train --task pore --resume ml/runs/nia-smartphone-seed-42/pore/last.pt
```

각 항목의 `best.pt`는 검증 기준으로 선택한 체크포인트, `last.pt`는 optimizer·scheduler·
scaler·RNG를 포함한 재개 파일, `inference.bin`은 추론용 파일입니다. 초기 가중치 해시,
스마트폰 데이터 fingerprint, 코드 해시와 라이브러리 버전을 함께 기록합니다.

최종 평가에서는 Accuracy, macro/weighted Precision·Recall·F1, 등급별 지표·혼동행렬과
기존 등급 오차 지표인 MAE·±1등급 정확도를 계산합니다. 같은 새 평가 ROI에서 기존 NIA
모델과 학습셋 최빈 등급 상수도 비교합니다. 개별 예측과 인물 ID는 Git에 포함하지 않습니다.

평가 후 다음 명령으로 로컬 연구 설정의 세 항목과 새 추천용 모델 묶음을 연결합니다.
기존 설정 사본·기존 추천 묶음·여드름 가중치는 보존합니다. 이 명령 자체는 학습 성능이
운영 배포에 충분하다는 판정이 아닙니다.

```powershell
uv run --project ml python -m skin_analysis.smartphone.evaluate --activate
```

## 해석 시 주의점

- 기존 NIA 모델은 새 평가 인물을 DSLR 학습에서 보았을 수 있습니다. 동일 ROI 비교는
  추론 결과 비교이며, 두 실험 모두 완전히 독립적인 학습 조건이었다는 뜻은 아닙니다.
- 과거 전체 평가와 분할·표본이 다르므로 그 보고서 수치와 단순 차감하지 않습니다.
- 원본 스마트폰 촬영도 통제된 조건입니다. 임의 셀카·자동 ROI의 정확도는 별도 검증 대상입니다.
- 단일 seed 실험이며, 희소 등급과 ROI 수보다 적은 실제 인물 수를 함께 확인해야 합니다.
- 등급별 수치는 등간격 생리 측정값이 아닙니다. softmax 점수도 보정된 확률·중증도가 아닙니다.
- 여드름은 이번에 재학습하지 않으며 기존 합성 데이터 기반 성능의 한계가 그대로 남습니다.
