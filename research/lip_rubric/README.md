# 립 자연스러움 채점표 v2

립의 트랙 A 현실감만 평가합니다. 5점은 실제로 바른 것처럼 보인다는 뜻입니다. 실물 발색 정확도와 부착은 별도 지표이며 합격선을 임의로 만들지 않습니다. LaPa는 비상업 연구용이며 실물 정답 쌍이 아닙니다.

현재 고정 벤치마크 `research/data/lip_rubric/benchmark/benchmark_v1.json`의 SHA-256: `99d553a9b74a44bdd3bfc7aa0d2126108afe145ec60e9ff17c6434793a327489`.

## 담당자 진행 순서

PowerShell에서 저장소 루트 기준입니다. 먼저 `$py = 'research/ar_evaluation/.venv/Scripts/python.exe'`를 입력하고 아래 예시는 `& $py ...`로 실행합니다.

1. v1 산출물은 `research/data/lip_rubric/_v1_archive/`에 보관합니다. `candidates.csv`와 `candidates_reviewed.csv`는 원래 위치에 둡니다.
2. `& $py research/lip_rubric/build_pack.py`로 본 채점 54장(고유 50 + 반복 4)과 다른 인물의 연습 3장을 생성합니다. 기본은 맨입술 19명, 립스틱 6명, 셰이드 2종, 스티커 6장입니다. 추가 후보가 필요하면 CSV의 사람 라벨과 인물 ID를 확인해야 합니다. 생성된 고정 목록의 SHA-256은 명령 출력과 `research/data/lip_rubric/benchmark/benchmark_v1.json`에서 확인합니다. 얼굴 ID의 정확성은 사람 확인에 의존합니다.
3. 담당자는 `pack/rating_pack/index.html`을 Chrome에서 열고 `R0`로 연습 3장과 본 채점 10장을 수행한 뒤 CSV를 내보냅니다. R0는 정답표를 아는 시범 평가자이므로 본 DB에 넣지 않습니다.
4. `& $py research/lip_rubric/aggregate.py --pilot <R0_CSV>`로 v2 실제 시범 시간을 확인합니다. 54장 예상 시간이 45분을 넘으면 이미지 수를 줄이거나 15문항 버전을 검토할지 사람이 결정합니다. 어느 것도 자동 선택하지 않습니다. 사진 수를 바꾼 경우 `--count`에 반복을 포함한 본 채점 장수를 지정합니다(예: 44).
5. 시범 결과를 보고 `pack/rating_pack/guide.json`을 작성합니다. 키는 체크 ID이며 값은 `{"pass":{"text":"설명","image":"images/ID_crop.png"},"fail":{"text":"설명","image":"images/ID_crop.png"}}`입니다. 예시는 팀원 채점에 영향을 줄 수 있으므로 그 출처와 사용을 보고합니다.
6. `rating_pack` 폴더만 압축해 R1~R5 등 팀원에게 전달합니다. `key.csv`, 원본 이름, 매니페스트, DB는 전달하지 않습니다.
7. `& $py research/lip_rubric/db.py init` 후 `& $py research/lip_rubric/db.py import-pack research/data/lip_rubric/pack`을 실행합니다. `& $py research/lip_rubric/db.py import-ratings <R1_CSV>`를 사람마다 실행하고 `& $py research/lip_rubric/aggregate.py`로 집계합니다. 같은 CSV는 중복 반영하지 않고 재제출은 최신 파일만 사용하며 이력은 보관합니다. v1 CSV와 R0는 거부합니다.
8. `& $py research/lip_rubric/metrics.py`로 판정 없는 코드 지표를 측정합니다. `& $py research/lip_rubric/db.py export-colab`으로 출처를 검증한 v2 묶음과 SHA-256을 만듭니다.
9. `colab/lip_judge.ipynb`를 비공개 Drive와 Colab GPU에서 실행합니다. 모델 카드의 라이선스와 정확한 리비전을 먼저 확인하세요. 임베딩 모델 라이선스는 확인 안 됨입니다. 결과 CSV를 내려받아 `& $py research/lip_rubric/db.py import-judge <CSV>`로 넣고 `& $py research/lip_rubric/analyze.py`로 분석합니다. 여러 실행이 있으면 `--run-id`를 지정합니다.
10. 렌더러 수정 전후 고정 사진을 재측정할 때 `& $py research/lip_rubric/bench.py --benchmark research/data/lip_rubric/benchmark/benchmark_v1.json --label before`를 실행합니다. 다음 측정 때 `--compare <이전_run_id>`를 추가합니다. 데이터가 작으면 차이의 신뢰구간을 함께 보고하며 합격 판정은 하지 않습니다.

## 팀원 안내

압축 해제한 폴더의 `index.html`을 Chrome으로 열고 이름이 아닌 R1 같은 코드를 입력한 뒤 폴더를 선택하세요. 연습 3장과 본 채점 54장이 있습니다. 본인의 장당 시간 중앙값에 따른 남은 시간이 표시됩니다. Y는 예, N은 아니오, A는 허용된 항목의 해당 없음입니다. 두세 번 이상 나눠 진행할 수 있고, 같은 기기와 Chrome에서 이어갑니다. 평가자끼리 상의하지 말고, 끝나면 CSV만 담당자에게 보내고 사진을 삭제해 주세요.

## 데이터 규칙과 제한

얼굴 이미지와 결과는 Git 제외된 `research/data/lip_rubric/`에만 둡니다. LaPa test만 사용하며 팀원 사진은 금지합니다. Colab/Drive는 이 실험의 비공개 폴더만 사용하고 실험 종료 후 삭제합니다. 외부 VLM API는 사용하지 않습니다. v2 실험 사진 수가 작고 사람의 얼굴 ID 검토가 틀릴 수 있으므로 VLM 결과는 예비 판정입니다. 실제 사진과 렌더는 짝이 아니며 발색 재현도는 판단하지 않습니다. 코드 지표는 `metrics.py`의 정의를 따르는 탐색용 수치입니다.
