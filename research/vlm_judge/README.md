# AR 메이크업 VLM 평가 연구 도구

연구용 독립 도구다. 앱이나 AR 런타임에서 import하지 않는다. 네 지표 모두 **VLM 추정**이며 ΔE2000·IoU·SSIM의 측정값이 아니다. 외부 API는 얼굴 사진을 OpenAI 서버에 전송하므로 프로젝트의 얼굴 이미지 서버 전송 금지 원칙과 충돌한다. 본 실험의 외부 전송은 이 작업 요청에 명시된 범위에만 한정하고, 사용 권한과 촬영 당사자의 외부 전송 동의를 별도로 확인해야 한다. 앱 사용자 사진은 사용하지 않는다. 사진과 보고서 HTML에는 얼굴이 포함되므로 Git에 올리거나 공개하지 않는다.

## 준비

`research/data/vlm_judge/sets/<세트ID>/`에 같은 인물의 `bare.jpg`(선택), `real.jpg`, `ar.jpg`를 넣는다. PNG도 가능하며 각 역할당 파일 하나만 허용한다. 선택적으로 `meta.json`에 `source`, `finish`, `product`, `skin_group`, `notes`를 넣는다. 서로 다른 조명과 자세는 판단을 왜곡할 수 있다. 사람 설문은 `human/responses.csv`에 `image_id,rater,guess_real,score,regions,reasons`를 넣고 image_id는 `<세트ID>/real` 또는 `<세트ID>/ar`로 지정한다. 이유는 쉼표 또는 세미콜론으로 구분한다.

루트 `.env`에 `OPENAI_API_KEY`와 `ALLOW_EXTERNAL_JUDGE=true`를 설정한다. 기존 앱 코드나 공개 환경 변수에 키를 넣지 않는다. `judges.json`의 `model`은 빈 값으로 제공된다. 이미지 입력과 구조화 출력을 모두 지원하고 해당 계정에서 사용할 수 있는 모델 ID를 직접 지정해야 한다. 실행할 때 모델 목록에 ID가 있는지 확인하지만 목록 조회만으로 이미지·구조화 출력 지원을 보장하지는 않는다. 모델 조회도 외부 호출이므로 플래그와 키가 필요하다. `temperature`는 기본값 `null`이면 전송하지 않으며, 사용하는 모델이 지원할 때만 숫자로 설정한다. 단가는 직접 확인한 경우에만 설정하며, 사전 토큰 수가 없어 plan은 비용을 추정하지 않는다.

공식 문서: [이미지 입력](https://developers.openai.com/api/docs/guides/images-vision) · [구조화 출력](https://developers.openai.com/api/docs/guides/structured-outputs). Responses 요청은 `store=false`로 전송한다. 이는 응답 저장 설정이며 외부 전송이나 서비스의 모든 데이터 처리·보존이 없다는 뜻은 아니다.

선택적으로 `uv sync --extra vision`으로 MediaPipe를 설치하고 로컬 Face Landmarker 모델을 준비해 `judges.json`에 `landmarker_model` 경로를 지정한다. 없거나 검출에 실패하면 사진 중앙 아래 절반으로 대체하며 결과에 `fallback`으로 남긴다. 기본 설치는 MediaPipe나 모델을 다운로드하지 않는다.

## PowerShell 명령

```powershell
cd research/vlm_judge
uv sync
uv run python -m vlm_judge validate --data ../data/vlm_judge
uv run python -m vlm_judge plan --data ../data/vlm_judge
uv run python -m vlm_judge import-existing --src ../data/ar_eval_public --data ../data/vlm_judge
uv run python -m vlm_judge run --data ../data/vlm_judge --seed 42
uv run python -m vlm_judge report --run ../data/vlm_judge/runs/<실행폴더>
```

`import-existing`은 동일 폴더에 `real`과 `ar` 파일이 명시된 세트만 복사한다. 그 외 이름으로 대응 관계를 추측하지 않으며, 같은 ID가 존재하면 중단한다. `--sets a,b`, `--only color,placement,texture,naturalness`, `--no-cache`로 범위를 조정한다. 유효한 세트가 없으면 validate와 plan은 오류로 종료한다. `report`는 네트워크 없이 raw 결과를 다시 집계한다.

## 결과와 해석

`runs/<시간>/raw/`에는 블라인드 질문 순서와 원본 응답, 소요 시간 및 토큰이 있다. `per_set.csv`, `summary.json`, `report.md`는 세트별·전체 결과이며 `report.html`은 얼굴 썸네일을 포함한 **비공개 로컬 파일**이다. 캐시는 `runs/.cache/`에 저장된다. 순서 비교의 동률은 승리로 치지 않는다. 반복 응답을 세트별로 먼저 합산하므로 Wilson 구간의 표본 수는 반복 호출 수가 아니다. 이미지의 실제 출처와 비교 기준 일치 여부를 보장하지 않으며 최종 품질 판정에는 사람 검증이 필요하다.

사람 비교는 이미지당 VLM 중앙 점수와 각 사람 응답을 비교한다. 점수 또는 추측이 부족하면 신뢰 수준은 판단 불가다. 반복 일치율과 순서 바꿈 지표는 질감의 명암 항목과 자연스러움 강제선택을 중심으로 기록한다. 캐시 적중분은 실제 API 토큰 및 지연에 포함하지 않는다.
