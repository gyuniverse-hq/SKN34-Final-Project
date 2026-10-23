# 피부 분석 실험·학습 환경

이 환경은 피부 모델 연구와 로컬 개발 도구입니다. 운영 앱의 제품 추천 연결·기기 내 모델
탑재가 완료됐다는 의미는 아닙니다. 실험 브랜치를 삭제한 뒤에도 코드·설정·lockfile과
이 문서들로 다음 개선 작업을 시작할 수 있도록 관리합니다.

## 문서

| 문서 | 내용 |
|---|---|
| [전체 성능 평가](full-performance-evaluation.md) | NIA 10종·여드름 1종의 실제 평가, 기기별 지표·등급별 오류·인물 중복·해석 한계 |
| [가중치 출처·전처리 확인](checkpoint-provenance.md) | 배포 가중치의 저장 설정·평가 통계, 공식 코드와의 일치 여부, 논문 결과와 비교 가능한 범위 |
| [스마트폰 전용 학습](smartphone-training.md) | 선별한 세 분류 모델의 스마트폰 전용 학습·인물 분리·재현 및 평가 |
| [CB Focal 비교](cb-focal-experiment.md) | 기존 모델을 보존한 모공 손실 함수 비교·검증 결과·확대 기준 |
| [여드름 전이학습](acne-transfer-learning.md) | 정상/여드름 이진 학습, ImageNet·NIA 비교, 평가·한계 |
| [NIA 평가 도구](nia-evaluation.md) | 기존 모델 연결, 개발 화면, 로컬 서버·평가 방법 |
| [추천 입력 선정](recommendation-inputs.md) | 네 항목 선정과 수분 제외 근거 |
| [모델 인계](model-handoff.md) | 네 모델 묶음 내보내기·복원·로딩 계약 |
| [실험 결과 요약](experiment-summary.md) | 공유 가능한 집계 수치와 해석 |
| [멀티라벨 학습](multilabel-training.md) | 별도 데이터 감사·학습 파이프라인. 현재 추천용 모델과 구분 |

## 폴더 역할

```text
ml/
  src/skin_analysis/           데이터 감사·전처리·학습·평가·추론
    acne/                      독립 여드름 이진 분류 실험
  configs/                     공유 설정과 검수 자료 예제
  tests/                       합성 데이터 기반 자동 테스트
  runs/                        로컬 실험 산출물·가중치 (Git 제외)
  pyproject.toml, uv.lock       Python 3.12 독립 환경
server/
  nia/, acne/                  로컬 Python 추론·평가와 모델 묶음 로더
  services/niaEvaluationService.ts  개발 전용 API 게이트웨이
app/dev/, app/api/dev/         개발 화면·개발 API 진입점
hooks/useNia*.ts              사진 분석·평가 결과 요청과 화면 상태 조합
components/nia/               평가 화면 구성 요소
reports/skin-analysis/        실행 문서·결정·공유 가능한 결과 요약
```

## 새 장비·새 브랜치에서 시작

1. 최신 `develop`에서 목적에 맞는 작업 브랜치를 만듭니다.
2. 저장소 루트에서 `uv sync --project ml --locked`로 Python 환경을 복원합니다.
   현재 lockfile의 검증 범위는 Windows AMD64 / Python 3.12 / CUDA 12.6입니다.
3. 승인된 데이터·원본 NIA 가중치·분할 또는 내보낸 모델 묶음을 별도로 배치합니다.
   Git에는 이 자산들이 포함되지 않습니다. 기존 개발 PC의 로컬 파일은 백업이 아닙니다.
4. `ml/configs/`의 데이터 경로·GPU UUID를 새 장비에 맞게 확인하고,
   `server/nia/config.example.json`을 복사해 로컬 경로와 SHA-256을 설정합니다.
5. 해당 실험 문서의 감사·학습·평가 명령을 실행합니다. 기존 run은 덮어쓰지 않습니다.
6. 개선 코드는 테스트와 함께 커밋하고, 결과·한계는 이 폴더에 갱신합니다.

모델 묶음만 사용하는 경우 [모델 인계](model-handoff.md)의 로딩 절차로 시작합니다.
실험 기록의 seed·설정·가중치 해시·데이터 분할 fingerprint를 함께 보존해야 합니다.
큰 자산을 별도 보관소로 전달할 때도 폴더 전체와 manifest를 함께 관리합니다.

## 검사

저장소 루트에서 실행합니다. 테스트는 원본 데이터나 가중치를 다운로드하지 않습니다.

```powershell
uv run --project ml ruff check ml
uv run --project ml python -m pytest ml/tests -q
uv run --project ml python -m unittest discover -s server/nia/tests -v
npm run check
```

기능 검사가 통과해도 실제 사진 정확도 검증을 대신하지 않습니다. 공유 수치는
[전체 성능 평가](full-performance-evaluation.md)의 데이터·전처리·평가 범위와 함께 해석합니다.
