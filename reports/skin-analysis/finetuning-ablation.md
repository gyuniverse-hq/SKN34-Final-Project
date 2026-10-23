# 모공 BN 통계 고정·부분 미세조정 분리 실험

## 사전에 고정한 비교

기존 CE 배치 16을 기준으로 두 요인을 각각 변경합니다. 모공 모델만 학습하고,
전문의 원본 라벨·데이터·증강은 유지합니다. 외부/생성 데이터는 추가하지 않습니다.

| 조건 | 미세조정 대상 파라미터 | 미세조정 중 BN 통계 |
|---|---|---|
| 기존 CE 배치 16 | 전체 network | 전체 갱신 |
| 실험 1: BN 통계 고정 | 전체 network | 전체 고정 |
| 실험 2: layer4만 학습 | layer4 + fc | 전체 갱신 |

실험 1은 BN의 `running_mean`, `running_var`, `num_batches_tracked`만 고정합니다.
BN의 affine scale/bias는 다른 파라미터처럼 학습합니다. 실험 2는 앞단 파라미터만
고정하고 앞단 BN 통계는 기존처럼 갱신합니다. 따라서 완전히 고정된 특징 추출기를
시험하는 것이 아니며, BN 통계까지 고정한 부분 미세조정과도 구분합니다.
두 실험을 동시에 적용하는 조합은 이번 범위에 포함하지 않습니다.

공통 조건은 seed 42, ImageNet V2 ResNet-50에서 새로 시작, 가중 CE, batch/effective
batch 16, head 2 + 미세조정 최대 18 epoch, patience 6, 기존 AdamW·학습률·scheduler·
AMP·256px 전처리입니다. 출력층 학습 2 epoch에서는 기존처럼 전체 backbone과 BN 통계를
동결합니다. 같은 head 초기화·단계에서 출발하고 기존 피부 모델을 이어 학습하지 않습니다.
기존과 같은 검증 macro-F1로 선택하며 동률이면 unweighted 검증 CE를 사용합니다.

인물 분리 fingerprint는
`6ac903796d100a2ee4f66e3e1936548dfa618c9b448a90985ff9ffbb0c13d793`입니다.
학습 690명/4,112 ROI, 검증 138명/816 ROI를 유지합니다. 두 후보는 별도 폴더에 저장하며
기존 가중치·서비스 설정·추천 묶음은 보존합니다. 테스트 페이지를 자동 교체하지 않습니다.

## 평가와 해석 기준

같은 학습/검증셋을 증강 없는 FP32 eval mode에서 평가합니다. Accuracy,
macro/weighted Precision·Recall·F1, 등급별 지표·혼동행렬·MAE·±1등급 적중률과
최고 두 등급 pooled 정확 분류 Recall을 기록합니다. scikit-learn으로 지표를 대조합니다.
학습/검증 F1 차이가 줄어도 검증 성능이 낮아지면 개선으로 해석하지 않습니다.

우선 검증 macro-F1을 비교하고 정확도·고등급 Recall·MAE의 변화를 함께 보고합니다.
상충되는 지표를 감추거나 후보를 자동 채택하지 않습니다. 한 seed의 검증 비교이므로
통계적 우월성이나 배포 성능을 확정하지 않습니다. 최종 평가셋은 조회하지 않습니다.
특히 모공 5등급 검증은 기존과 같은 1명/6 ROI이므로 고등급 지표의 해석 범위가 좁습니다.

BN 고정 후보의 최종 학습 체크포인트에서 모든 BN 통계가 ImageNet 초기값과
일치하는지 확인합니다. layer4 후보는 앞단 파라미터가 초기값과 같고 앞단 BN 통계는
갱신됐는지 확인합니다. 평가 모드 전환 뒤에도 학습 정책이 유지되는지 테스트합니다.

## 재현과 산출물

저장소 루트에서 실행합니다.

```powershell
uv run --project ml python -m ml.scripts.report_finetuning_ablation --phase preflight
uv run --project ml python -u -m skin_analysis.smartphone.train --config ml/configs/nia_smartphone_bn_frozen.toml --task pore
uv run --project ml python -u -m skin_analysis.smartphone.train --config ml/configs/nia_smartphone_layer4.toml --task pore
uv run --project ml python -m ml.scripts.report_finetuning_ablation --phase evaluate
uv run --project ml python -m ml.scripts.report_finetuning_ablation --phase publish
```

산출물은 `ml/runs/nia-smartphone-finetuning-seed-42/`의 `bn-stats-frozen/pore/`,
`layer4-only/pore/`에 보존합니다. 개별 예측·원본 경로·인물 식별자는 공유하지 않습니다.
공개 보고서는 이 문서·집계 JSON·학습 곡선만 포함합니다. 기존 run은 덮어쓰지 않습니다.

참고: [BatchNorm 동작](https://docs.pytorch.org/docs/2.14/generated/torch.nn.BatchNorm2d.html),
[미세조정과 사전학습 특징](https://arxiv.org/abs/2202.10054).
