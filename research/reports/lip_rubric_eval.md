# 립 자연스러움 채점표 추가 실험

- 상태: 사람 채점 **미실행**, Colab 및 실제 VLM 채점 **미실행**. 렌더러 점수와 VLM 성능 결과 없음.
- 범위: 립 시뮬레이션 현실감. 점수 5는 실제로 바른 것처럼 보인다는 뜻이며 실물 정답과의 일치가 아니다. 색 정확도와 부착은 별도 지표다.
- 데이터: LaPa test, 비상업 연구용. 예외는 이 실험의 비공개 채점 및 Colab에만 한정된다. 얼굴 ID는 사람 확인이 필요하며 오인 가능성이 남는다.
- 후보 추출: 2,000장 중 얼굴 검출 1,969장, 미검출 31장. 출처: `research/data/lip_rubric/candidates.csv`, `research/data/lip_rubric/selection_metadata.json`. 임시 인물 ID는 1,838개이며 인물 수로 해석하면 안 된다. 사람 확인은 미실행.
- 사람 신뢰도 및 렌더러 점수: 미실행 (`research/data/lip_rubric/results/human_summary.json` 생성 전).
- VLM·이웃 기준선 비교 및 판정: 미실행 (`research/data/lip_rubric/results/judge_summary.json` 생성 전).
- 모델 ID와 리비전: `research/lip_rubric/judges.json`. 실행 전 모델 카드와 라이선스를 다시 확인한다. 임베딩 모델 라이선스 확인 안 됨.
- 담당자 본 채점 참여 여부: 미정. 실제 참여 시 기록한다.
- 제한: 작은 test 표본의 넓은 신뢰구간, LaPa 단일 출처, 인물 ID 오인, 사전 연습의 영향을 함께 보고한다.
