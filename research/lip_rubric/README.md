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
9. `colab/lip_judge.ipynb`를 비공개 Drive와 Colab GPU에서 실행합니다. `judges.json`에는 2026-11-12에 확인한 두 모델의 리비전이 들어 있으니 실행 전에 모델 카드를 다시 확인하세요. CLIP은 모델 카드에 라이선스 표기가 없고 배포 서비스 사용이 범위 밖이므로 이 연구 실험에만 씁니다. 노트북 4단계는 VLM 없이 "비슷한 3장의 사람 평균" 방식을 렌더 전체에서 시험합니다(`judge.py --knn-output <JSON> --knn-only`). 결과 CSV를 내려받아 `& $py research/lip_rubric/db.py import-judge <CSV>`로 넣고 `& $py research/lip_rubric/analyze.py`로 분석합니다. 여러 실행이 있으면 `--run-id`를 지정합니다.
9-1. A/B 비교 시험(절대 점수 대신 두 장 중 더 자연스러운 쪽 고르기): `research/lip_rubric`에서 `& ../../$py pairwise.py build`로 사람 5명 평균 점수에서 쌍을 만들고(`results/pairs_truth.csv`는 정답 포함·로컬 전용, `results/pairs.csv`는 정답 없음), `pairwise.py export`로 `pairwise_pack.zip`과 SHA-256을 만듭니다. `colab/lip_pairwise.ipynb`를 T4에서 실행해 받은 `pairwise_results.csv`를 `results/`에 두고 `pairwise.py analyze`로 판정합니다. 판정 규칙은 `pairwise.py` 맨 위에 실행 전에 고정했습니다.
9-2. 체크별 예시 프롬프트 시험: `research/lip_rubric`에서 `rubric_examples.py build`로 체크마다 사람 예·아니오 예시를 고르고 기준별 사진첩(`results/rubric_gallery.html`, 로컬 전용)을 만듭니다. `rubric_examples.py export`로 `rubric_examples_pack.zip`과 SHA-256을 만들고, `colab/lip_rubric_examples.ipynb`를 T4에서 실행한 뒤 받은 `rubric_examples_results.csv`를 `results/`에 두고 `rubric_examples.py analyze`로 판정합니다.
10. 렌더러 수정 전후 고정 사진을 재측정할 때 `& $py research/lip_rubric/bench.py --benchmark research/data/lip_rubric/benchmark/benchmark_v1.json --label before`를 실행합니다. 다음 측정 때 `--compare <이전_run_id>`를 추가합니다. 데이터가 작으면 차이의 신뢰구간을 함께 보고하며 합격 판정은 하지 않습니다.

## 팀원 안내

압축 해제한 폴더의 `index.html`을 Chrome으로 열고 이름이 아닌 R1 같은 코드를 입력한 뒤 폴더를 선택하세요. 연습 3장과 본 채점 54장이 있습니다. 본인의 장당 시간 중앙값에 따른 남은 시간이 표시됩니다. Y는 예, N은 아니오, A는 허용된 항목의 해당 없음입니다. 두세 번 이상 나눠 진행할 수 있고, 같은 기기와 Chrome에서 이어갑니다. 평가자끼리 상의하지 말고, 끝나면 CSV만 담당자에게 보내고 사진을 삭제해 주세요.

## 데이터 규칙과 제한

얼굴 이미지와 결과는 Git 제외된 `research/data/lip_rubric/`에만 둡니다. LaPa test만 사용하며 팀원 사진은 금지합니다. Colab/Drive는 이 실험의 비공개 폴더만 사용하고 실험 종료 후 삭제합니다. 외부 VLM API는 사용하지 않습니다. v2 실험 사진 수가 작고 사람의 얼굴 ID 검토가 틀릴 수 있으므로 VLM 결과는 예비 판정입니다. 실제 사진과 렌더는 짝이 아니며 발색 재현도는 판단하지 않습니다. 코드 지표는 `metrics.py`의 정의를 따르는 탐색용 수치입니다.

## 사람 라벨 학습 (2026-11-16)

프롬프트 VLM은 종료했고, R5 checklist 절대점수(01–03) + A/B 쌍으로 고정 인코더·작은 헤드를 학습한다.

```powershell
ml/.venv/Scripts/python.exe research/lip_rubric/learn.py all
```

산출: `research/data/lip_rubric/learn/`(라벨·임베딩·모델, Git 제외), 요약 `research/lip_rubric/LEARN_RESULTS.md`. 결함 이름은 특징으로 쓰지 않으며 앱에 연결하지 않는다.

## Astra 라벨 증류 확인 (2026-11-19)

Astra(OpenAI)가 v2 채점표로 `expansion_v3_openai_pool`의 1,659장(얼굴 667명)을 채점한 CSV를 `research/data/lip_rubric/astra/`에 둔다. 매트는 윤기 체크 3개(q3_2~q3_4)를 해당 없음으로 바꿔 R5와 같은 규칙으로 총점을 계산한다. 고정 ResNet18 + Ridge를 Astra 라벨로만 학습하고, Astra가 보지 않은 R5 사람 라벨(checklist 98장, A/B 476쌍)로 시험한다.

```powershell
ml/.venv/Scripts/python.exe research/lip_rubric/learn_astra.py all
```

결과(`research/data/lip_rubric/learn_astra/fit_summary.json`): R5 98장 Spearman 0.50(얼굴 단위 95% CI 약 0.3~0.67), R5만으로 학습한 0.31보다 높다. 렌더끼리만 보면 0.35, A/B 476쌍 일치 0.66(R5 쌍으로 직접 학습한 헤드는 0.81). Astra 평균 총점 1.85로 R5(3.13)보다 엄하므로 점수 수준이 아니라 순위로만 비교한다. 4,080장은 사람이 원래 입술 상태를 확인하지 않은 얼굴이다.

고정 인코더 점수 bakeoff(같은 Astra 1,659장 → Ridge, 같은 R5 98장 홀드아웃; A/B는 보지 않음):

```powershell
ml/.venv/Scripts/python.exe research/lip_rubric/learn_astra.py all --encoder resnet18
ml/.venv/Scripts/python.exe research/lip_rubric/learn_astra.py all --encoder efficientnet_b0
ml/.venv/Scripts/python.exe research/lip_rubric/learn_astra.py all --encoder efficientnet_b3
ml/.venv/Scripts/python.exe research/lip_rubric/learn_astra.py all --encoder convnext_tiny
ml/.venv/Scripts/python.exe research/lip_rubric/learn_astra.py all --encoder dinov2_vits14
```

| 모델 | R5 Spearman | R5 MAE | 렌더끼리 Spearman | kind 순서 |
|---|---|---|---|---|
| ResNet18 고정 + Ridge | 0.501 | 1.60 | 0.349 | sticker < render < real |
| EfficientNet-B0 고정 + Ridge | 0.374 | — | 0.21 | ok |
| EfficientNet-B3 고정 + Ridge | 0.397 | 1.54 | 0.259 | ok |
| ConvNeXt-Tiny 고정 + Ridge | 0.497 | 1.51 | 0.360 | ok |
| **DINOv2-ViT-S/14 고정 + Ridge** | **0.515** | **1.49** | **0.410** | ok |

DINOv2가 홀드아웃에서 가장 높지만 ResNet18과 CI가 크게 겹친다(약 0.30~0.69 vs 0.30~0.66). 요약 JSON은 `fit_summary.json`(ResNet18)과 `fit_summary_<encoder>.json`.

DINOv2 가중 MSE + AdamW 헤드 (`finetune_dinov2.py`, 백본 고정·Dropout+Linear, 12에폭, 저/고득점·합격선 구간 가중):

```powershell
ml/.venv/Scripts/python.exe research/lip_rubric/finetune_dinov2.py
```

R5 Spearman **0.303** · MAE **1.80** · bias −1.27 → 같은 임베딩의 Ridge(**0.515**)보다 나쁨. 스크린샷 채점은 계속 **고정 DINOv2 + Ridge**. 가중치 `finetune_dinov2_head.pt`(Git 제외).

분포·산점도(R5 98장):

```powershell
ml/.venv/Scripts/python.exe research/lip_rubric/plot_score_dist.py
```

출력: `research/data/lip_rubric/learn_astra/dist_plots/<encoder>/` — `scatter_human_vs_pred.png`, `hist_scores.png`, `hist_residual.png`, `bar_by_kind.png`, `stats.json`. DINOv2는 사람 평균 3.13 vs 예측 2.13(편향 −1.0), 예측 분산이 사람보다 훨씬 좁다(std 0.57 vs 1.60).

(참고) B0 fine-tuning 가중치는 `finetune_b0.pt`(Git 제외). A/B 476쌍에서는 B0 FT가 0.72까지 올랐으나 절대 점수 목표는 아님.

### 합격선 후보 갤러리 · 스크린샷 점수 (2026-11-19)

사람 R5 총점 ≥4.0 사진(38장, 그중 ≥4.5는 25장) 갤러리에서 사용자가 21장을 합격 앵커로 고름(`pass_gallery/pass_anchors.json`). 앵커 점수 4.0~5.0(중앙값 4.8, 평균 4.68). **확정 합격선 4.68/5 (사람 채점표, 앵커 평균)**. 자동 모델 점수는 합격 판정에 직접 쓰지 않는다.

```powershell
ml/.venv/Scripts/python.exe research/lip_rubric/make_pass_gallery.py
# 열기: research/data/lip_rubric/learn_astra/pass_gallery/index.html
```

평가지표 브리핑 PDF (타임라인·개념·분포 그림·합격선·칼리브):

```powershell
ml/.venv/Scripts/python.exe research/lip_rubric/export_eval_report_pdf.py
```

출력: `research/data/lip_rubric/learn_astra/lip_eval_metrics_briefing_20261119.pdf`

스토리 흐름 PDF (25체크 → 사람5명 → Qwen실패 → 사다리+R5 → R5만학습 → Astra증류 → 칼리브):

```powershell
ml/.venv/Scripts/python.exe research/lip_rubric/export_eval_story_pdf.py
```

출력: `research/data/lip_rubric/learn_astra/lip_eval_story_flow_20261119.pdf`

외부 평가지표 레퍼런스 1쪽 요약 (토요일 제출용):

```powershell
ml/.venv/Scripts/python.exe research/lip_rubric/export_eval_refs_pdf.py
```

출력: `reports/lip_eval_external_refs_1p_20261120.pdf` (동일본 `research/data/lip_rubric/learn_astra/`)

사람 척도 칼리브레이션(R5 isotonic → 합격선 4.68과 같은 눈금):

```powershell
ml/.venv/Scripts/python.exe research/lip_rubric/calibrate_score.py --encoder dinov2_vits14
```

출력 `calibration_dinov2_vits14.json`. R5에서 raw MAE 1.49·real 평균 2.73 → 보정 후 MAE ~0.89(전체 fit)·CV MAE ~1.03, real 평균 ~4.03. `compare_score`/`score_capture`는 보정 점수를 기본으로 씀.

폰/렌더 스크린샷 → 입술 crop → 보정 점수:

```powershell
research/ar_evaluation/.venv/Scripts/python.exe research/lip_rubric/score_capture.py path\to\shot.png
```

출력: `calibrated_score`, `pass`(≥4.68).

### 점수 모델로 전후 비교 (2026-11-19)

절대 점수 헤드로 before/after crop을 재는 도구:

```powershell
# DINOv2 고정 + Ridge (기본, bakeoff 최고)
ml/.venv/Scripts/python.exe research/lip_rubric/compare_score.py pairs <pairs.csv> --out <out_dir>
# 참고용 B0 fine-tune
ml/.venv/Scripts/python.exe research/lip_rubric/compare_b0.py pairs <pairs.csv>
ml/.venv/Scripts/python.exe research/lip_rubric/compare_b0.py pool-sanity
```

- B0 pool-sanity: openai_pool 같은 얼굴 `current` vs `*:strong` → current 승률 **0.827**.
- TUNING `creaseGain` 1.0→1.4 (16쌍, crop MAD ~0.07): B0 승률 **0.50**, DINOv2 승률 **0.625**이나 평균 Δ ≈ 0 → 미세 TUNING만으로는 판정이 흔들림.
- 맨입술 고주파를 립에 되돌린 이미지 공간 탐침(16쌍, MAD ~0.31): DINOv2 승률 **0.688**, ResNet18 **1.0**, B0 **~0.56** → “색은 유지하고 결만 더 남기기” 방향은 점수 모델이 선호. 앱 셰이더 반영·Expo Go 확인은 별도.

## 추가 이미지 평가 (2026-11-14)

- 기존 5명 평균 총점 기준 렌더 38장은 0~1점 1장, 1~2점 4장, 2~3점 14장, 3~4점 13장, 4~5점 6장이다(상한 5 포함). 스티커 6장과 실제 립 기준 6장은 이 렌더 분포에서 제외했다. 점수 구간은 합격 기준이 아니다.
- `expand_pack.py`는 기존 본 평가와 연습에 쓴 얼굴을 제외하고 검토된 LaPa test 얼굴을 사용한다. 동일 인물에 제형 5종과 기본·결 약화·과한 광택 등 실험 설정을 적용하고 스티커·실제 립도 포함한다. 이 설정은 앱을 변경하지 않으며 점수 라벨이 아니다. 고정 벤치마크와 이전 평가 파일을 덮어쓰지 않는다. 동일 얼굴의 여러 사진은 독립 인물이 아니므로 사람 단위로 분할·분석한다. 기존 얼굴 ID 검토의 한계도 그대로다.
- 생성: `research/ar_evaluation/.venv/Scripts/python.exe research/lip_rubric/expand_pack.py`. 기본 출력은 `research/data/lip_rubric/expansion_20261114/`이며 이미 존재하면 중단한다. 본 평가 묶음은 약 50장씩 나뉘며 각 묶음에 같은 이미지의 반복 4장과 별도 연습 3장이 포함된다. 각 묶음의 `rating_pack` 폴더를 열거나 같은 이름 ZIP을 팀원에게 전달한다. 원본 인물 정보·정답표(`key.csv`)·매니페스트·중간 렌더는 전달하지 않는다.
- 같은 v2 가이드와 예시를 사용한다. 가이드는 기존 시범 평가자의 판단이라 새 채점에도 영향을 줄 수 있다. 각 묶음은 브라우저에서 평가자 코드와 묶음별로 따로 저장된다. 완료 후 각 묶음에서 CSV를 내려받아 담당자에게 전달한다. 다운로드 이름에 평가자 코드와 묶음 해시 앞부분이 들어간다.
- 채점 전 예측 점수는 없고 평가 후에만 사람 점수 분포를 집계한다. 제형·입 모양·피부톤 및 실험 설정별 편향과 평가자 간 차이를 확인한다. 새로운 얼굴 수가 이미지 수보다 훨씬 적고 스티커·광택 과장 설정은 합성 실패 사례이므로 운영 AR의 자연스러운 분포나 고득점 자료가 충분하다고 보장하지 않는다. 기존 test 얼굴은 새 후보에서 제외하지만 인물 ID의 정확성은 별도 검증이 필요하다.
- 새 묶음 DB 등록은 `db.py import-pack <pack_번호>`로 묶음별 수행하며, CSV는 해당 pack을 먼저 등록한 뒤 `db.py import-ratings <CSV>`로 가져온다. 생성 단계에서는 기존 DB를 변경하지 않는다. 여러 묶음을 등록한 후 집계하려면 `aggregate.py --pack-id <manifest의 pack_sha256> --output <새 결과 폴더>`를 묶음마다 실행한다. 기존 `results/`는 덮어쓰지 않는다. 원본 데이터셋은 비상업 연구에만 사용하고 사진·결과는 Git에 올리지 않는다.
- 모든 추가 묶음의 점수대 합산은 `expansion_scores.py`를 실행한다. 기본값은 사진마다 5명 이상 채점된 경우만 평균 총점과 점수 구간을 산출하며, 미완료 사진은 미채점으로 남긴다(`--min-raters`로 변경 가능). 반복 사진은 분포에서 제외하고 실제 사진·스티커·AR 렌더를 구분한다. 결과 폴더가 이미 있으면 덮어쓰지 않는다.
