# 스마트폰 모공 Class-Balanced Focal Loss 비교

## 목적과 사전 조건

기존 스마트폰 세 항목 모델과 테스트 페이지를 보존하고, **모공 모델 하나**를 별도로
학습합니다. 기존 모델을 이어 학습하지 않고 같은 ImageNet V2 초기화·seed 42에서 시작합니다.
이 문서의 설정은 후보 성능을 보기 전에 고정했습니다.

- 데이터: 기존 fingerprint `6ac903796d100a2ee4f66e3e1936548dfa618c9b448a90985ff9ffbb0c13d793`.
  모공 학습 690명/4,112 ROI, 검증 138명/816 ROI. 증강·256px 전처리·읽기 전용 캐시는 동일합니다.
- 모델·예산: ResNet-50, batch/effective batch 32, head 2 + backbone 최대 18 epoch,
  같은 학습률·optimizer·scheduler·AMP·patience 6을 유지합니다.
- 기준 모델: `ml/runs/nia-smartphone-seed-42/pore/inference.bin`, SHA-256
  `462b54a3af361843dee2ccea6a8dfb6661e60b9c13e2bbe1a1e7fec488c314b2`.
  검증 macro-F1로 선택한 epoch 18이며 모든 원본 학습 파일을 보존합니다.
- 변경: 기존 제곱근 빈도 가중 CE를 **softmax 다중분류형 CB Focal**로 교체합니다.
  `beta=0.999`, `gamma=2`를 고정하고 기존 제곱근 가중치·별도 균형 sampler는 사용하지 않습니다.
- CB 가중치: `alpha_c = (1-beta)/(1-beta^n_c)`를 클래스 평균 1로 정규화합니다.
  `n_c`는 학습셋만의 등급별 ROI 수 `[114,721,2486,519,224,48]`입니다.
- 손실: `sum(alpha_y * (1-p_y)^gamma * CE) / sum(alpha_y)`.
  FP16 autocast 중에도 손실은 FP32로 계산합니다. `gamma=0`에서 weighted CE와
  손실·gradient가 일치하는지 시험합니다. 분모는 배치의 정답 클래스 가중치 합입니다.
- 원 논문의 공개 구현은 sigmoid one-vs-all입니다. 본 실험은 서로 배타적인 등급에
  softmax를 사용하는 변형이며 저자 구현의 정확한 재현이라고 주장하지 않습니다.
- epoch 선택은 기존과 같은 검증 macro-F1, 동률일 때 unweighted 검증 CE입니다.
  손실 함수와 클래스 보정 방식을 함께 바꾸므로 Focal 단독 효과를 분리한 실험은 아닙니다.

## 비교와 확대 기준

같은 검증셋에서 두 모델을 평가하고 Accuracy·macro/weighted Precision·Recall·F1,
등급별 지표·혼동행렬·MAE·±1등급 적중률을 기록합니다. scikit-learn으로 지표를 독립 대조합니다.

색소침착·주름으로 확대할 조건은 다음 세 가지를 모두 만족하는 것입니다.

1. 검증 macro-F1 개선
2. 정확 일치율이 기존보다 낮아지지 않음
3. 모공 4·5등급 정답 예측 수를 해당 두 등급 실제 ROI 수로 나눈 pooled Recall 개선

마지막 값은 확대 판단을 위한 등급별 Recall 집계이며 전체 정확도와 구분합니다.
조건이 충족되지 않으면 모공 후보를 보존해 실패 양상만 기록하고 확대하지 않습니다.
최종 평가셋을 반복 확인해 파라미터를 바꾸거나 현 테스트 페이지를 자동 교체하지 않습니다.
검증 성능이 좋아도 새 인물에 대한 독립 최종 성능을 보증하지 않습니다.

모공 고등급의 실제 인물 수가 적고 원본 사진에서 반복된 각도·양쪽 볼이 여러 ROI를 만듭니다.
증강·손실 보정은 새로운 인물 정보를 추가하지 않습니다. 자동 검수는 캐시 해시, bbox,
등급 범위와 분할 정합성을 확인하며 임상 전문가의 라벨 재판독을 대체하지 않습니다.

## 실행과 보존

저장소 루트에서 실행합니다. 데이터·기존 가중치·서비스 설정은 수정하지 않습니다.

```powershell
uv run --project ml python -m skin_analysis.smartphone.focal_compare --baseline-only
uv run --project ml python -m skin_analysis.smartphone.train --config ml/configs/nia_smartphone_cb_focal.toml --task pore
uv run --project ml python -m skin_analysis.smartphone.focal_compare
uv run --project ml python -m skin_analysis.smartphone.focal_compare --publish
```

새 산출물은 `ml/runs/nia-smartphone-cb-focal-seed-42/`에 저장합니다.
`pore/{best.pt,last.pt,inference.bin,history.json,summary.json}`와 검증 예측은 Git에서 제외합니다.
공유 보고서는 집계 수치만 포함합니다. 기존 스마트폰 보고서·가중치·추천용 묶음은 보존합니다.

참고: [Focal Loss](https://arxiv.org/abs/1708.02002),
[Class-Balanced Loss](https://arxiv.org/abs/1901.05555).
