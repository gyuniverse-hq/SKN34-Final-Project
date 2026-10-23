# 스마트폰 모공 CE 배치 크기 비교

## 설정

기존 `ml/configs/nia_smartphone.toml`의 가중 CE 모델을 기준으로
`batch_size`와 `effective_batch`를 32에서 **16**으로 바꿉니다.
기존 가중치를 이어 학습하지 않고 동일 ImageNet V2 초기화·seed 42에서 시작합니다.
데이터 분할·증강·모델 구조·클래스 가중치·학습률·최대 epoch·조기 종료는 유지합니다.
별도 설정: `ml/configs/nia_smartphone_ce_batch16.toml`.

`[data].output`은 기존 캐시를 재사용합니다. `[train].output`만
`ml/runs/nia-smartphone-ce-batch16-seed-42/`로 분리해 기존 모델을 보존합니다.
이번 변경에서는 설정 준비와 검사만 진행했으며, 학습 성능 결과는 아직 없습니다.

## 실행

저장소 루트 `R:\Coding\SKN34-Final-Project`의 PowerShell에서 실행합니다.

```powershell
uv run --project ml python -u -m skin_analysis.smartphone.train --config ml/configs/nia_smartphone_ce_batch16.toml --task pore
```

명령은 **모공만 새로 학습**하며 각 epoch의 검증 Accuracy·macro-F1·±1등급을 출력합니다.
선택 기준은 기존과 같은 검증 macro-F1, 동률이면 unweighted 검증 CE입니다.
최대 head 2 + 미세조정 18 epoch이며 patience 6에 따라 더 일찍 종료될 수 있습니다.
테스트 페이지나 추천용 묶음을 자동으로 변경하지 않습니다.

## 결과 확인과 해석

산출물은 `ml/runs/nia-smartphone-ce-batch16-seed-42/pore/`에 저장합니다.

- `summary.json`: 선택 epoch·실행 epoch 수·선택 macro-F1·가중치 SHA-256
- `history.json`: epoch별 학습 손실과 검증 지표
- `best.pt`, `last.pt`, `inference.bin`: 선택 모델·재개용 체크포인트·추론 가중치

기존 CE의 동일 검증셋 결과는 Accuracy **55.64%**, macro-F1 **31.42%**입니다.
`summary.json`의 `best_epoch`에 해당하는 `history.json` 행과 비교합니다.
학습셋 지표나 과거 최종 평가셋 수치와 혼동하지 않습니다.

이 실험은 같은 최대 epoch 예산의 배치 비교입니다. 배치를 절반으로 줄이므로
epoch당 optimizer 업데이트 수는 약 두 배가 되고, 미세조정 중 BatchNorm의 통계도
달라집니다. 동일 업데이트 횟수로 통제한 실험은 아닙니다. 실제 종료 epoch도 달라질 수 있습니다.
배치만 줄였다고 성능 개선을 보장하지 않으며 한 seed의 결과로 일반화하지 않습니다.

기존 Focal·CORAL 비교 명령은 비손실 학습 조건의 동일성을 검사하므로 이 설정에
그대로 사용하지 않습니다. 이번 실행은 최종 평가셋을 평가하지 않습니다.
이미 학습한 출력 폴더가 있으면 덮어쓰기를 거부합니다. 추가 실험은 새 출력 경로를 쓰고,
재개는 설정·소스·환경이 동일할 때 해당 폴더의 `last.pt`를 `--resume`에 지정합니다.
