# 모공 순서형 CDF 손실 + AdamW + SAM 실험

## 사전에 고정한 비교

직전 **가중 CE + AdamW + SAM**을 주 비교 기준으로 사용하고 손실함수만
**가중 순서형 CDF 손실**로 교체합니다. 별도 보존된 CE+AdamW는 참고 행으로 비교합니다.
CORAL 실험을 반복하지 않고, 같은 ResNet-50의 6개 softmax 출력과 argmax 판정을 유지합니다.
전문의 라벨과 기존 인물 분리·ROI·증강은 유지하며 외부/생성 데이터는 추가하지 않습니다.

이번 손실은 비정규화 Ranked Probability Score(RPS), 즉 등급별 누적분포의 제곱 차이를
합산하는 방식입니다. 예측 확률을 `p`, 정답 등급을 `y`라고 할 때:

```text
CDF_p(k) = sum(p_j, j <= k)
CDF_y(k) = 1[y <= k]
L_i = sum((CDF_p(k) - CDF_y(k))^2, k=0..K-2)
L = sum(weight[y_i] * L_i) / sum(weight[y_i])
```

기존 inverse-square-root 빈도 가중치와 cap 4를 그대로 사용합니다. CE 항을 혼합하거나
추가 계수를 탐색하지 않습니다. 정규화 RPS의 `1/(K-1)` 상수는 적용하지 않습니다.
각 경계의 비용은 1로 둡니다. 확률이 하나의 오답에 집중될 때 1등급 차이의 손실은 1,
4등급 차이는 4입니다. 이것은 등급 번호에 수치 회귀 MSE를 적용하는 방식이 아니며,
실제 피부 심각도가 등급마다 같은 물리량만큼 증가한다는 가정도 아닙니다.
CDF 손실의 softmax 포화 구간에서는 gradient가 작아질 수 있으며 CE와 수치 스케일도 다릅니다.

공통 조건: ImageNet V2 신규 초기화, seed 42, 256px, 물리/유효 batch 16, head 2 +
전체 미세조정 최대 18 epoch, patience 6, head LR 1e-3 → 1e-4, backbone LR 1e-5,
weight decay 1e-4, 기존 cosine scheduler·AMP·SAM rho 0.05입니다. SAM의 두 계산·BN
통계 복원·AMP 재시도 구현도 직전 CE+SAM과 같습니다. 기존 피부 가중치에서 이어 학습하지 않습니다.

학습 690명/4,112 ROI, 검증 138명/816 ROI. 분리 fingerprint:
`6ac903796d100a2ee4f66e3e1936548dfa618c9b448a90985ff9ffbb0c13d793`.
최종 테스트셋은 평가하지 않고, 같은 검증 macro-F1로 선택하며 동률이면 unweighted CE로
판정합니다. 손실만 비교하기 위해 checkpoint 선택/추론 규칙도 유지합니다.

## 평가와 산출물

Accuracy, macro/weighted Precision·Recall·F1, 등급별 지표·혼동행렬·MAE·±1등급 적중률,
4·5등급 pooled 정확 분류 Recall을 같은 FP32 eval mode에서 비교하고 sklearn과 대조합니다.
특히 직전 SAM에서 나빠진 3등급 Recall과 여전히 낮은 4·5등급 Recall을 함께 확인합니다.
고등급 pooled Recall은 4↔5 혼동도 오답으로 셉니다. 5등급 검증은 1명/6 ROI입니다.

학습 로그 `train_loss`는 각 모델의 실제 가중 학습 손실입니다. `valid_loss`와
`train_eval_loss`는 공통 진단값인 **unweighted CE**이며 새 모델의 최적화 목적과 다릅니다.
학습 곡선은 이 공통 CE와 macro-F1을 사용합니다. 서로 다른 손실의 원시 크기를 비교해
일반화 차이를 판단하지 않습니다. 같은 최대 epoch의 비교이며 동일 계산량 보장은 없습니다.

기존 서비스 설정·추천 묶음·모든 기존 모델은 해시로 보존하고 후보는 별도 저장합니다.
실제 사진은 로컬에서만 읽습니다. 개별 예측·인물 ID·사진은 Git으로 공유하지 않습니다.
단일 seed·고정 손실의 결과이며 같은 검증셋의 반복 사용으로 선택 편향이 생길 수 있습니다.
이번 실험으로 순서형 손실 전체의 우열이나 최종 배포 성능을 확정하지 않습니다.

저장소 루트에서 실행합니다:

```powershell
uv run --project ml python -m ml.scripts.report_ordinal_loss --phase preflight
uv run --project ml python -u -m skin_analysis.smartphone.train --config ml/configs/nia_smartphone_ordinal_cdf_sam.toml --task pore
uv run --project ml python -m ml.scripts.report_ordinal_loss --phase evaluate
uv run --project ml python -m ml.scripts.report_ordinal_loss --phase publish
```

로컬 산출물: `ml/runs/nia-smartphone-ordinal-cdf-sam-seed-42/`.
기존 폴더는 덮어쓰지 않습니다. 테스트 페이지 교체나 다른 항목 확대는 자동 진행하지 않습니다.

참고: [Squared EMD 손실](https://arxiv.org/abs/1611.05916),
[순서형 CDF 제곱 손실 수식](https://link.springer.com/article/10.1007/s00357-021-09406-4).
여기서는 위에 명시한 CDF 수식만 구현하며 논문의 다른 거리행렬 학습이나 전체 실험을 재현하지 않습니다.
