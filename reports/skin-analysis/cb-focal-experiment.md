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

## 실행 결론과 적용 판단

2026-10-23 실행 완료. 최대 20 epoch 중 15 epoch에서 patience 6에 따른 조기 종료가
발생했고, 사전에 정한 검증 macro-F1 기준으로 **epoch 9**를 선택했습니다.
초기 head 학습 epoch 2의 Accuracy가 더 높더라도 선택 기준을 사후 변경하지 않았습니다.

**이번 설정의 CB Focal은 기존 모공 모델을 대체하지 않습니다.** 정확 일치율은
55.64% → 54.29%(-1.35%p), macro-F1은 31.42% → 30.89%(-0.53%p)로 하락했습니다.
4·5등급 pooled Recall은 16% → 20%로 올랐지만, 세 가지 확대 조건 중 두 가지를
충족하지 못해 색소침착·주름 학습으로 확대하지 않았습니다. 여드름도 이번 학습 대상이 아닙니다.

고등급 개선은 실제 50 ROI 중 정확히 맞힌 수가 8개 → 10개로 늘어난 결과입니다.
4등급 Recall은 18.18% → 22.73%로 올랐지만 Precision은 23.53% → 17.54%로
낮아졌습니다. 5등급은 두 모델 모두 6 ROI 중 정답이 0개입니다. 따라서 심한 상태를
안정적으로 구분하게 되었다고 해석할 수 없습니다. 3등급 Recall도 11.65% → 5.83%로
낮아졌습니다. 0등급 F1 개선 등 부분적인 이득은 있으나 전체 등급 성능 개선은 확인되지 않았습니다.

| 추가 집계 | 기존 CE | CB Focal |
|---|---:|---:|
| weighted Precision | 53.00% | 51.00% |
| weighted Recall | 55.64% | 54.29% |
| weighted F1 | 53.96% | 52.26% |
| MAE (등급 번호) | 0.5331 | 0.5723 |
| unweighted 검증 CE | 1.0859 | 1.1437 |

±1등급 적중률도 92.16% → 90.07%로 낮아졌습니다. MAE는 등급 번호 사이의 거리이며
물리적 피부 측정 단위로 해석하지 않습니다. 학습 손실은 목적 함수가 다르므로 두 모델의
`train_loss` 숫자를 직접 비교하지 않습니다. 혼동행렬과 모든 원시 집계 수치는
[집계 JSON](cb-focal-experiment.metrics.json)에 있습니다.

이번 결과는 seed 42 한 번의 검증 비교입니다. 통계적 유의성이나 CB Focal 전반의
효과 부재를 입증한 결과는 아닙니다. 손실과 클래스 보정 방식을 함께 바꿨으므로
어느 요소가 변화의 원인인지도 분리할 수 없습니다. 검증 후보를 선택하는 데 사용한
동일 검증셋의 수치이며, 이번 실험에서는 최종 평가셋을 새로 평가하지 않았습니다.

### 보존과 검증

- 후보 가중치·학습 이력·검증 예측은 별도 실험 폴더에 보존했습니다.
- 기존 세 항목 가중치, 추천용 묶음 manifest, 테스트 페이지 서비스 설정 등
  총 5개 파일의 실행 전후 SHA-256이 모두 일치했습니다. 테스트 페이지는 기존 모델을 유지합니다.
- 후보 `inference.bin`은 기존 추론 엔진에서 SHA-256 확인과 strict 로딩을 통과했으며,
  로컬 검증 입력으로 유한한 6개 등급 출력을 확인했습니다. 이미지 전송은 하지 않았습니다.
- 모든 비손실 학습 조건·초기화·데이터 fingerprint·패키지 버전을 기존 체크포인트와
  대조했습니다. Accuracy·혼동행렬·macro/weighted Precision·Recall·F1은
  scikit-learn 계산과 일치했습니다.
- ML 테스트 84개(신규 손실·비교 조건 테스트 17개 포함), ML Ruff 검사 통과.
  `npm run check -- -- --runInBand`의 typecheck·lint·앱 테스트 48개 통과.

## 실제 비교 결과

항목 `pore`, 검증 인물 138명. 최종 평가셋은 이번 비교에 사용하지 않았습니다.

| 모델 | 선택 epoch | Accuracy | macro Precision | macro Recall | macro-F1 | ±1등급 | 고등급 Recall |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 18 | 55.64% | 30.26% | 35.28% | 31.42% | 92.16% | 16.00% |
| candidate | 9 | 54.29% | 29.43% | 34.07% | 30.89% | 90.07% | 20.00% |

### 등급별 비교

| 모델 | 등급 | 실제 ROI | 예측 ROI | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 0 | 21 | 44 | 36.36% | 76.19% | 49.23% |
| baseline | 1 | 144 | 124 | 35.48% | 30.56% | 32.84% |
| baseline | 2 | 498 | 538 | 69.52% | 75.10% | 72.20% |
| baseline | 3 | 103 | 72 | 16.67% | 11.65% | 13.71% |
| baseline | 4 | 44 | 34 | 23.53% | 18.18% | 20.51% |
| baseline | 5 | 6 | 4 | 0.00% | 0.00% | 0.00% |
| candidate | 0 | 21 | 34 | 44.12% | 71.43% | 54.55% |
| candidate | 1 | 144 | 128 | 34.38% | 30.56% | 32.35% |
| candidate | 2 | 498 | 545 | 67.52% | 73.90% | 70.57% |
| candidate | 3 | 103 | 46 | 13.04% | 5.83% | 8.05% |
| candidate | 4 | 44 | 57 | 17.54% | 22.73% | 19.80% |
| candidate | 5 | 6 | 6 | 0.00% | 0.00% | 0.00% |

### 가중치

- baseline: `462b54a3af361843dee2ccea6a8dfb6661e60b9c13e2bbe1a1e7fec488c314b2`
- candidate: `8b3234826442ea2d0be34c4b829a358af83784482bcf70099ed53097c19b4d34`

사전에 정한 확대 조건 충족: **False**.
이 결과는 검증셋 비교이며 독립 최종 성능 추정이 아닙니다.
