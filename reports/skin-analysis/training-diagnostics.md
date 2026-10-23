# 모공 학습 파이프라인 진단

## 사전에 고정한 범위

시드·최적 하이퍼파라미터를 탐색하기 전에 소량 데이터 암기와 학습/검증 성능 차이를
확인합니다. 학습은 로컬 GPU에서만 실행하고 기존 가중치·서비스 설정·추천 묶음을 보존합니다.
새 데이터 수집·라벨 변경·최종 평가셋 조회·테스트 페이지 교체는 하지 않습니다.

데이터는 기존 인물 분리 seed 42, fingerprint
`6ac903796d100a2ee4f66e3e1936548dfa618c9b448a90985ff9ffbb0c13d793`을 유지합니다.
모공 학습 690명/4,112 ROI, 검증 138명/816 ROI입니다.

1. **소량 암기:** 학습셋에서 등급별 8개, 전체 48명/48 ROI를 선택합니다.
   희소 등급부터 선택하고 전 등급에 걸쳐 인물이 중복되지 않게 합니다.
   증강 없이 같은 48개를 반복하고, ImageNet V2 ResNet-50 전체를 FP32로 학습합니다.
   배치 16, head LR 0.001, backbone LR 0.0001, AdamW decay 0, 일반 CE,
   최대 100 epoch(300 업데이트), 5 epoch마다 평가합니다(초기와 epoch 1도 평가).
   두 번 연속 eval-mode Accuracy와 macro-F1이 모두 99% 이상이면 통과입니다.
   이는 일반화 성능 실험이 아니며 검증셋을 선택/학습/종료에 사용하지 않습니다.
2. **전체 학습 곡선:** 기존 배치 16 CE 학습을 별도 경로에서 재실행합니다.
   학습 조건·증강·선택 기준·최대 20 epoch·patience 6은 유지합니다.
   `record_train_metrics=true`로 매 epoch의 증강 없는 학습셋 지표를 추가합니다.
   학습/검증 모두 FP32, eval mode, unweighted CE와 동일 분류 지표로 비교합니다.
   추가 평가는 BN 버퍼를 갱신하지 않고 학습 RNG·loader generator 상태를 복원합니다.
3. **기존 모델 대조:** CE 배치 32·16, CB Focal, CORAL, 이번 진단 CE의 선택 가중치를
   동일한 학습/검증셋에서 평가합니다. 개별 예측은 Git 제외 경로에만 보관합니다.
   CORAL의 손실은 threshold BCE이므로 CE 모델의 손실과 직접 비교하지 않습니다.

구현의 자동 테스트만으로 사진/등급의 임상적 정합성이나 전처리의 정보 보존을 검증했다고
간주하지 않습니다. 작은 데이터 암기에 성공해도 라벨 품질이나 일반화를 보장하지 않습니다.

## 재현

```powershell
uv run --project ml python -u -m skin_analysis.smartphone.diagnostics --phase tiny
uv run --project ml python -u -m skin_analysis.smartphone.train --config ml/configs/nia_smartphone_diagnostics.toml --task pore
uv run --project ml python -u -m skin_analysis.smartphone.diagnostics --phase gaps
```

설정은 `ml/configs/nia_smartphone_diagnostics.toml`, 산출물은
`ml/runs/nia-smartphone-diagnostics-seed-42/`입니다. 기존 run을 덮어쓰지 않습니다.
`tiny-ce/`는 진단 전용 모델이며 추천용 가중치가 아닙니다.
`full-ce-batch16/pore/history.json`에 학습·검증 곡선 원시 집계를 보관합니다.

참고: [작은 배치 암기 및 입력 진단](https://karpathy.github.io/2019/04/25/recipe/),
[Google 연구팀 학습 진단 가이드](https://github.com/google-research/tuning_playbook).
