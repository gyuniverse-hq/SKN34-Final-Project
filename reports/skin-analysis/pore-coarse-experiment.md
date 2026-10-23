# 모공 3등급 WCE + AdamW + SAM 학습

## 범위와 사전 결정

[분류층 균형 재학습](classifier-retraining.md)은 6등급에서 전체 Accuracy·Macro-F1이
하락했고, 3등급으로 묶은 분류층 단독 재학습도 오탐과 정확도 손실이 컸다.
이에 사용자 지시의 후속 단계로 분류 목표를 `0·1 / 2·3 / 4·5`의 3개로 바꾸고,
기존 가장 높은 전체 정확도를 기록한 **WCE + AdamW + SAM 전층 학습**을 적용한다.
직접 3출력을 학습하는 모델이며 기존 6등급의 예측을 단순히 표시만 바꾸는 모델과 구분한다.

원본 라벨·인물별 분할·이미지·ROI를 수정하지 않고 dataset 접근 시 목표 라벨만
매핑한다. 원본 0~5등급은 별도로 보존한다. 3출력 체크포인트에는 `pore_coarse`,
`grades=[0,1,2]`, `original_grades=[0,1,2,3,4,5]`,
`original_to_target=[0,0,1,1,2,2]`를 명시한다.

ImageNet ResNet-50에서 새로 시작한다. 6등급의 학습된 특징 추출기를 고정하는
cRT 실험과 달리 여기서는 head warmup 2 epoch 후 전체 네트워크를 최대 18 epoch
미세조정한다. 원래 WCE+SAM과 비교해 목표 등급 수·그에 따른 WCE 가중치만 바꾼다.
자연 분포 shuffle을 사용하며 균형 복원 샘플링을 사용하지 않는다.

배치 16, seed 42, SAM rho=0.05, patience 6, AMP, head LR 0.001,
미세조정 head LR 0.0001·backbone LR 0.00001, weight decay 0.0001,
cosine 감소와 기존 약한 증강을 유지한다. 검증 Macro-F1 최댓값·CE 동률 기준으로
체크포인트를 선택한다. 설정은 `ml/configs/nia_smartphone_pore_coarse_sam.toml`이다.

**전층 학습 전 고정한 통과 조건**: 기존 6등급 모델의 두 가지 3등급 해석 방식
(① 확률을 두 등급씩 합산 후 argmax, ② 원본 argmax 등급을 두 개씩 묶기)보다
Accuracy 유지 이상, Macro-F1 증가, 높음 Recall 증가를 모두 충족한다.
각 지표별 두 기준선의 큰 값을 넘는지 확인한다. 이는 운영 선택 기준이며 통계적
유의성 검정은 아니다. 기준선 ①은 Accuracy 74.88%·F1 44.96%·높음 Recall 0%,
②는 74.39%·53.84%·20%였다. 같은 데이터의 3등급 분류끼리 비교한다.

학습 690명·4,112 ROI와 검증 138명·816 ROI만 사용한다. 목표별 ROI 수는
학습 `[835,3005,272]`, 검증 `[165,601,50]`이다. 테스트는 이번 탐색에서 평가하지 않는다.
WCE 가중치는 매핑된 학습 빈도로 다시 계산한다. 등급 이름 낮음·중간·높음은
추천용 임시 구간이며 피부과 중증도 등급을 뜻하지 않는다.

## 실행 및 인계

저장소 루트에서 실행한다. 기존 run은 덮어쓰지 않으며 일반 학습 실행기는 동일
소스·환경·설정의 `last.pt` 재개를 지원한다.

```powershell
uv run --project ml python -m ml.scripts.pore_coarse_experiment --phase preflight
uv run --project ml python -m ml.scripts.pore_coarse_experiment --phase train
uv run --project ml python -m ml.scripts.pore_coarse_experiment --phase evaluate
uv run --project ml python -m ml.scripts.pore_coarse_experiment --phase publish
```

중단된 학습 재개는 다음 명령으로 한다. 완료 뒤 `wall-time.json`은 처음부터 끝까지
실행한 경우에만 생성되므로 재개했다면 실제 실행 시간을 별도로 기록해야 한다.

```powershell
uv run --project ml python -m skin_analysis.smartphone.train --config ml/configs/nia_smartphone_pore_coarse_sam.toml --task pore --resume ml/runs/nia-smartphone-pore-coarse-sam-seed-42/pore/last.pt
```

읽을 때는 먼저 SHA-256을 확인하고 안전한 tensor 로딩과 전용 계약 검사를 사용한다.

```python
import torch
from skin_analysis.smartphone.pore_coarse import load_model

checkpoint = torch.load("inference.bin", map_location="cpu", weights_only=True)
model = load_model(checkpoint)  # strict shape + original-to-target mapping
```

입력은 기존과 같은 로컬 256px 정사각 ROI·RGB·ImageNet 정규화다. 셀카 전체를
그대로 넣거나 사진을 외부 서버로 전송하는 사용법은 이 실험 범위에 포함하지 않는다.
실제 서비스 연결 시 API·UI·추천 값의 3등급 계약을 함께 반영해야 한다.
