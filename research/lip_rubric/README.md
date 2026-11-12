# 숫자 평가 요약 게시

실험 실행·얼굴 자료는 기존 연구 브랜치의 로컬 데이터에 둔다. 이 브랜치에는 게시 도구와 숫자 픽스처만 포함한다. 비상업 모델·얼굴 픽셀을 관리자 웹에 포함하지 않는다.

저장소 루트에서 먼저 dry-run으로 검토한다. 경로는 실제 연구 작업 공간으로 지정한다.

```powershell
uv run --project backend/api python research/lip_rubric/publish_eval.py --db <local-eval.db> --results <results-directory> --benchmark <benchmark-manifest.json> --dry-run
```

eval.db는 SQLite read-only 모드로 열고 runs 메타데이터·코드 집계에 필요한 컬럼만 읽는다. human_summary.json에서 렌더의 요인·그룹 추정치·얼굴 부트스트랩 CI만 선택한다. 선택적인 adhoc_severity·adhoc_v2_analysis·adhoc_mdc_disagreement에서 평가자 수가 맞는 렌더 신뢰도·상관·MDC만 선택한다. 전체 50장 ICC를 렌더 38장의 신뢰도로 섞지 않는다. 미측정값은 null이다. 여러 run은 --run-id로 지정한다.

`--kind bench`는 해당 코드 실행의 지표별 중앙값·표본 수만 보낸다. 계산되지 않은 CI·사람 점수는 채우지 않는다. VLM judge 결과는 실제 판정 후 별도 형식 검토가 필요하며 이번 도구가 임의로 판정하지 않는다. 현재 v2는 사람 5명, 렌더 평균 3.038947…, ICC(2,k) 0.633, MDC95 1.42다. 전체 보고서의 수치와 출처는 원래 연구 브랜치 `research/reports/lip_rubric_eval.md`를 따른다.

검토 후에만 `VISHUE_ADMIN_TOKEN`을 현재 세션 메모리에 설정하고 --dry-run 대신 `--api-base <origin>`을 쓴다. 토큰은 파일에 저장하거나 출력하지 않는다. HTTPS 또는 로컬 HTTP만 허용하고 HTTP redirect는 거부한다. 모든 payload는 백엔드의 Pydantic 계약으로 생성 시·송신 직전에 재검증한다. 실제 업로드는 이번 작업에서 하지 않았다.

```powershell
$env:VISHUE_ADMIN_TOKEN = Read-Host '관리자 access token'
uv run --project backend/api python research/lip_rubric/publish_eval.py --db <local-eval.db> --results <results> --benchmark <manifest.json> --api-base http://127.0.0.1:8000
Remove-Item Env:VISHUE_ADMIN_TOKEN
```

선택 `--paired-comparison <json>`은 동일 얼굴 묶음에서 로컬로 계산한 짝 차이의 숫자 집계만 받는다: `{previousRendererCommit,method:"face-paired-bootstrap",totalDelta:{estimate,low,high,n}}`. 개별 사진/얼굴 ID는 넣지 않는다. 이 값이 없으면 버전 방향은 판정 불가다. 단일 사진 MDC를 버전 평균의 판정선으로 쓰지 않는다.

테스트: `uv run --project backend/api pytest research/lip_rubric/test_publish_eval.py`. HTTP는 모의 객체만 사용한다. v2 숫자 픽스처는 `backend/api/tests/fixtures/admin_eval_v2.json`이며 소스 파일 경로·이미지 ID·평가자 ID는 포함하지 않는다.
