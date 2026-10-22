# 네 항목 피부 분석 모델 인계

선정: 여드름 이진 분류, 모공 등급(0~5), 색소침착 등급(0~5), 주름 등급(0~6).
수분·탄력·처짐·입술 건조·모공/색소침착/주름 회귀 모델은 추천용 추론에서 실행하지 않습니다.

## 저장 단위

하나의 새 추천 모델을 학습한 것이 아니라 **독립적인 분석 모델 4개**를 묶습니다.
여드름은 이번에 학습해 선택한 ImageNet 초기화 모델의 `inference.pt`, 나머지 3개는
기존 NIA 분류 체크포인트의 텐서가 동일한 안전 로더용 사본입니다. 재학습하지 않습니다.

`server/nia/recommendation.py`의 export 명령이 가중치의 SHA-256을 검사하고 다음을 만듭니다.
기존 원본과 내보내기 결과를 덮어쓰지 않습니다.

```text
skin-recommendation-v1/
  manifest.json       # 모델 설정, 부위, 등급 순서, 해시, 런타임 버전
  weights/
    acne.pt
    pore.bin
    pigmentation.bin
    wrinkle.bin
```

저장소 루트의 기존 Python 환경에서 생성합니다.

```powershell
uv run --project ml python -m server.nia.recommendation export --config server/nia/config.local.json --output ml/runs/skin-recommendation-v1
```

가중치 묶음은 Git에서 제외됩니다. 브랜치를 바꾸어도 같은 작업 디렉터리의 무시된 파일은
통상 남지만, 다른 worktree·장비·배포 환경에는 자동으로 전달되지 않습니다. 코드와 별도로
이 폴더 전체를 허용된 로컬 모델 경로에 배치합니다. 모델 파일만 전달하면 충분하지 않습니다.

## 기능 브랜치에서 로드

기능 브랜치에는 아래 코드도 함께 반영해야 합니다. 팀 규칙에 따라 PR로 develop에 통합하고
기능 브랜치에서 해당 변경을 가져오는 흐름이 기본입니다. 이 문서 작성만으로 커밋·PR·병합이
완료된 것은 아닙니다.

- `server/nia/{recommendation,profile,engine,imaging,catalog,metrics,__init__}.py`
- `server/acne/{engine,__init__}.py`
- `ml/src/skin_analysis/acne/{model,data,common,__init__}.py`
- Python 환경 정의 `ml/pyproject.toml`, `ml/uv.lock` 및 이 문서

모듈 경로를 유지하고 저장소 루트에서 Python 3.12 환경으로 실행합니다. 런타임 버전은
manifest에 기록되며 PyTorch·torchvision·NumPy·Pillow·OpenCV가 필요합니다. Expo 앱에서
Python 체크포인트를 직접 import하는 방식은 아닙니다.

```python
from pathlib import Path
from server.nia.recommendation import RecommendationAnalyzer

# 프로세스당 한 번 생성. 첫 analyze에서 가중치를 로드한 뒤 재사용합니다.
analyzer = RecommendationAnalyzer("ml/runs/skin-recommendation-v1")
features = analyzer.analyze(Path("local-test-photo.jpg").read_bytes())
```

CLI로도 로컬 추론을 확인할 수 있습니다.

```powershell
uv run --project ml python -m server.nia.recommendation infer --bundle ml/runs/skin-recommendation-v1 --image local-test-photo.jpg
```

기존 프로젝트의 얼굴 영상 비전송 정책은 유지합니다. 이 로더는 로컬 연구용이며,
앱 탑재에는 별도의 기기 내 실행 형식 변환과 성능 검증이 필요합니다. 서버에서 얼굴 사진을
받는 운영 API를 이 작업에서 추가하지 않습니다.

## 출력과 추천의 연결

출력 schema는 `skin-recommendation-features-v1`입니다. `features`에는 아래 10개 값만 있습니다.

- `acne`: 정상 0 / 여드름성 패턴 1
- `pore_grade_cheek_image_left`, `pore_grade_cheek_image_right`: 0~5
- `pigmentation_grade_forehead`, `pigmentation_grade_cheek_image_left`,
  `pigmentation_grade_cheek_image_right`: 0~5
- `wrinkle_grade_forehead`, `wrinkle_grade_glabella`, `wrinkle_grade_eye_image_left`,
  `wrinkle_grade_eye_image_right`: 0~6

좌우는 사진 기준입니다. 네 항목이지만 부위를 보존하므로 숫자는 10개입니다. 임의 평균이나
최댓값으로 합치지 않습니다. 부위를 통합하는 추천 정책은 기능 개발 단계에서 별도로 정합니다.

`feature_status`, `provenance`, `roi_method`, 검증 상태와 여드름 score/threshold도 함께
반환합니다. 실패한 값은 null이며 정상 0으로 대체하지 않습니다. 얼굴 이미지나 Crop은
이 출력에 포함되지 않습니다. 여드름 score는 중증도·보정된 확률이 아닙니다.

성분·상품을 고르는 추천 로직은 이 출력의 다음 단계이며 아직 구현하지 않았습니다.
여드름성 패턴은 진정 케어 우선 조건으로, 나머지는 각 등급과 부위에 맞는 추천 입력으로
사용합니다. 높은 합성 평가 성능이나 로딩 성공이 실사 정확도를 보증하지 않습니다.
자동 ROI와 각 모델의 실제 사진 품질 검증 상태는 기존 연구 문서의 제한을 그대로 유지합니다.
