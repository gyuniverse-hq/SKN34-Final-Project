# 립 자연스러움 채점표 v2 실험

## v2로 바꾼 근거

v1 담당자 시범 완료 10장의 장당 시간 중앙값 170.5초, 최소 39초, 최대 369초. 중앙값을 104장에 단순 적용하면 약 295.53분(4시간 55분 32초)이다. 출처: `research/data/lip_rubric/_v1_archive/pilot/R0_ratings.csv`. 화면에 켜 둔 시간도 포함될 수 있는 단순 추정이다. v2는 54회 채점이지만 실제 소요 시간은 v2 시범 채점 전 미확인이다.

## 실행 상태

- LaPa test를 비상업 연구 목적으로 사용한다. 사람 라벨과 ID의 정확성은 별도로 검증되지 않았다. 입력: `research/data/lip_rubric/candidates_reviewed.csv`.
- 생성한 본 채점 항목: 렌더 38장, 스티커 6장, 실제 기준 6장과 반복 4장으로 총 54장. 연습 3장은 별도 인물이다. 출처: `research/data/lip_rubric/pack/key.csv`, `research/data/lip_rubric/pack/manifest.json`.
- 렌더 제형: 글로시 15장, 새틴 15장, 매트 8장. 맨입술 인물 ITA 구간: q1 6명, q2 5명, q3 6명, q4 2명. 출처: `research/data/lip_rubric/pack/key.csv`.
- 본 채점의 얼굴 단위 분할: pool 17명, test 8명. 원본 기준 test는 렌더 12장, 스티커 2장, 실제 기준 2장이다. 출처: `research/data/lip_rubric/pack/key.csv`.
- 고정 벤치마크 SHA-256: `99d553a9b74a44bdd3bfc7aa0d2126108afe145ec60e9ff17c6434793a327489`. 출처: `research/data/lip_rubric/benchmark/benchmark_v1.json`. 생성 시 Git 작업 트리가 dirty였으며 렌더러 커밋·파일별 해시를 `research/data/lip_rubric/pack/manifest.json`에 기록했다.
- 코드 지표: 원본 50장 × 6개 지표로 300개 항목을 DB에 기록했다. 맨입술 기준이 없는 실제 사진의 상관 등은 null이다. 출처: `research/data/lip_rubric/eval.db`의 `code_metrics`. 판정은 하지 않는다.
- v2 사람 시범 채점, 팀원 본 채점: 미실행.
- v2 Colab과 실제 VLM 채점, 렌더러 점수: 미실행.
- 코드 지표는 탐색적 보고만 한다. 정의와 한계: `research/lip_rubric/metrics.py`. L* 95–5 분위 폭, 중앙값 ±3 L* 비율, 고주파 표준편차, 맨입술 고주파 상관, 국소 반사 비율, 법선 방향 L*/채도 10–90% 전이 폭을 입 너비로 정규화한 값이다. 조명과 해상도에 영향을 받으며 임의 합격 기준은 없다.
- VLM 비교는 얼굴 단위 부트스트랩과 사람 기준선, 이웃 평균을 사용하되 작은 검증 표본이므로 예비 판정이다. 결과 파일을 실행 후에만 인용한다.

## 멘토 피드백 대비 아직 해결하지 않은 것

1. 목표 제품의 색·질감 재현: 실물 쌍 기반 재현도는 평가하지 못했고, 20쌍 원본 위치를 확인하지 못했다.
2. 요인별 1~5점과 점수별 설명 척도는 별도로 검증되지 않았다.
3. 팀 밖 독립 평가자는 아직 확보되지 않았다.
4. 불일치 유형 분석은 아직 수행하지 않았다.
5. 최소 의미 차이(MDC)를 이용한 해석 기준은 아직 마련되지 않았다.
6. 구별 설문 정답률 86.7%를 구현도로 해석하지 않는다.
