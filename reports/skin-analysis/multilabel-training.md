# 피부 분석 멀티라벨 학습 도구

Windows / Python 3.12 / PyTorch / RTX 4070 Ti SUPER를 위한 독립 uv 프로젝트입니다.
Expo 앱, 추천 모델, 추론 서버와 연결하지 않습니다.

기본 데이터 경로는 저장소 루트의 `data/Skin-Problem-MultiLabel/`입니다.
데이터 확보 이후에도 라벨링 근거·분포·중복 검사가 필요하며, **본학습은 데이터 감사가
통과할 때까지 차단됩니다.** 합성 테스트 통과는 피부 분석 성능 검증을 의미하지 않습니다.

## 설치와 오프라인 검증

저장소 루트의 PowerShell에서 실행합니다. Python 의존성은 루트 npm 환경과 분리됩니다.

```powershell
uv sync --project ml --locked
uv run --project ml ruff check ml
uv run --project ml python -m pytest ml/tests -q
uv run --project ml python -m skin_analysis.smoke
uv run --project ml python -m skin_analysis.smoke --cuda
```

lockfile은 Windows AMD64와 Python 3.12용이며, `torch==2.13.0`,
`torchvision==0.28.0`에만 공식 CUDA 12.6 index를 사용합니다. 별도의 기존 가상환경은
변경하지 않습니다. GPU UUID는 `configs/resnet50_multilabel.toml`의 `train.device_uuid`에
지정합니다. 다른 장비에서는 다음 명령으로 확인한 4070 Ti SUPER UUID로 변경하세요.

```powershell
nvidia-smi --query-gpu=uuid,name,memory.total --format=csv
```

smoke 명령은 ImageNet 가중치를 다운로드하지 않고, 무작위 가중치와 합성 이미지로
224×224 입력, freeze/unfreeze, BCE 역전파, CUDA FP16 AMP, 저장·재로드를 검사합니다.
측정값은 `ml/runs/smoke.json`에 저장하며 배치 2의 합성 검사 값입니다.
실데이터 배치 32의 메모리·학습 시간으로 해석하면 안 됩니다.

## 실제 데이터 준비

대상은 [Skin-Problem-MultiLabel v1](https://universe.roboflow.com/parin-kittipongdaja-vwmn3/skin-problem-multilabel/dataset/1)
하나입니다. Roboflow의 다운로드 화면에서 **Multiclass Classification CSV** export를
선택하고 `data/Skin-Problem-MultiLabel/`에 압축을 해제합니다. 계정 접근 권한이 필요할 수
있습니다. 이 도구는 다운로드나 API 키 저장을 수행하지 않습니다.

```text
data/Skin-Problem-MultiLabel/
  train/_classes.csv   (+ images)
  valid/_classes.csv   (+ images)
  test/_classes.csv    (+ images)
```

`classes.csv`라는 파일명도 허용하며 split마다 둘 중 하나만 있어야 합니다.
첫 열은 `filename`, 나머지 **모든 열**은 클래스입니다. 세 split의 클래스 이름과 순서는
같아야 합니다. 값은 0/1이어야 하며 빈칸, `unknown`, `null`, `nan`, `na`, `?`는
미확인으로 집계하고 학습을 차단합니다. -1과 다른 수치는 오류입니다.
다른 export 형식이라면 변환 과정에서 라벨을 잃지 않는지 확인한 뒤 명시적인 어댑터가
필요합니다. 폴더 이름으로 one-hot 라벨을 임의 생성하지 않습니다.

공개 페이지의 클래스는 Acne, Blackheads, Dark Spots, Dry Skin, Eye bags, Normal Skin,
Oily Skin, Pores, Skin Redness, Wrinkles입니다. 실제 CSV에서 전체 클래스 수와 순서를
읽으며, 공개 목록과의 차이도 보고합니다. 10개 출력을 하드코딩하지 않습니다.

## 근거와 검수 기록

예제 파일을 복사해 로컬 검수 자료를 만듭니다. 예제는 승인된 자료가 아닙니다.

```powershell
Copy-Item ml/configs/evidence.example.json ml/configs/evidence.local.json
Copy-Item ml/configs/images.example.csv ml/configs/images.local.csv
Copy-Item ml/configs/duplicates.example.csv ml/configs/duplicates.local.csv
uv run --project ml python -m skin_analysis.audit
```

감사는 실패해도 TOML의 `audit.output`에 `report.json`을 쓰고 종료 코드 2를 반환합니다.
현재 기본 출력은 `ml/runs/audit-cleaned/`이며, 최초 원본 감사 `ml/runs/audit/`와 분리됩니다.
정상 종료 코드는 0입니다. 학습용 manifest도 같은 폴더에 저장합니다.
`summary.md`에 원본/준비 분할 수, 클래스별 양성 수와 경고를 정리하며,
`prepared-manifest.csv`와 `quarantine.csv`도 감사할 때마다 함께 갱신합니다.
원본 폴더명을 옮기는 대신 manifest의 `split`을 실제 학습·평가에 사용합니다.

`evidence.local.json`에는 실제 자료의 출처를 남깁니다.

- `confirmed_classes`: CSV의 전체 클래스 순서와 정확히 같은 목록.
- `exhaustive_negatives_evidence`: 명시된 0이 실제 음성임을 뒷받침하는 라벨링 지침·검수 근거.
  CSV가 이진이라는 사실이나 표본 몇 장의 관찰만으로 대체하지 않습니다.
- `normal_definition_evidence`, `normal_exclusive`: Normal Skin의 범위와 다른 상태와의
  동시 양성 허용 여부. 클래스가 없으면 그 사실을 문서화합니다.
- `rights_evidence`, `image_sources`, `license`, `license_url`: 사용 권한과 원출처,
  CC BY 4.0 출처 표시 근거. 공개 라이선스가 초상·개인정보 관련 권한까지 보장하지 않습니다.
- `label_review_evidence`, `full_face_evaluation_evidence`: 실제 검수 담당·방법·기록과
  얼굴 사진 입력 목적에 맞는 평가 근거.
- `skin_tone_information`: 공개적으로 확인된 구성과 한계. 알 수 없으면 unknown으로 둡니다.

이 필드들은 근거 기록이지 자동 검증된 사실이 아닙니다. 승인받기 위해 임의 문구로
채우지 마세요. 도구는 문서가 참인지, 피부 상태가 정확한지 판정하지 않습니다.

`images.local.csv`의 각 행은 `train/example.jpg` 같은 root 상대 경로를 사용합니다.

| 열 | 의미 |
|---|---|
| `person_id` | 제공되거나 검수로 확인된 동일 인물 ID. 알 수 없으면 비워 둠 |
| `session_id` | 동일 촬영 세션의 전역 고유 ID |
| `source_id` | 크롭·편집본이 공유하는 **원본 이미지** ID. 웹사이트 이름이 아님 |
| `image_type` | `full_face`, `partial_face`, `skin_closeup`, `non_face`, `unknown` |
| `labels_reviewed` | `true` 또는 `false` |
| `notes` | 검수 근거·문제·촬영 조건 등. 검수 완료에는 메모도 필요 |

보고서의 `review_samples`에 클래스별 양성·음성 각 20장, 복합·정상 각 30장을
고정 seed로 제시합니다. 가용 수가 적으면 전부 제시하고 부족량을 남깁니다.
지정 표본의 라벨을 검수하고 기록하세요. 전체 0 라벨도 별도 검수가 필요하며
자동으로 정상 피부로 해석하지 않습니다.

SHA-256·EXIF 반영 RGB 픽셀 해시가 같은 이미지는 하나만 남깁니다.
동일 이미지의 충돌 라벨은 합치지 않습니다. pHash 거리 6 이하 원본 후보는
`source_near_duplicate_candidates`에, 준비된 학습셋에 남은 후보는
`near_duplicate_candidates`에 기록합니다. `duplicates.local.csv`에 `path_a`, `path_b`,
`decision`(`duplicate`/`distinct`), `notes`를 작성해 검수합니다. 확인된 중복은 제거하고
인물·세션·원본 그룹은 분할 경계를 넘지 않게 묶습니다. 인물 ID가 없으면
동일 인물 누수 제거를 보장하지 못한다는 경고를 남깁니다.

현재 기본 설정은 `quarantine_conflicts=true`, `quarantine_unreviewed_similarities=true`,
`resplit=true`입니다. 확인된 중복의 정답이 충돌하면 해당 그룹 전체를 학습 manifest에서
격리하며, 미검수 유사 후보도 양쪽의 기존 인물/원본 그룹 전체를 격리합니다. 원본 파일과
라벨을 삭제·변경하지 않으며, 유사 후보를 확정 중복이라고 판정하지도 않습니다.
격리한 모든 경로·기존 정답·이유는 `quarantined_source_images`에 보존합니다.
정상 이미지도 보수적으로 제외될 수 있으므로 격리 비율과 클래스별 영향을 확인하세요.
두 quarantine 옵션을 false로 두면 충돌·유사 후보를 기존처럼 차단 사유로 남깁니다.

재분할은 그룹별 크기·양성 수·복합 수가 같은 그룹들을 묶어 정수 최적화로 배치합니다.
전체 이미지 비율 70/20/10과 클래스별 양성 수의 70/20/10 배분을 목표로 하되,
설정된 양성·음성·복합 사례 최소치를 제약으로 지키며 그룹을 쪼개지 않습니다. 같은 유형의 실제 그룹은
seed 42로 배치합니다. 충족할 수 없으면 기준을 낮추거나 그룹을 쪼개지 않고 차단합니다.
그룹 크기 때문에 전체 비율은 최대 그룹 크기-1장까지 차이를 허용합니다.
현재 `positive_support_policy="proportional"`은 요청한 비율을 우선합니다. 클래스별 전체 양성 수를
N이라 할 때 valid/test 양성 최소치는 각각 `max(1, floor(N×0.2))`, `max(1, floor(N×0.1))`이며,
학습에도 최소 1장이 있어야 합니다. 정수 반올림·복합 라벨·그룹 제약 때문에 클래스별 비율은
근사값입니다. 희소 클래스의 평가 표본이 초기 권고 20장보다 작으면 경고로 기록합니다.
`positive_support_policy="fixed"`로 바꾸면 초기 `min_eval_positive=20`을 다시 강제하므로,
홍조 46장 중 학습에 6장만 남을 수 있습니다. 정책 선택은 fingerprint에 포함됩니다.
새 분할의 클래스별 수를 확인해야 하며, 표본 수 기준 통과가 성능 검증을 뜻하지 않습니다.
테스트 결과를 본 이후 재분할하지 마세요.

정수 최적화는 고정 환경의 SciPy/HiGHS를 사용합니다. 미확인 라벨은 재분할에 음성으로
사용하지 않습니다. 격리와 재분할 후에도 원출처·음성 라벨 완전성·정상 정의·검수 근거가
없으면 감사는 승인되지 않습니다. 근거를 임의 문구로 채워 학습을 시작하지 않습니다.

기본 학습 승인 조건은 다음과 같습니다. 정책 변경도 fingerprint에 반영됩니다.

- 모든 라벨이 완전한 이진 정답이며, 미표기=음성이라는 근거가 있음.
- Normal Skin을 제외한 양성이 둘 이상인 복합 사례가 train 100 / valid 30 / test 30장 이상.
- 모든 클래스에 train 양성·음성이 있고, valid/test 양성 수는 위 명시적 비율 정책을 충족.
  valid/test 음성은 각각 20장 이상. 초기 고정 양성 20장 기준과 달라졌음을 보고서에 기록.
- valid/test에 검수된 full-face 이미지 각각 30장 이상과 독립 그룹 각각 2개 이상.
- 지정 표본 검수, 클래스 순서·권한·라벨 정의 근거, 정상 피부 일관성, 중복 검수가 충족됨.

이 수치는 초기 운영 최소 기준이며 통계적 충분성이나 글로벌 서비스 적합성을 보장하지
않습니다. 미달하면 본학습을 보류합니다. 새 데이터 수집·자동 재라벨링은 하지 않습니다.

## 학습·재개

```powershell
uv run --project ml python -m skin_analysis.train
uv run --project ml python -m skin_analysis.train --resume ml/runs/resnet50/last.pt
```

모든 명령에 `--config <toml>`을 지정할 수 있습니다. TOML 안의 경로는 항상 `ml/`
기준입니다. 별도 설정을 사용해도 데이터·근거·검수 파일을 다시 읽어 감사를 수행하므로,
기존 보고서의 `status`만 수정해서 학습을 시작할 수 없습니다. 데이터 fingerprint,
클래스 순서 또는 학습 설정이 달라지면 재개를 거부합니다. 기존 실행은 덮어쓰지 않습니다.

구조는 공식 torchvision ImageNet `IMAGENET1K_V2` ResNet-50 +
`2048→512→ReLU→Dropout(0.3)→K logits`입니다. 첫 본학습 시 공식 ImageNet 가중치를
받을 수 있습니다. tugbadur 소스·피부 분석 가중치는 복제하거나 로드하지 않습니다.

RGB·EXIF 방향 반영·전체 프레임 224×224 bilinear/antialias resize 후 ImageNet 정규화를
적용합니다. 학습에만 flip 0.5, 회전 ±5°, 밝기·대비 0.1을 사용합니다. 얼굴 검출·크롭은
추가하지 않습니다. 이 레시피는 공식 가중치의 기본 center-crop과 다르며 체크포인트에
저장합니다.

정답은 `[B,K]` float32의 0/1, 출력은 logits이며 학습 손실은 BCEWithLogitsLoss입니다.
train에서만 `pos_weight=min(음성/양성,20)`을 계산합니다. 출력층에 Sigmoid를 넣지 않고
평가·추론에서만 적용합니다.

AdamW로 head 3 epochs(LR 1e-3)를 학습한 뒤 전체 백본을 최대 27 epochs 미세조정합니다.
두 번째 단계는 backbone 1e-5 / head 1e-4, weight decay 1e-4, cosine 최저 LR 1e-7입니다.
BatchNorm running statistics는 고정합니다. 검증 macro AP로 best를 선택하고 동률이면
BCE가 작은 모델을 선택합니다. 2단계에서 AP 개선이 1e-4 미만인 상태가 7 epochs 지속되면
조기 종료합니다.

CUDA FP16 AMP와 유효 배치 32를 사용합니다. OOM 시 epoch 시작 상태로 되돌린 뒤
micro batch를 32→16→8로 줄여 재시도하고 gradient accumulation을 적용합니다.
마지막 불완전한 누적 묶음도 실제 표본 수로 정규화합니다. Windows worker 오류는
`train.num_workers=0`으로 진단하세요.

`best.pt`, `last.pt`, `history.json`, `data_audit.json`이 run 폴더에 저장됩니다.
재개용 체크포인트는 optimizer·scheduler·scaler·난수·로더 상태를 포함합니다.
기록된 epoch 시간은 CPU 백업·감사·파일 저장 시간을 모두 포함하는 전체 실행 시간과
다를 수 있습니다. 실제 peak 메모리와 시간은 첫 epoch와 unfreeze 이후 측정합니다.

## 검증·추론

```powershell
uv run --project ml python -m skin_analysis.evaluate --cuda
uv run --project ml python -m skin_analysis.predict --checkpoint ml/runs/resnet50/evaluation/inference.pt --image C:/path/to/face.jpg
```

평가·추론은 기본 CPU이며 `--cuda`를 지정하면 설정된 GPU UUID를 사용합니다.
평가는 기본 `best.pt`를 읽습니다. 클래스별 F1 최대 임계값을 **valid만** 사용해
0.05~0.95/0.01 간격으로 선택합니다. 동률이면 0.5에 가까운 값, 다시 동률이면 높은 값을
선택합니다. 그 뒤 test를 예측하며 test로 임계값을 재조정하지 않습니다.
학습 양성률 상수 기준선에도 valid로 선택한 임계값을 적용해 비교합니다.

산출물은 `evaluation.json`, PR 곡선 PNG, `inference.pt`입니다. 클래스별
Precision/Recall/F1/AP/support/2×2 confusion matrix/FPR, Macro·Micro F1, macro AP,
복합·단일 상태·정상·구도별 결과를 제공합니다. AP는 Average Precision이며
사다리꼴 적분 PR-AUC와 혼용하지 않습니다. 정의할 수 없는 지표는 null과 사유를 기록합니다.
group bootstrap 1,000회의 Macro F1 및 기준선 대비 차이 95% CI도 기록합니다.

기준선보다 Macro·Micro F1이 높고, 모든 클래스의 양성을 검출하며, Macro F1 차이의
95% CI 하한이 양수여야 `research_success=true`입니다. 검증셋 성능에는 모델·임계값
선택의 영향이 있습니다. 하위 집합 표본 부족, 피부톤 다양성, 인물 ID 미확보 등의
한계도 보고합니다. 평가 출력 폴더는 덮어쓰지 않으며 재평가 시 새 `--output`이 필요합니다.

추론은 클래스 이름·순서, sigmoid 점수, 임계값, 판정, 모델 ID와 연구 성공 여부를
반환합니다. 점수 합을 1로 강제하지 않고 Normal Skin도 독립 출력으로 유지합니다.
**점수는 보정되지 않은 분류 점수이며, 심각도·의학적 진단·실제 발생 확률이 아닙니다.**

## 검증과 저장소 관리

```powershell
uv run --project ml ruff check ml
uv run --project ml python -m pytest ml/tests -q
npm run check
```

테스트는 합성 이미지·라벨만 사용하며 데이터나 가중치를 다운로드하지 않습니다.
실제 ResNet CPU 역전파·저장·재로드 검사와 별도로, 빠른 작은 모델을 이용해
전체 학습·중단 재개·평가 흐름을 검사합니다. 이는 피부 분석 정확도를 측정하지 않습니다.

데이터, 로컬 검수 파일, `.venv`, run 산출물은 Git에서 제외합니다. 코드와 lockfile만
공유하고 얼굴 이미지나 권한이 불명확한 가중치는 커밋하지 않습니다. PR은 팀의
CONTRIBUTING.md를 따르며 변경 사항·영향 범위·실행한 검사 결과를 기록합니다.

참고: [torchvision ResNet-50](https://docs.pytorch.org/vision/0.28/models/generated/torchvision.models.resnet50.html),
[PyTorch 설치 조합](https://pytorch.org/get-started/previous-versions/),
[Roboflow export](https://docs.roboflow.com/developer/export-data),
[SciPy 그룹 분할 최적화](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html),
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/),
[tugbadur 설계 참고](https://github.com/tugbadur/skin-analysis-project).
