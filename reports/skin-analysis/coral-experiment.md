# 스마트폰 CORAL 순서형 분류 비교

## 목적과 사전 조건

2026-10-23, 기존 CE·CB Focal 가중치와 서비스 설정을 보존하고 **모공 하나부터**
새 CORAL 모델을 학습합니다. 아래 조건은 후보 학습 전에 고정했습니다.

- 기존과 같은 ImageNet V2 ResNet-50 backbone에서 새로 시작합니다. 기존 피부 모델을
  이어 학습하지 않습니다. 출력층은 6개 softmax에서 **공유 점수 + 5개 bias**로 바꿉니다.
- 학습 690명/4,112 ROI, 검증 138명/816 ROI. 데이터 fingerprint는
  `6ac903796d100a2ee4f66e3e1936548dfa618c9b448a90985ff9ffbb0c13d793`입니다.
  인물 분할·256px 전처리·증강·읽기 전용 캐시는 기존 실험과 동일합니다.
- seed 42, batch/effective batch 32, head 2 + backbone 최대 18 epoch, patience 6,
  학습률·AdamW·scheduler·AMP를 유지합니다. 새 head 구조에 따른 파라미터 초기화는 달라집니다.
- `y > k`를 정답으로 하는 K-1개 이진 문제를 함께 학습합니다. 모공 3등급은
  `[1,1,1,0,0]`입니다. 학습 입력을 등급별로 순차 제공하는 방식은 아닙니다.
- 손실은 **threshold별 BCE 합을 샘플 평균**한 기본 CORAL입니다. FP32 손실을 사용합니다.
  Focal·CB·기존 제곱근 클래스 가중치·별도 sampler는 사용하지 않습니다. 기존 가중 CE와
  출력층·손실·가중 방식이 함께 달라지므로 순서 정보만의 효과를 분리한 실험은 아닙니다.
- 저자 라이브러리와 같은 공유 선형 점수, 내림차순 초기 bias를 사용합니다. 추론은
  **P(y>k)>0.5인 threshold 개수**를 등급으로 반환합니다. softmax나 argmax를 사용하지 않습니다.
  threshold 순서가 어긋나면 추론을 차단합니다. 출력은 K-1개 누적 확률이며 클래스 확률이 아닙니다.
- 선택 기준은 기존과 같은 검증 macro-F1입니다. 동률일 때 CORAL의 unweighted 검증
  threshold BCE를 사용합니다. CE와 CORAL 손실의 절대값은 직접 비교하지 않습니다.

## 비교와 확대 기준

같은 검증셋에서 기존 CE·CB Focal·CORAL을 다시 추론합니다. Accuracy,
macro/weighted Precision·Recall·F1, 등급별 지표·혼동행렬·등급 MAE·±1등급 적중률을
기록합니다. scikit-learn 계산과 독립 대조합니다. 최종 평가셋은 이번 비교에 사용하지 않습니다.

모공 CORAL이 **기존 CE 대비** 다음 조건을 모두 만족할 때만 색소침착·주름으로 확대합니다.

1. 검증 macro-F1 개선
2. 정확 일치율 유지 또는 개선
3. 최고 두 등급(모공 4·5등급)의 pooled 정확 분류 Recall 개선

MAE는 등급 오차의 보조 판단값으로 함께 기록합니다. 정확 일치율 개선 없이 ±1등급이나
MAE만 개선된 후보는 확대하지 않습니다. 후속 항목도 각각 기존 모델과 평가하며
모공의 개선을 다른 항목의 개선으로 간주하지 않습니다. 이진 여드름은 대상에서 제외합니다.

한 seed의 검증 실험이며 통계적 우월성이나 새 인물의 최종 성능을 확정하지 않습니다.
소수 고등급 인물·라벨 품질·ROI·촬영 도메인 문제는 CORAL로 해결되었다고 볼 수 없습니다.
등급 사이의 실제 측정값 간격이 같다고 가정하지 않으며, MAE도 물리적 측정 단위가 아닙니다.

## 실행과 저장 계약

```powershell
uv run --project ml python -m skin_analysis.smartphone.train --config ml/configs/nia_smartphone_coral.toml --task pore
uv run --project ml python -m skin_analysis.smartphone.coral_compare --task pore
uv run --project ml python -m skin_analysis.smartphone.coral_compare --publish
```

모공 확대 기준을 통과한 기록이 있을 때만 동일 명령의 `--task pigmentation`,
`--task wrinkle`로 후속 학습·비교합니다. `--task all`은 CORAL에서 차단합니다.
실행 이력·가중치·개별 예측은 Git에서 제외한 `ml/runs/nia-smartphone-coral-seed-42/`에,
공유 가능한 집계는 이 보고서와 `.metrics.json`에 보관합니다. 이미 완료한 run은 덮어쓰지 않습니다.

CORAL 가중치는 `architecture=resnet50_coral`, `decoding=count_sigmoid_strictly_above_0.5`를
저장합니다. `skin_analysis.smartphone.coral.load_coral_checkpoint(path, expected_sha256)`로
해시·메타데이터·파라미터를 검증해 로딩합니다. 기존 softmax 엔진과 번들에 넣으면 안 됩니다.
운영 연결에는 CORAL 구조와 누적 확률 해석을 지원하는 별도 어댑터가 필요합니다.
이번 실험은 로컬에서만 실행하고 테스트 페이지나 추천용 묶음을 자동 교체하지 않습니다.

참고: [CORAL 논문](https://arxiv.org/abs/1901.07884),
[저자 구현 문서](https://raschka-research-group.github.io/coral-pytorch/).
