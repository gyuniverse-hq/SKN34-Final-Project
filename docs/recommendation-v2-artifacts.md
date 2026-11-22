# V2 모델·데이터 인계와 구버전 정리

기준일은 2026-11-14다. Git에는 실행 코드·테스트·재학습 도구·설계 문서를 공유한다.
사용자 승인으로 추천 V3의 모델 가중치·manifest·설명서는 Git에 함께 배포한다.
그 외 모델, 학습 원문, 검수 결정 원본, 개인별 분석 메타데이터와 실험 산출물은 로컬에 보존한다.
새 clone은 동봉된 V3로 추론할 수 있으며 재학습에는 별도 데이터가 필요하다.

## 실행·재학습 자료

| 목적 | 로컬 기본 경로 | 필요한 파일 |
|---|---|---|
| 추천 추론 (새 V3, Git 동봉) | `ml/runs/recommend-cat-v3/bundle/` | `model.cbm`, `manifest.json`, `README.md` |
| 기존 V2 회귀 검증 | `ml/runs/recommend-cat-v2/bundle/` | `model.cbm`, `manifest.json` |
| 재학습 | `ml/data/recommendation-v2/reviewed-20261114/` | `training.jsonl`, `validation.jsonl`, `test.jsonl`, `protocol.json`, `folds.json` |
| 입력·정답 사전 | `ml/data/recommendation-v2/reviewed-20261114/` | `encoding_metadata.json` |
| 기존 모델 회귀 검증 | `ml/experiments/recommendation-v2-image-feature-replacement-20261111/` | 기존 테스트셋 및 `image/test_predictions.npz` |
| 로컬 API smoke 사례 추출 | `ml/data/recommendation-v2/model-ready-20261111/` | `x_metadata.csv` |

V3의 세 파일은 pull 시 배치된다. 나머지 로컬 자료는 기존 별도 인계 방식을 따른다.
V3의 실행·입력·평가·한계는 [번들 설명서](../ml/runs/recommend-cat-v3/bundle/README.md)에 있다.
추천 서비스는 `RECOMMENDATION_MODEL=recommend-cat-v3`로 새 모델을 선택한다. 변경 후 API를 재시작한다.
기본 위치는 피부 분석 원본과 같은 `ml/runs/<모델 이름>/bundle/`이며, 서버 마운트 경로는
`RECOMMENDATION_MODELS_DIR`로 바꿀 수 있다. 두 파일을 함께 전달하며 `manifest.json`의 `version`은 선택한 모델 이름과 같아야 한다.
이름·모델 SHA-256·입력 순서·범주·80성분 ID 계약을 검증하며 파일이 없거나 계약이 다르면 다른 모델로 대체하지 않는다.
기존 경로 지정 변수 `RECOMMENDATION_V2_BUNDLE`은 더 이상 사용하지 않는다.
재학습 도구는 `--source`, `--schema`, `--output`으로 다른 경로를 지정할 수 있다.
서비스 코드의 리뷰 사전분포는 고정 계수이므로 과거 실험 JSON을 요청마다 읽지 않는다.

DB에는 발행된 스킨케어 카탈로그와 원본 성분·COSING·리뷰 자료가 필요하다.
비교 도구는 기존 V1 API를 별도 HTTP로 호출하며 카탈로그는 읽기 전용으로 조회한다.
로그인한 비교의 추천·반응 기록에는 `0020`이 필요하며 현재 로컬 DB에는 적용되어 있다.
모델 이름·배치 경로 변경에는 추가 DB 마이그레이션이 없다.

## 현재 모델과 검증 범위

새 V3는 검수 후 5,273행의 같은 분할에서 분석 점수만 추가한 모델이다. 입력은 기존 7개 범주형과
모공·주름·색소 수치 점수 3개다. 반복 상담 가중치 조정과 정답 대안 집합 구성은 적용하지 않았다.
`model.cbm`의 SHA-256은 `9ff5c76348efb934911a3179b6a221dd9b7afc2ce3a559ceceef8158a25f9c37`이며,
native 저장·재로딩 후 테스트 792행의 예측이 실험 결과와 일치했다. 테스트 R-Precision 80.93%,
P@5 67.83%, Recall@5 84.36%, Top-5 micro-F1 74.90%, Top-5 macro-F1(80종) 25.29%다.
V2 제품 후보·COSING·리뷰·주/보조 고민 로직을 유지하며 성분 모델만 manifest에 따라 전환한다.

아래는 보존한 기존 V2 모델의 기록이다.

- `recommend-cat-v2`는 기존 `replacement-catboost-20261111`의 가중치를 그대로 사용한다. 기존 로컬 번들은 보존했다.
- 새 manifest의 `version`은 `recommend-cat-v2`, `sourceVersion`은 기존 이름이다. `model.cbm`의 SHA-256은 `1f1e8453ae5d7c10f5f6b205a2bc1c6a574ba966b8a6d64d7e39cb12ab1b6b2f`다.
- CatBoost 입력: 연령대·성별·피부타입·대상 고민·모공·주름·톤의 7개 범주형 값.
- 정답: DB 성분 ID에 대응하는 80열 멀티핫. 추론은 상위 5성분을 사용한다.
- 최종 5,289행: 학습 3,702 / 검증 794 / 테스트 793. 원본·이미지 그룹 중복을 고려한 분할을 유지한다.
- 고정 설정 재학습에서 기존 모델과 검증·테스트 확률 차이 0.0을 확인했다.

2026-11-14 원문 재검수 후 다음 재학습 입력은 5,273행(학습 3,689 / 검증 792 / 테스트 792)이다.
기존 5,289행의 구간·입력값을 보존하면서 추정 8행·제외 3행·보류 5행을 학습 대상에서 분리했다.
남은 162행에서 성분 정답을 보정했으며 미네랄솔트 40행은 유지했다.
80개 성분의 열 순서는 유지하고 실제 7개 입력·행수·입력 해시를 새 인코딩 사전에 기록했다.
원문·엑셀 대조 및 보류 5행은 로컬 `reports/recommendation-v2/audit-20261114/`에 보존한다.
검수 후 7입력 재학습 모델은 `ml/experiments/recommendation-v2-reviewed-catboost-20261114/`에 보존했다.
분석 점수 추가·반복 상담 가중치 조정·두 방법 적용 비교는
`ml/experiments/recommendation-v2-score-weight-ablation-20261114/report.md`에 기록했다.
아래 수치는 기존 5,289행 기반 V2 모델의 기록이다.

| 구간 | P@5 | Recall@5 | Precision micro | macro-F1 (80종) |
|---|---:|---:|---:|---:|
| 검증 | 0.661965 | 0.827330 | 0.618908 | 0.258177 |
| 테스트 | 0.659269 | 0.825641 | 0.608017 | 0.256711 |

이는 성분 정답과의 일치도다. 최종 제품의 효능·사용 만족 정확도를 의미하지 않는다.
이미 관찰한 테스트셋의 재현 확인이며 독립적인 신규 평가가 아니다. 모바일 입력과 학습 ROI 전처리의 동등성도 별도 검증 대상이다.

## 변경 과정과 폐기 범위

1. 자연어 성분 추출 후 사전·지식 엑셀·검수 규칙으로 확정/추정/제외를 구분했다.
2. RF/CatBoost 4개 입력 모델, 탐색 방식, 희귀 라벨 오버샘플링, Precision·macro-F1·추천 제공률 제약을 비교했다.
3. 원문 피부상태와 분석 결과의 추가·대체를 비교한 뒤 현재 7개 입력 모델과 분할을 보존했다.
4. 성분→COSING→제품 연결에 리뷰의 경험적 베이즈·보수적 평점·피부타입 적합성·주/보조 고민을 반영했다.

사용자 승인으로 로컬 구버전 1,853파일(6.868 GiB)을 삭제했다. 중간 전처리 사본, 구형 추천 모델·산출물, NIA SAM 번들, 미등록 모바일 번들, 해당 전용 코드·설정이 대상이다.
현재 V2 번들·재학습 자료와 **skin-analysis-v3/v4 및 등록 모바일 번들**은 보존했다. 지정한 161개 파일의 SHA-256 불변을 확인했다.
공유 `mobile_export.py`에는 v3/v4가 사용하는 해시·검증 입력 생성 함수가 남아 있다.
구버전 전체 재현은 보장하지 않는다. 최종 데이터에서의 재학습은 별도 도구로 지원한다.

상세 변경·검수 기록·삭제 파일 해시는 로컬 `reports/recommendation-v2/cleanup-20261112/`에 보존했다.
이 경로와 `ml/experiments/`의 실험별 보고서·결과는 Git 공유 대상이 아니다.

현재 실행법은 [추천 도구 안내](../scripts/data/recommendation/README.md), 입력·순위 정책은 [V2 비교 설계](recommendation-v2-comparison.md)를 따른다.
