# AI-Hub 여드름 이진 분류 연구

기존 `skin_analysis` 멀티라벨 실험과 독립적인 `skin_analysis.acne` 모듈입니다.
정상=0, 여드름=1이며, 다른 피부질환을 정상으로 취급하지 않습니다.
원본 ZIP·JSON·NIA 체크포인트는 수정·추출·이동하지 않습니다.

## 데이터와 평가 범위

- AI-Hub 71863의 로컬 정면 이미지 1,800장(정상/여드름 각 900장)을 감사합니다.
- 공식 Training에서 그룹 단위 약 70/15/15 내부 분할을 만들고 공식 Validation은
  모델 선택에 사용하지 않는 추가 합성 평가로 보존합니다.
- 이미지–JSON을 대조하고 모든 대상 이미지를 디코딩하며 원본 바이트·픽셀 해시와
  pHash를 기록합니다. 같은 후보 원본 접두사, 동일 콘텐츠, pHash 거리 6 이하를
  연결한 전체 그룹은 분할 경계를 넘지 않습니다. 공식 평가와 겹치는 학습 그룹 및
  동일 픽셀의 상충 라벨은 manifest에서 격리합니다.
- 파일명 접두사의 원본·인물 의미는 미확인입니다. 위 그룹은 누수 완화책이며
  동일인 독립성을 검증했다는 뜻이 아닙니다. 얼굴 재식별은 수행하지 않습니다.
- 생성 연령·성별·계열 메타데이터를 분할 분포에 반영하지만 클래스 간 편향을
  제거했다고 주장하지 않습니다. 최종 보고서에 메타데이터만 사용한 진단용 기준 모델도
  포함해 높은 합성 점수의 해석을 돕습니다. 해당 메타데이터는 이미지 모델에 입력하지 않습니다.
- 병변 bbox·염증 여부·마스크 경로는 유지합니다. 실제 마스크 파일은 로컬 ZIP에 없으며
  분류에 사용하지 않습니다. 측면 부분 이미지는 초기 학습에서 제외합니다.

## 실행

저장소 루트 PowerShell에서 기존 uv 환경을 사용합니다. 추가 의존성이 없습니다.

```powershell
uv run --project ml python -m skin_analysis.acne.audit
uv run --project ml python -m skin_analysis.acne.train --source imagenet
uv run --project ml python -m skin_analysis.acne.train --source nia
uv run --project ml python -m skin_analysis.acne.evaluate
uv run --project ml python -m skin_analysis.acne.plot
```

설정은 `configs/acne_binary.toml`이며 경로는 `ml/` 기준입니다. 데이터 감사는 기존
manifest를 덮어쓰지 않습니다. 다시 감사할 때는 새로운 `data.output`을 사용하세요.
학습도 기존 실행을 덮어쓰지 않으며 재개에는 `--resume <같은 실행의 last.pt>`를 사용합니다.

아카이브·manifest·학습 설정·패키지·소스 해시가 달라지면 재개를 거절합니다.
GPU는 UUID로 명시적으로 선택합니다. RTX 4070 Ti SUPER / 유효 batch 32,
물리 batch 16, FP16 AMP가 기본입니다. OOM이면 실패를 확인하고 두 실험에 동일한
새 batch 설정과 실행 경로를 적용해야 합니다.

초기화만 바꾼 동일 ResNet-50 + Linear(2048,1)를 비교합니다. Head는 같은 seed로
별도 초기화하며 이후 데이터 RNG도 재설정합니다. 처음 3 epoch는 Head만,
이후 17 epoch는 layer4와 Head를 학습합니다. BatchNorm 통계는 고정합니다.
고정 20 epoch를 모두 수행하며 최적 체크포인트는 내부 Validation의
0.5 임계값 Macro F1, 동률 시 BCE로 선택합니다. Macro F1은 양 클래스 평균입니다.

ImageNet 가중치는 torchvision `IMAGENET1K_V2`를 명시적으로 사용합니다.
NIA는 로컬 설정의 `class/pore` 안전 사본에 SHA-256 검사와 strict 로딩을 적용한 뒤
원래 FC를 버립니다. 원래 가중치의 학습 해상도와 초기화 이력은 미확인입니다.
두 초기 가중치의 차이를 검증하며 피부 사전학습만의 인과 효과로 해석하지 않습니다.

## 결과와 추론 계약

`ml/runs/acne/` 아래에 감사 보고서, 최고/마지막 체크포인트, epoch별 기록,
Validation에서 정한 임계값, 최종 표본별 예측과 A/B 비교 보고서를 저장합니다.
최종 평가는 기존 `report.json`이 있으면 재실행을 거절합니다.

Accuracy, 여드름 Precision/Recall, 양 클래스 Macro F1, ROC-AUC,
Average Precision, 사다리꼴 PR-AUC, 혼동행렬, 메타데이터별 하위그룹을 기록합니다.
NIA−ImageNet의 고정 0.5 Test Macro F1 차이는 그룹 paired bootstrap으로 평가합니다.
이 신뢰구간은 하나의 seed·분할 내 표본 불확실성이며 학습 seed 변동을 대신하지 않습니다.
고정 0.5와 Validation에서 선택한 임계값의 결과를 둘 다 보고합니다.
채택 모델은 Test 점수와 독립적으로 Validation에서 선택합니다.

추론 bundle은 원본 전체 이미지 → EXIF 방향 처리 → RGB → 256×256 bilinear
→ ImageNet 정규화를 포함합니다. NIA 부위별 Crop·JPEG 왕복은 적용하지 않습니다.
sigmoid score는 보정된 임상 확률이 아닙니다. 여드름 확정 진단, 다른 질환 배제,
병변 검출 또는 중증도를 제공하지 않습니다.

## 로컬 NIA 개발 도구 연결

`server/nia/config.local.json`에 선택한 bundle의 경로와 해시를 추가합니다.
기존 10개 원본 모델 설정은 유지합니다.

```json
{"acne": {"checkpoint": "<absolute path to inference.pt>", "sha256": "<SHA-256>"}}
```

Python 서비스를 재시작하면 `/dev/nia`의 사진 분석에 독립 여드름 결과가 추가됩니다.
실패 시 해당 값만 null/failed가 되고 NIA 결과는 유지됩니다. 여드름 미설정 시
기존 v1 schema가 유지되며 설정 시 v2에서 `features.acne`는 이진 label입니다.
`ml_input.acne`에 score·threshold·모델 해시·검증 범위가 별도로 들어갑니다.

이 연결은 사용자가 요청한 로컬 연구·평가 도구에 한정합니다. 운영 앱의 얼굴 영상
비전송/기기 내 피부톤 분석 아키텍처는 변경하지 않습니다. 새 운영 API를 열지 않고
개발 전용 제한·loopback·서버 비밀값을 유지합니다.

## 권리와 한계

AI-Hub 공식 이용정책의 연구개발 활용 범위에서 로컬 비교를 수행합니다.
제공 문서 본문과 생성 원본 관계, 개별 체크포인트 권리, 상업 서비스·가중치 배포·국외
반출 조건은 추가 확인이 필요합니다. 무제한 라이선스로 표시하지 않습니다.
실사 검증 데이터의 이용 동의와 정답 근거는 확보되지 않았으므로 이 모델은
운영 배포 준비가 끝난 모델이 아닙니다. 이미지·가중치·로컬 보고서를 Git에 넣지 않습니다.

- 데이터: https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=71863
- 이용정책: https://www.aihub.or.kr/intrcn/guid/usagepolicy.do?currMenu=151&topMenu=105
- ResNet-50: https://docs.pytorch.org/vision/0.28/models/generated/torchvision.models.resnet50.html

## 검증 명령

```powershell
uv run --project ml ruff check ml
uv run --project ml python -m pytest ml/tests -q
server/nia/.venv/Scripts/python.exe -m unittest discover -s server/nia/tests -v
npm run check
```
