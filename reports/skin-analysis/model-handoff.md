# 네 항목 피부 분석 모델 인계

## pull 후 테스트 페이지 실행 (Windows x64)

Node.js와 uv가 설치된 환경에서 저장소를 pull한 뒤 아래 순서로 실행합니다.
가중치는 팀 공유 Drive에서 `recommendation-bundle` **전체**를 받아 아래에 배치합니다.
Drive 공유 링크는 배포 담당자가 공유할 예정이며 현재 저장소에는 없습니다.

```text
ml/runs/nia-smartphone-sam-seed-42/recommendation-bundle/
  manifest.json
  weights/acne.pt
  weights/pore.bin
  weights/pigmentation.bin
  weights/wrinkle.bin
```

저장소 루트에서:

```powershell
npm ci
npm run nia:test
```

이후 앱 의존성이 바뀌지 않았다면 `npm run nia:test`만 실행합니다.
첫 실행은 `uv run --locked --project ml`이 Python 3.12 및 잠금 파일의 의존성을
자동 준비하므로 인터넷과 다운로드 시간이 필요합니다. 미리 설치하려면
`uv sync --project ml --locked`를 사용합니다. 현재 ML 잠금 환경은 Windows x64용입니다.
GPU는 필요하지 않으며 이 명령은 CPU로 실행합니다. CUDA 빌드의 PyTorch가 설치되지만
GPU를 사용하지 않습니다. macOS/Linux용 의존성 구성은 이 작업에 포함하지 않았습니다.

실행기가 네 가중치의 SHA-256을 검증하고 Python 서버 준비 후 Expo를 실행합니다.
Metro 준비 완료 후 **http://localhost:8083/dev/nia** 에서 사진을 선택하고 분석합니다.
선정한 여드름·모공·색소침착·주름만 실행합니다. 데이터셋 원본은 사진 테스트에 필요하지 않습니다.
직접 `config.local.json`이나 `.env`를 작성할 필요가 없고 기존 파일도 변경하지 않습니다.
인증 토큰은 실행마다 생성해 두 하위 프로세스에만 전달합니다. Ctrl+C로 둘 다 종료합니다.
기존 Expo가 실행 중이면 종료한 뒤 실행하세요. 기존 서버에 자동으로 붙지 않습니다.

다른 위치의 모델은 `NIA_EVAL_BUNDLE`, 포트 충돌은 `NIA_EVAL_PORT`(기본 8765)와
`NIA_WEB_PORT`(기본 8083)를 해당 터미널에서 지정할 수 있습니다.
Python과 Expo는 localhost 전용이며 이 명령은 PC 웹 연구 화면용입니다.
가중치 오류·누락은 서버 시작 단계에서 차단합니다. 사진에서 얼굴을 찾지 못하면 분석은
실패할 수 있고, CPU 속도와 자동 ROI의 실사 정확도는 별도 검증 대상입니다.

선정: 여드름 이진 분류, 모공 등급(0~5), 색소침착 등급(0~5), 주름 등급(0~6).
수분·탄력·처짐·입술 건조·모공/색소침착/주름 회귀 모델은 추천용 추론에서 실행하지 않습니다.

## 현재 사용할 모델 묶음

최종 선정 방침은 모공·색소침착·주름의 WCE+AdamW+SAM이다. 최신 인계 경로는
`ml/runs/nia-smartphone-sam-seed-42/recommendation-bundle/`이며 평가·해시와
항목별 한계는 [최종 종합보고서](final-model-report.md)를 따른다. 여드름 모델은 유지한다.
이전 묶음의 지표는 [통합 근거](experiment-evidence.json)에 보존하고, 현재 활성 참조를
제외한 과거 묶음 파일은 정리했다. 최종 묶음에서도 원본 세부 등급을
유지하며 모공만 필요에 따라 예측 등급을 `0·1 / 2·3 / 4·5`로 묶는다.
선정 당시에는 테스트 페이지 설정을 바꾸지 않았으며, 후속 작업에서 개발용
`/dev/nia`만 최종 SAM 묶음으로 연결했다. 운영 화면과 앱 기기 내 추론은 별도다.

2026-10-23 스마트폰 전용 모공·색소침착·주름 분류 학습과 평가를 완료했습니다.
최초 연구용 묶음은 `ml/runs/nia-smartphone-seed-42/recommendation-bundle/`입니다.
세 분류 모델은 ImageNet V2에서 새로 학습했고 여드름 모델은 기존 선택본을 유지합니다.
실제 성능과 등급별 한계는 [스마트폰 학습 보고서](smartphone-training.md)를 확인합니다.

`ml/runs/skin-recommendation-v1/`는 이전 묶음의 역사적 경로이며 현재 사용하지 않습니다.
다른 브랜치·장비에 인계할 때 최신 묶음 전체와 해당 보고서를 함께 전달합니다.

## 저장 단위

하나의 새 추천 모델을 학습한 것이 아니라 **독립적인 분석 모델 4개**를 묶습니다.
여드름은 기존에 학습해 선택한 ImageNet 초기화 모델의 `inference.pt`입니다.
최신 묶음의 나머지 3개는 스마트폰 전용 SAM 학습 결과입니다. 이전 v1은 원본 NIA
분류 체크포인트의 안전 로더용 사본을 사용했던 기록입니다.

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
uv run --project ml python -m server.nia.recommendation export --config ml/runs/nia-smartphone-sam-seed-42/config.selected.json --output ml/runs/skin-recommendation-export
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
analyzer = RecommendationAnalyzer("ml/runs/nia-smartphone-sam-seed-42/recommendation-bundle")
features = analyzer.analyze(Path("local-test-photo.jpg").read_bytes())
```

CLI로도 로컬 추론을 확인할 수 있습니다.

```powershell
uv run --project ml python -m server.nia.recommendation infer --bundle ml/runs/nia-smartphone-sam-seed-42/recommendation-bundle --image local-test-photo.jpg
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
