# 모공 SAM-AdamW 비교 실험

## 사전에 고정한 조건

기존 CE 배치 16을 기준으로 SAM만 추가합니다. 기반 optimizer는 AdamW를 유지하고,
일반 L2 SAM의 반경 `ρ=0.05`를 고정합니다. ASAM이나 반경 탐색은 이번 범위에 포함하지
않습니다. head와 전체 backbone 미세조정 두 단계 모두 SAM을 사용합니다.

공통 조건은 seed 42, ImageNet V2 ResNet-50 신규 초기화, 가중 CE, 물리/유효 batch 16,
head 2 + 미세조정 최대 18 epoch, patience 6, head LR 1e-3 → 1e-4, backbone LR 1e-5,
weight decay 1e-4, 기존 cosine scheduler·AMP·256px 전처리·약한 증강입니다.
BN 통계 고정이나 layer4 제한을 함께 적용하지 않습니다. 전문의 라벨과 데이터는 유지합니다.
기존 피부 모델을 이어 학습하지 않고, 같은 검증 macro-F1 및 동률 시 unweighted CE로 선택합니다.

인물 분리 fingerprint:
`6ac903796d100a2ee4f66e3e1936548dfa618c9b448a90985ff9ffbb0c13d793`.
학습 690명/4,112 ROI, 검증 138명/816 ROI를 사용하며 최종 테스트셋은 평가하지 않습니다.

## 구현과 평가 기준

같은 증강 배치에서 첫 gradient `g`로 `ε = ρg/(||g||₂+1e-12)`를 만들고, 임시로 `w+ε`에서
두 번째 gradient를 계산합니다. 원래 파라미터를 복사해 정확히 복원한 다음 두 번째 gradient에
global norm 1 clipping을 적용하고 AdamW로 한 번 갱신합니다. weight decay와 scheduler는
기존처럼 각각 한 번 적용됩니다. 두 번째 backward에서 perturbation의 미분은 계산하지 않습니다.

미세조정 첫 forward에서만 BN running 통계를 영구 갱신하고, 두 번째 forward도 학습 배치
통계를 사용하되 running mean/variance/count는 첫 forward 이후 값으로 복원합니다.
head 단계에서는 기존과 같이 backbone과 BN을 동결합니다. AMP는 첫 gradient를 수동으로
unscale하고 두 번째 gradient에서만 `GradScaler.unscale_`을 사용합니다. gradient overflow는
scale을 절반으로 줄여 같은 배치를 재시도하며 파라미터·BN·torch RNG를 복원합니다.
동일한 증강 입력과 stochastic mask를 두 계산에서 재사용합니다.

Accuracy, macro/weighted Precision·Recall·F1, 등급별 지표와 혼동행렬, MAE·±1등급 적중률을
기록합니다. 고등급 Recall은 실제 4·5등급 총 50 ROI 중 **자기 등급으로 정확히 분류한 비율**이며
이진 고등급 검출 Recall과 다릅니다. 지표는 scikit-learn과 대조하고 학습 지표는 증강 없는 FP32
eval mode로 측정합니다. 5등급 검증은 1명/6 ROI이므로 작은 변화도 일반화해 해석하지 않습니다.

학습량은 같은 최대 epoch로 제한하지만 SAM은 배치당 forward/backward가 두 번이므로
동일 계산량 비교는 아닙니다. 한 seed·고정 반경의 비교이므로 SAM 전체의 유효성을 확정하거나
부정할 수 없습니다. 기존 모델·추천 묶음·테스트 페이지는 보존하고 후보는 별도로 저장합니다.

## 재현

저장소 루트에서 실행합니다. 기존 run은 덮어쓰지 않습니다.

```powershell
uv run --project ml python -m ml.scripts.report_sam_experiment --phase preflight
uv run --project ml python -u -m skin_analysis.smartphone.train --config ml/configs/nia_smartphone_sam.toml --task pore
uv run --project ml python -m ml.scripts.report_sam_experiment --phase evaluate
uv run --project ml python -m ml.scripts.report_sam_experiment --phase publish
```

후보 가중치·체크포인트·학습 이력·개별 예측은 `ml/runs/nia-smartphone-sam-seed-42/`에
로컬 저장합니다. 이 보고서와 집계 JSON·학습 곡선만 Git으로 공유합니다.

참고: [SAM 원 논문](https://arxiv.org/abs/2010.01412),
[PyTorch AMP 예제](https://docs.pytorch.org/docs/2.14/notes/amp_examples.html).
AMP 문서 링크는 현재 공개 문서이며 실제 실행 버전은 lockfile의 torch 2.13.0입니다.
