# 피부 모델 선정 및 실험 통합 보고서

- `model-selection-evidence-20261030.md`: 최종 네 모델의 선정 이유, 배치·head·손실 근거, 10/27~30 모공 실험 흐름과 성능.
- `figures/`: 보고서에서 직접 참조하는 학습 곡선과 집계 그래프. `weekly/` 및 `equipment-*`는 실험 세부 그래프다.
- `Data_scale_chart.md`, `device-grade-distribution.json`, `device-grade-distribution.py`: 기기별 데이터 규모 스냅샷과 집계 코드·집계 결과. 코드 실행에는 원본 데이터와 Git 제외 로컬 manifest가 필요하다.
- `model-selection-settings-evidence-20261030.json`, `plot-model-selection-settings-20261030.py`: 배치·head 비교의 익명 집계와 두 그래프 재생성 코드.

이 폴더에는 원본 얼굴 사진이나 개인별 ROI를 포함하지 않는다. Test 분할을 반복 관찰한 탐색 실험이며, 본 문서만으로 독립 일반화 성능을 보증하지 않는다.
