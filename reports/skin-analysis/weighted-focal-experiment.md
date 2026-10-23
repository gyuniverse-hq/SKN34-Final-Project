# 모공 WFL(Weighted Focal Loss) + AdamW + SAM 실험

## 사전에 고정한 비교

이번 문서에서 WFL은 **Weighted Focal Loss**를 뜻합니다. 직전의 가중 순서형 CDF 손실을
대체하고, **기존 WCE + AdamW + SAM**을 주 비교 기준으로 사용합니다. WCE는 앞선 보고서에서
CE라고 줄여 쓴 weighted cross entropy입니다. WCE+AdamW는 참고 행으로 따로 비교합니다.

WFL은 기존 WCE의 클래스 가중치 `alpha`를 유지하고 Focal 항만 추가합니다:

```text
CE_i = -log(softmax(logits_i)[y_i])  # class weight를 곱하기 전 CE
p_t = exp(-CE_i)
L = sum(alpha[y_i] * (1 - p_t)^gamma * CE_i) / sum(alpha[y_i])
gamma = 2.0
```

`p_t`를 `exp(-weighted_CE)`로 계산하지 않습니다. Focal 항도 함께 미분하며 detach하지 않습니다.
계산은 AMP 안에서도 FP32로 수행합니다. `gamma=0`에서 기존 WCE의 값과 gradient를
회복하는지 검사합니다. 이번에는 gamma 탐색·새 샘플링·새 클래스 가중치를 도입하지 않습니다.

클래스 가중치는 기존 cap 4의 정규화된 inverse-square-root 빈도 가중치입니다.
정규화 전 `sqrt(N/n_grade)`이며, 이후 학습 분포에 대한 가중 평균이 1이 되도록 정규화하고
cap을 적용합니다. 아래 값은 학습 라벨에서만 계산합니다.

| 등급 | 학습 ROI | alpha (WCE와 동일) |
|---|---:|---:|
| 0 | 114 | 2.916177 |
| 1 | 721 | 1.159574 |
| 2 | 2486 | 0.624476 |
| 3 | 519 | 1.366729 |
| 4 | 224 | 2.080378 |
| 5 | 48 | 4.000000 |

### 이전 CB Focal과의 차이

기존 CB Focal은 effective number `((1-beta^n)/(1-beta))`의 역수를 이용해 클래스별
가중치를 정했습니다(beta 0.999). 이번 WFL은 **WCE와 동일한 sqrt 빈도 가중치**를 사용합니다.
과거 CB Focal은 batch 32·AdamW, 이번 WFL은 batch 16·AdamW+SAM이므로, 두 결과를
비교해 alpha 계산 방식 하나의 인과 효과라고 주장하지 않습니다. 주 비교는 WCE+SAM입니다.
공유 Focal 계산부를 사용하되 기존 CB Focal의 값·gradient·가중치가 그대로인지 검사합니다.
두 구현 모두 서로 배타적인 6개 등급의 softmax 방식이며, 원 논문의 전체 detector나
sigmoid one-vs-all 구현을 재현한 것은 아닙니다.

## 공통 조건과 평가

ImageNet V2 ResNet-50 신규 초기화, seed 42, 256px ROI, 물리/유효 batch 16,
head 2 + 전체 미세조정 최대 18 epoch, patience 6, head LR 1e-3 → 1e-4,
backbone LR 1e-5, weight decay 1e-4, 기존 cosine scheduler·AMP·SAM rho 0.05를 유지합니다.
같은 약한 증강·전문의 라벨을 사용하며 기존 피부 가중치에서 이어 학습하지 않습니다.
WCE+SAM 대비 변경은 손실 종류·focal gamma 추가·출력 폴더입니다.

학습 690명/4,112 ROI, 검증 138명/816 ROI. 인물 분리 fingerprint:
`6ac903796d100a2ee4f66e3e1936548dfa618c9b448a90985ff9ffbb0c13d793`.
최종 테스트셋을 조회하지 않고 검증 macro-F1로 checkpoint를 선택합니다.
동률은 공통 unweighted CE로 판정하며 출력층·softmax argmax도 유지합니다.

Accuracy, macro/weighted Precision·Recall·F1, 등급별 지표·혼동행렬, MAE·±1등급 적중률,
4·5등급 pooled 정확 분류 Recall을 같은 FP32 eval mode에서 측정하고 sklearn과 대조합니다.
고등급 pooled Recall은 실제 고등급을 자기 등급으로 정확히 맞힌 비율로, 4↔5 혼동도 오답입니다.
특히 3등급·4등급 Recall과 1명/6 ROI인 5등급의 한계를 함께 기록합니다.

로그 `train_loss`는 WFL 최적화 손실입니다. `valid_loss`와 `train_eval_loss`는 모델 간
공통 진단값인 **unweighted CE**입니다. Focal 손실이 작아진 수치 자체를 성능 향상으로
해석하지 않습니다. 그림은 공통 CE 및 macro-F1을 비교합니다.

같은 검증셋을 반복 사용한 단일 seed·고정 gamma 실험입니다. 통계적 우월성·다른 장비나
새 인물에서의 성능을 확정하지 않습니다. 모공만 학습하고 기존 서비스·추천 묶음·테스트 페이지는
보존합니다. 외부/생성 데이터나 새 라벨을 추가하지 않고 얼굴 사진을 서버에 전송하지 않습니다.

## 재현과 산출물

저장소 루트에서 실행합니다. 기존 실험 폴더는 덮어쓰지 않습니다.

```powershell
uv run --project ml python -m ml.scripts.report_weighted_focal --phase preflight
uv run --project ml python -u -m skin_analysis.smartphone.train --config ml/configs/nia_smartphone_weighted_focal_sam.toml --task pore
uv run --project ml python -m ml.scripts.report_weighted_focal --phase evaluate
uv run --project ml python -m ml.scripts.report_weighted_focal --phase publish
```

후보 체크포인트·export·학습 이력·개별 예측:
`ml/runs/nia-smartphone-weighted-focal-sam-seed-42/`.
개별 예측·인물 ID·이미지는 로컬에만 보존하고 공개 집계·학습 곡선만 Git으로 공유합니다.

참고: [Focal Loss 원 논문](https://arxiv.org/abs/1708.02002),
[Class-Balanced Loss 원 논문](https://arxiv.org/abs/1901.05555).
