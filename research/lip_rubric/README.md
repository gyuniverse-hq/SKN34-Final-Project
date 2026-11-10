# 립 자연스러움 채점표 v1

이 실험은 립의 **시뮬레이션 현실감**만 다룹니다. 5점은 실제로 바른 것처럼 보인다는 뜻이며 실제 정답 사진과의 일치를 뜻하지 않습니다. 색 정확도와 부착은 별도 코드 지표로 평가합니다. Q4는 사용자의 지시에 따라 경계의 시각적 자연스러움으로 재구성했습니다.

LaPa는 비상업 연구용으로만 사용합니다. 이 실험에 한해 LaPa 얼굴을 비공개 Colab/Drive에 두는 예외를 적용합니다. 앱에서 얼굴을 서버로 보내는 허가는 아닙니다. 팀원 얼굴은 이 파이프라인에 넣지 마세요. 실험을 마치면 비공개 저장소와 Colab 임시 복사본을 삭제합니다. `research/data/`는 Git에 넣지 않습니다.

## 담당자 순서

PowerShell에서 저장소 루트 기준으로 실행합니다. Python은 `research/ar_evaluation/.venv/Scripts/python.exe`입니다. 실제 이미지와 결과는 `research/data/lip_rubric/`에만 생성합니다.

1. `research/data/LaPa/test/images/*.jpg`와 `labels/*.png`를 준비합니다. 데이터가 없으면 별도 확보해야 합니다. `python research/lip_rubric/select_faces.py research/data/LaPa/test`로 후보를 만듭니다. 처음부터 전체 후보를 재실행하려면 기존 결과를 백업하세요.
2. `candidate_sheets/`의 사진과 `candidates.csv`를 함께 보며 `human_label`에 맨입술 `bare`, 립스틱 `lipstick`, 제외 `exclude`를 입력합니다. 자동 점수는 참고값일 뿐입니다. 립스틱 후보는 `finish`에 `matte`, `satin`, `glossy`, 또는 모르면 `unknown`을 입력합니다.
3. `face_id`는 파일명 기반 **임시값**입니다. 동일 인물은 같은 값으로, 다른 인물은 다른 값으로 직접 정리하고 검토한 행에만 `identity_reviewed=yes`를 입력합니다. 눈으로 확인할 수 없는 경우 제외하세요. 얼굴 ID 정확도는 보장되지 않습니다. 맨입술 최소 24명과 립스틱 12명이 필요합니다.
4. `python research/lip_rubric/build_pack.py`를 실행합니다. 기존 중간 결과나 채점 묶음을 덮어쓰지 않습니다. Playwright와 로컬 Chrome, 기존 립 렌더러의 MediaPipe 웹 자산 및 모델이 필요합니다. `pack/key.csv`와 `manifest.json`은 담당자 전용입니다.
5. 담당자는 묶음에서 10장을 시범 채점하고 `rating_pack/guide.json`에 예시를 추가합니다. 키는 체크 ID, 값은 `{"pass":{"text":"설명","image":"images/파일.png"},"fail":{"text":"설명","image":"images/파일.png"}}` 형식입니다. 예시 이미지를 배포하려면 반드시 LaPa에서 만든 이미지로 준비하고 파일 해시·출처를 검토하세요. 담당자는 본 채점에 참여하지 않거나 참여 사실을 보고서에 적습니다.
6. `rating_pack/` 폴더만 ZIP으로 압축해 팀원에게 전달합니다. `key.csv`, manifest, 원본 파일명은 전달하지 않습니다. `pack.json`에 반복 여부가 들어 있으므로 내부 파일은 열지 말고 화면으로만 채점합니다.
7. 받은 CSV들을 `results/` 아래에 둔 후 `python research/lip_rubric/aggregate.py research/data/lip_rubric/results/R1.csv research/data/lip_rubric/results/R2.csv`처럼 입력합니다. 자동 집계는 빠른 채점을 표시만 하며 렌더러 점수에 합격선을 적용하지 않습니다.
8. `python research/lip_rubric/make_colab_pack.py`로 원본 해시와 생성 이미지 해시를 검사하고 ZIP 및 SHA-256을 만듭니다. CSV와 ZIP 모두 비공개로 관리하세요. 해시 검사는 지정된 로컬 LaPa 폴더 및 최초 후보 추출 기록과의 일치를 확인하며, 원본 배포처 자체의 진위를 증명하지는 못합니다.
9. `colab/lip_judge.ipynb` 안내에 따라 비공개 Drive와 Colab GPU에서 실행합니다. Hugging Face 모델 카드 라이선스를 확인하고 정확한 모델 revision을 지정하세요. CLIP 라이선스는 확인 안 됨입니다. 세션이 끊기면 같은 설정과 출력 파일로 다시 실행합니다.
10. 결과를 `results/judge_results.csv`에 놓고 `python research/lip_rubric/analyze.py --raters research/data/lip_rubric/results/R1.csv research/data/lip_rubric/results/R2.csv`로 분석합니다. 데이터가 부족하면 판정 불가입니다. 결과 보고서에 수치와 출처 경로를 직접 기록합니다.

## 팀원 안내

Chrome에서 전달받은 폴더의 `index.html`을 열고 본명 대신 담당자가 정한 R1 같은 코드를 입력한 뒤 폴더를 선택하세요. 연습 3장은 결과에서 제외됩니다. 본 채점은 2~3번으로 나누어도 자동 저장된 곳에서 이어갈 수 있습니다. 모든 항목에 답하고 CSV를 내보내 담당자에게 보내 주세요. 최종 제출 후 전달받은 이미지는 삭제하세요. 같은 기기와 브라우저에서만 자동 저장이 유지됩니다.

## 한계

입 상태 0.1은 AR_SPEC의 내측 보간 시작값을 참고한 분류용 휴리스틱입니다. yaw는 도 단위가 아닌 랜드마크 상대 깊이 지표입니다. Monk 참조가 없어 미확인으로 기록합니다. 실제 LaPa에는 각 렌더와 짝이 되는 실물 정답이 없으며, 사람 판정의 불일치와 작은 검증 표본을 함께 보고해야 합니다. 연습은 본 채점 이미지 3장을 미리 보는 방식이므로 학습 효과가 있을 수 있습니다.
