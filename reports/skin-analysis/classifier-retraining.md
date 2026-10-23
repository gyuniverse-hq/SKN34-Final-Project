# 모공 분류층 균형 재학습과 조건부 3등급 실험

## 사전에 고정한 실험 계획

기존 WCE + AdamW + SAM의 선택 가중치에서 특징 추출기를 가져오고 마지막
분류층을 초기화해 다시 학습한다. 특징 추출기의 파라미터와 BN 이동 통계는
모두 고정한다. 매 epoch마다 원래 학습 ROI 수 4,112개만큼 복원 추출하며
목표 등급별 횟수 차이가 최대 1개가 되도록 한다. 등급 안에서는 인물을 균등
추출하고, 선택된 인물의 해당 등급 ROI 중 하나를 균등 추출한다.

손실은 가중치 없는 CE이다. 균형 샘플링과 WCE를 중복 적용하지 않는다.
최적화는 분류층에만 AdamW + SAM(rho=0.05), 배치 16, LR 0.001에서 cosine
감소, weight decay 0.0001, 최대 20 epoch, patience 6, seed 42를 사용한다.
기존 ±5도 회전·2% 이동·약한 색상 증강과 256px ROI는 유지한다.
검증 Macro-F1이 가장 높은 체크포인트를 선택하고 동률이면 검증 CE로 결정한다.

이는 [cRT 논문](https://arxiv.org/abs/1910.09217)의 특징 학습/분류층 재학습 분리를
차용한 실험이다. 원 논문의 자연 분포 특징 학습·SGD 설정을 재현하는 실험은 아니다.
기존 피부 특징을 사용하는 후처리 학습이므로 ImageNet 초기 상태에서 분류층을
먼저 학습하던 기존 warmup 및 layer4 미세조정 실험과 다르다.

**6등급 통과 조건**: 기존 WCE+SAM보다 검증 Macro-F1 증가, Accuracy 유지 이상,
4·5등급의 정확한 등급 재현율을 support로 합산한 값 증가, 5등급 Recall > 0을
모두 충족해야 한다. 이것은 이번 실험의 운영 판단 기준이며 통계적 유의성 기준이 아니다.

충족하지 못하면 원본 라벨을 보존하면서 `0·1 → 낮음(0)`, `2·3 → 중간(1)`,
`4·5 → 높음(2)`으로 묶은 **3출력 분류층**을 같은 방식으로 새로 학습한다.
이 구간은 추천 기능을 위한 임시 묶음이며 임상적으로 검증된 중증도 기준은 아니다.
3등급 후보는 기존 6등급 모델의 확률을 같은 두 등급씩 합산한 3등급 기준선과
비교한다. 6등급 Accuracy와 3등급 Accuracy를 직접 비교해 개선으로 주장하지 않는다.
3등급 통과 조건도 같은 목표 공간에서 Macro-F1 증가·Accuracy 유지 이상·높음 Recall
증가이다. 높음 Recall은 원본 4·5를 구분하지 않고 묶어 맞힌 비율이다.

## 데이터 및 보존

- 기존 스마트폰 데이터의 인물별 train/valid/test 분할과 원본 라벨을 유지한다.
- train 690명·4,112 ROI, valid 138명·816 ROI만 사용한다. test 137명·819 ROI는 평가하지 않는다.
- 원본 5등급은 학습 8명·48 ROI, 검증 1명·6 ROI이다. 복원 추출은 새로운 피부 사례를 만들지 않는다.
- 3등급에서도 원본 4·5등급의 인물 다양성 부족은 그대로 남는다.
- 기존 가중치와 서비스 설정은 SHA-256으로 전후 비교하며 후보는 별도 run에 저장한다.
- `pore_coarse`와 명시적 원본→목표 매핑을 저장한다. 기존 6등급 추론 계약과 혼용하지 않는다.
- 테스트 페이지와 추천용 활성 모델은 이 실험으로 자동 변경하지 않는다.

## 실행

저장소 루트, 로컬 GPU 환경에서 실행한다. 설정은 `ml/configs/nia_smartphone_classifier_retraining.toml`과
`ml/configs/nia_smartphone_pore_coarse.toml`이다.

```powershell
uv run --project ml python -m skin_analysis.smartphone.classifier_retraining --config ml/configs/nia_smartphone_classifier_retraining.toml --phase preflight
uv run --project ml python -m skin_analysis.smartphone.classifier_retraining --config ml/configs/nia_smartphone_classifier_retraining.toml --phase train
uv run --project ml python -m skin_analysis.smartphone.classifier_retraining --config ml/configs/nia_smartphone_classifier_retraining.toml --phase evaluate
```

6등급의 기록된 조건이 미달일 때만 아래 명령이 허용된다.

```powershell
uv run --project ml python -m skin_analysis.smartphone.classifier_retraining --config ml/configs/nia_smartphone_pore_coarse.toml --phase preflight
uv run --project ml python -m skin_analysis.smartphone.classifier_retraining --config ml/configs/nia_smartphone_pore_coarse.toml --phase train
uv run --project ml python -m skin_analysis.smartphone.classifier_retraining --config ml/configs/nia_smartphone_pore_coarse.toml --phase evaluate
```

완료되거나 일부 생성된 run은 덮어쓰지 않는다. 이 소규모 재학습 실행기는 재개 기능이
없다. 새 실험은 설정의 output 경로를 분리한다. 3등급 전환의 선행 판단은 위 기본
6등급 run의 `comparison.json`에서 읽는다. 개별 인물·예측·가중치는 Git 제외 경로에만
저장하며 이 보고서에는 집계 통계만 게시한다.
