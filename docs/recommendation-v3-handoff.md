# 추천 V3 팀 적용 안내

2026-11-14. 추천 시스템 V2의 성분 모델을 `recommend-cat-v3`로 선택한다.
분석 점수만 추가한 모델이며 기존 COSING·제품 후보·리뷰·주/보조 고민 정책은 유지한다.
피부 분석 모델 이름은 `skin-analysis-v4`다.

## pull 후 적용

모델과 입력 명세, 보고서는 Git에 함께 포함한다. ZIP 전달이나 코드 패치 적용이 필요하지 않다.

```text
ml/runs/recommend-cat-v3/bundle/
  model.cbm
  manifest.json
  README.md
```

학습 데이터·이미지·원문 상담·사용자별 메타데이터·실험 산출물·환경변수 파일은 포함하지 않는다.
설정과 CatBoost 의존성을 준비한 기존 개발 환경에서는 pull 후 API를 재시작해 사용한다.

```powershell
# 저장소 루트, 최초 1회 또는 의존성 변경 시
uv sync --project backend/api --group recommendation

# 기존 Docker DB/카탈로그를 이용하는 개발 비교 API
uv run --project backend/api --group recommendation python scripts/data/recommendation/run_v2_comparison.py --docker-local
```

백엔드 기본 모델과 `.env.example`은 V3다. 기존 `.env`나 셸에 V2가 있으면
`RECOMMENDATION_MODEL=recommend-cat-v3`로 변경한 뒤 비교 API를 재시작한다.
기존 DB·카탈로그·인증 설정은 필요하다. 모델 교체 때문에 DB 마이그레이션이나 모바일 에셋 준비를 할 필요는 없다.
학습·모델 내보내기도 필요하지 않다.

비교 실행기는 `.env`, `.env.development`, `.env.local`, `.env.development.local`을 뒤의 파일 우선으로 읽고
셸 환경변수가 최우선이다. FastAPI를 직접 시작하면 프로세스 환경변수 또는 `backend/api/.env`를 사용한다.
서버에 별도 모델 볼륨을 사용하면 `RECOMMENDATION_MODELS_DIR` 아래에 같은 폴더 구조를 배치한다.
Docker 이미지는 저장소의 `ml/runs/`를 자동 복사하지 않으므로 별도 서버에는 번들과 CatBoost 의존성을 준비한다.
환경변수 변경은 프로세스 재시작 후 반영된다.

## 동작 확인

응답의 `v2.model.version`이 `recommend-cat-v3`이고 `features`가 10개인지 확인한다.
응답의 `v2` 키는 추천 흐름의 이름이며 모델 버전은 그 안의 `model.version`이다.

범주형 7개는 연령대·성별·피부타입·대상 고민·모공/주름/톤 상태다.
수치형 3개는 모공·주름·색소 원점수 순서이며, 기존 요청의 분석 점수를 그대로 사용한다.
서비스는 manifest에 맞춰 입력을 구성하고 모델 해시·입력 수·범주형 인덱스를 검증한다.
정답·출력은 기존 DB 성분 ID의 80열이며 상위 5성분을 사용한다.

```powershell
# backend/api에서 실행. Git에 포함한 실제 번들로 세 고민의 추론·추천을 확인한다.
uv run --group recommendation pytest tests/test_recommendation_packaged_bundle.py tests/test_recommendation_numeric_features.py tests/test_recommendation_model_config.py
```

## 모델 보고서

학습 자료·고정 설정·V2 기준 모델과의 비교·지표 정의·검증 및 한계는
[번들 설명서 및 평가 보고서](../ml/runs/recommend-cat-v3/bundle/README.md)에 있다.

테스트 결과: R-Precision 80.93%, P@5 67.83%, Recall@5 84.36%,
상위 5개 micro-F1 74.90%, macro-F1(80종) 25.29%다.
테스트는 이미 관찰한 개발 평가셋이며 성분 일치도와 제품 효능·사용 만족도는 구분한다.

## 기존 V2로 전환

기존 V2 번들은 로컬 보존 자료이며 이번 Git 배포에는 포함하지 않는다.
해당 번들을 갖고 있는 환경에서는 `RECOMMENDATION_MODEL=recommend-cat-v2`로 변경하고 API를 재시작한다.
모델 누락이나 입력 계약 오류가 나면 다른 버전으로 자동 대체하지 않는다.
