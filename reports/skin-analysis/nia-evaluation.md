# NIA 원본 모델 평가 환경

2026-10-23 후속 작업에서 로컬 설정의 모공·색소침착·주름 분류 모델을 스마트폰 전용
학습 결과로 교체했습니다. 여드름과 그 외 원본 진단 모델은 보존합니다.
최신 가중치·분할·성능은 [스마트폰 학습 보고서](smartphone-training.md)를 참고하세요.
아래 원본 10종 성능은 이전 가중치의 기록입니다. 원본 비교 설정은 로컬
`nia-private/reports/config.before-smartphone-training.json`에 보존했습니다.
새 모델은 인물 분할이 달라 개발 화면의 기존 분할 기반 배치 평가를 차단합니다.
개별 사진 분석은 새 가중치로 동작하며, 새 모델의 독립 평가는 전용 CLI 결과를 사용합니다.

개발 전용 Expo Router 화면 `/dev/nia`와 로컬 Python 추론 서버입니다. 기존 사용자 화면이나
기존 멀티라벨 학습 프로젝트에는 연결하지 않습니다. 원본 NIA 모델은 재학습하지 않습니다.
프런트엔드는 기존 테마·Button·4개 언어 사전을 사용하며, 추가 앱 의존성은 Expo Go에
포함되는 `expo-image-picker`입니다. Python 의존성은 별도 환경에 설치합니다.

독립 여드름 이진 연구 모델은 선택적으로 연결할 수 있습니다. 설정·학습·평가와 검증 범위는
[여드름 전이학습 문서](acne-transfer-learning.md)를 참고하세요. `config.local.json`의 `acne`가 없거나 null이면
기존 동작과 v1 JSON을 유지합니다. 설정하면 여드름 label·보정 전 score·threshold를 v2에
추가하며, 여드름 실패는 기존 24개 부위 출력에 영향을 주지 않습니다. 이 연결은 로컬
개발 평가 전용이며 운영 앱의 기기 내 분석·얼굴 영상 비전송 정책을 변경하지 않습니다.

## 현재 확인된 것과 미확인 항목

- 조사 기준: [공식 소스 커밋 3e17047](https://github.com/leejeongho3214/NIA/tree/3e1704799587bef889e11203612eba46b529a66a).
  `tool/test.py`, `main.py`, `model.py`, `data_loader.py`, `img_crop.py`, `utils.py`를 확인했습니다.
- 현재 작업 장비에는 사용자가 제공한 원본 체크포인트 10개, 공식 분할 JSON과 AI-Hub
  데이터를 연결했습니다. 파일과 로컬 설정은 Git에서 제외되며, 다른 장비에서는 별도로
  확보해야 합니다. 원본 가중치를 변경하지 않고 텐서 동일성을 확인한 안전 로더용 사본을 사용합니다.
- 자산 검증과 실제 평가 결과는 로컬 `nia-private/reports/README.md`에 있습니다.
  스마트폰 주름 평가의 사용 가능 부분집합 1,962개에서 정확도 33.08%였습니다.
  누락 표본과 학습·검증 분할의 인물 중복이 있으므로 독립적인 일반화 성능으로 볼 수 없습니다.
- 개발 장비에서 PyTorch CUDA 12.6 및 NVIDIA GeForce RTX 4070 Ti SUPER 인식을 확인했습니다.
  장치 인식은 모델 성능 검증이 아닙니다. Expo Go 실기기 검증은 남아 있습니다.
- `tool/utils.py`의 저장 형식은 `model_state`, `epoch`, `best_loss`, `batch_size`, `info`를 가진
  딕셔너리입니다. 원본 아카이브 구조·텐서·등급 수·라벨 부위 ID를 확인했습니다.
  공개 평가 코드의 입력은 256px이나, 체크포인트의 학습 당시 해상도는 미확인입니다.

## 사진 한 장으로 통합 지표 테스트

`/dev/nia`의 기본 탭 **사진 한 장 · 피부 지표**에서 JPEG/PNG를 선택한 후
**전체 피부 지표 분석**을 누릅니다. 좌표 입력이나 개별 모델 로드는 필요하지 않습니다.

- 기존 OpenCV에 포함된 Haar cascade로 정방향 정면 얼굴 한 개를 찾고, 얼굴 박스 비율로
  이마·미간·양쪽 눈가·양쪽 볼·입술·턱 후보 영역을 만듭니다. 얼굴이 없거나 여러 개면 실패하며
  임의로 전체 이미지를 부위 모델에 넣지 않습니다. 측면·가림·기울어진 얼굴은 검출에 실패할 수 있습니다.
- `profile.py`의 후보 영역은 NIA 학습 주석과 일치한다고 검증되지 않았습니다. 기존 AR 랜드마크와
  별개인 실험용 전처리이며 자동 ROI 성능이나 피부 지표 정확도를 주장하지 않습니다.
- 설정된 10개 체크포인트를 자동 검증·로드해 24개 부위별 예측을 실행합니다. 좌우는 **사진 기준**이며,
  부위·분류/회귀 척도를 합치거나 임의의 0~100 점수로 바꾸지 않습니다. 원본 facepart 0인
  색소침착 회귀는 공개 전처리와 동일하게 원본 이미지 전체를 사용합니다.
- **건조 모델의 대상은 입술(facepart 7)**입니다. 기존 NIA에는 건성·지성·복합성 분류와
  유분·여드름 모델이 없습니다. 여드름은 별도의 선택적 이진 연구 모델로 보완하며,
  미설정이면 `unsupported/null`입니다. 누락 모델/실패 출력도 `null`이며 0으로 대체하지 않습니다.
- UI는 요약값, 실제 Crop·확률 분포·원본 예측 상세, ML 입력 JSON 다운로드/공유를 제공합니다.
  JSON의 `features`는 숫자/null, `feature_status`는 출력 상태, `provenance`는 모델 해시·척도·부위·Crop입니다.
  `experimental_unvalidated`, `training_roi_match: false`, `softmax_calibrated: false`를 함께 전달합니다.
- `POST profile`은 이미지 한 번 업로드 후 백그라운드 job을 반환합니다. 기존 `GET job?id=...`로
  진행 상황과 결과를 조회합니다. 사진은 디스크에 저장하지 않으며 이미지/Crop은 ML JSON에 포함하지 않습니다.
  데이터셋 평가와 같은 단일 worker/lock을 사용합니다. 탭을 바꿔도 진행 중인 사진 작업 상태를 유지합니다.

현재 장비에서 실제 스마트폰 사진 한 장을 업로드해 24개 출력·미지원 null 3개·JSON 다운로드·
실제 Crop 24개·새 사진 선택 시 결과 초기화를 390px 웹 화면에서 확인했습니다. 이는 기능 검증이며
정답과 비교한 정확도 검증이 아닙니다. 실제 출력 예시는 로컬 `nia-private/reports/one-photo-ml-input.json`입니다.

## 공식 코드 조사 결과

`test.py`는 `torchvision.models.resnet50(num_classes=...)`를 피부 항목별로 만듭니다.
하나의 다중 헤드 모델이 아닙니다. 분류는 argmax/Softmax, 회귀는 선형 단일 출력이며
sigmoid나 출력값 clipping을 추가하지 않습니다.

| 항목 | 분류 출력 / 등급 | 회귀 원래 단위 역변환 |
|---|---|---|
| wrinkle | 7 / 0–6 | 해당 없음 |
| dryness | 5 / 0–4 | 해당 없음 |
| pigmentation | 6 / 0–5 | ×350 |
| pore | 6 / 0–5 | ×2600 |
| sagging | 6 / 0–5 | 해당 없음 |
| moisture | 해당 없음 | ×100 |
| elasticity_R2 | 해당 없음 | ×1 |
| wrinkle_Ra | 해당 없음 | ×50 |

회귀의 배율은 `data_loader.py::norm_reg`, `model.py::get_test_loss`에서 확인했습니다.
물리 단위의 이름은 코드만으로 확정하지 않으며 설정에 근거와 함께 입력해야 합니다.
주름 분류의 split key는 `forehead_wrinkle`, `glabellus_wrinkle`, `perocular_wrinkle`입니다.
눈가·볼의 좌우처럼 하나의 split key에 여러 facepart ID가 대응할 수 있으므로 ID 배열을
지원합니다. 번호를 랜드마크 인덱스에서 추정하지 않습니다. 원본 NIA에는 여드름·피부톤
모델이 없으며, 선택적 여드름 모델은 `server/acne/`에서 별도로 로드합니다.

전처리는 원본 `img_crop.py`와 평가용 `data_loader.py`를 연결한 과정입니다.

1. OpenCV JPEG/PNG 디코딩(BGR, 기본 EXIF 처리).
2. annotation bbox `[x1,y1,x2,y2]`의 중심을 정수로 내림하고 긴 변의 절반을 정수화.
   해당 중심의 정사각 ROI를 이미지 경계에서 clip. facepart 0은 원본 전체 사용.
3. OpenCV bilinear로 256×256 resize → 기본 JPEG 품질로 저장·재읽기.
4. RGB → PIL `Resize((256,256), antialias=True)` → `ToTensor()`.
5. ImageNet mean `[.485,.456,.406]`, std `[.229,.224,.225]`로 정규화.

공식 `cropped_img`가 있으면 해당 JPEG를 직접 읽습니다. 없으면 위의 Crop·JPEG 왕복을
메모리에서 재현하며 파일을 만들지 않습니다. 미리보기는 실제 입력 텐서의 정규화 직전 RGB입니다.
기존 AR의 MediaPipe 랜드마크는 메이크업 좌표 용도이며 NIA ROI 일치 근거가 없어 재사용하지 않습니다.
기존 **단일 이미지** 탭에서는 원본 픽셀 ROI를 직접 입력하고 확인해야 합니다. **수동 ROI의 위치가 학습
ROI와 일치한다는 보장은 없으며**, 결과와 함께 그 한계를 표시합니다. 입력 좌표 범위 오류는 거절합니다.

원본 테스트 스크립트를 직접 실행하지 않는 이유:

- `~/dir/NIA`로 작업 경로 고정, `.cuda()` 강제 실행.
- 잘못된 checkpoint 경로 처리에서 디렉터리를 삭제하는 코드와 평가 로그 삭제 코드 존재.
- 체크포인트가 없는 일부 항목도 초기화된 모델로 평가할 수 있음.
- `weights_only=False`, `strict=False` 로딩으로 안전성·불일치 검사가 부족함.
- 일부 잘못된 인자 처리에서 `raise` 누락, 누락된 Crop을 조용히 건너뜀.

어댑터는 이 스크립트를 import하거나 원본 파일을 변경하지 않습니다.
[연구 소개](https://leejeongho3214.github.io/NIA/)의 CoAtNet-4 결과를 현재 ResNet-50 실측값으로
표시하지 않습니다. 라이브러리 버전 차이에 따른 원본 환경과의 차이는 별도로 검증해야 합니다.

2026-10-23에 [가중치 출처·전처리 확인](checkpoint-provenance.md)을 추가했습니다.
공개 `main.py`는 Train과 Val을 합쳐 학습하고 Test를 검증·체크포인트 선택에 사용합니다.
따라서 제공된 파일 이름이 Test라는 사실만으로 모델 선택에도 사용하지 않은 최종 평가셋이라고
판단하지 않습니다. 실제 배포 가중치의 실행 인자·학습 해상도·촬영 기기는 기록이 없어
확정할 수 없습니다. 저장된 batch size는 256이며, 공개 코드의 기본값이나 논문의 비교 실험
설정으로 이를 대체하지 않습니다.

## 실행 (저장소 루트의 PowerShell)

```powershell
uv sync --project ml --locked
Copy-Item server/nia/config.example.json server/nia/config.local.json
```

임의의 32자 이상 비밀값을 생성해 루트 `.env`의 `NIA_EVAL_TOKEN`과 Python 터미널의
같은 환경변수에 설정하세요. 비밀값에 `EXPO_PUBLIC_` 접두사를 붙이지 마세요.

```powershell
# 터미널 1: .env에 기록한 것과 같은 값. 실제 토큰은 Git에 저장하지 않습니다.
$env:NIA_EVAL_TOKEN = '<same-random-secret-with-at-least-32-characters>'
uv run --project ml python -m server.nia.service

# 터미널 2: Expo는 루트 .env를 읽습니다.
npm run web
```

브라우저에서 `http://localhost:8081/dev/nia`를 엽니다. 일반 앱 메뉴에는 링크를 추가하지 않습니다.
Expo Go에서도 개발 서버의 `/dev/nia` 경로로 접근할 수 있습니다. 네트워크·딥링크 동작은
실기기에서 확인해야 합니다. 현재 `ml/uv.lock`은 Windows AMD64 / Python 3.12 / CUDA 12.6용입니다.
Linux/macOS에서 재현하려면 해당 플랫폼의 의존성을 별도로 검증해야 합니다.

Python은 `127.0.0.1:8765`에만 바인딩하고 매 요청의 토큰을 검사합니다. Expo API가
`NIA_EVAL_TOKEN`을 서버에서만 읽어 프록시합니다. 두 프로세스는 같은 호스트에서 실행합니다.
`NIA_EVAL_PORT`로 포트를 변경할 경우 양쪽에 같은 값을 설정합니다.
API는 `NODE_ENV=development`에서만 열리며 production/test/미지정에서는 404입니다.
UI도 `__DEV__`일 때만 평가 컴포넌트를 렌더합니다. 관리자 권한 시스템은 추가하지 않았습니다.
개발 서버 자체에 접속 가능한 사람은 평가 화면에 접근할 수 있으므로 접근 가능한 로컬 개발망에서 실행합니다.

설정 파일이 없어도 서버와 화면이 열리고 미확보 상태를 표시합니다. `models: []`는 정상적인
초기 상태입니다. 설정 변경 후에는 Python 서버를 재시작하고 화면의 상태를 새로고침합니다.

## 실제 체크포인트 연결

가중치·사진·라벨·분할·보고서는 무시되는 `nia-private/` 또는 저장소 외부에 보관합니다.
원본 `state_dict.bin`을 수정하지 말고 SHA-256을 확인합니다.

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath 'R:/private/NIA/checkpoint/class/1st_cnn/save_model/wrinkle/state_dict.bin'
```

`config.local.json`의 모델 예시입니다. 아래의 빈 배열과 placeholder는 **의도적으로 로딩을
차단**합니다. 배포 아카이브의 설정·실제 라벨을 검토한 뒤 확인된 값으로 채워야 합니다.

```json
{
  "models": [{
    "id": "nia-original-wrinkle",
    "task": "class/wrinkle",
    "architecture": "resnet50",
    "resolution": 256,
    "checkpoint": "R:/private/NIA/checkpoint/class/1st_cnn/save_model/wrinkle/state_dict.bin",
    "sha256": "<64-character-sha256>",
    "source": "<archive origin, acquisition record and integrity evidence>",
    "label_evidence": "<reviewed archive config / label grade order and facepart mapping>",
    "grades": [0, 1, 2, 3, 4, 5, 6],
    "areas": {
      "forehead_wrinkle": [],
      "glabellus_wrinkle": [],
      "perocular_wrinkle": []
    }
  }],
  "dataset_roots": ["R:/private/NIA/dataset"],
  "allow_dataset_previews": false,
  "metadata_evidence": null
}
```

각 배열을 검증한 `images.facepart` 번호로 채우거나, 확인되지 않은 부위의 key 자체를 제거하세요.
회귀 모델은 `task: "regression/wrinkle_Ra"` 등으로 지정하고 실제 단위의 `unit`을 추가합니다.
허용되는 항목·부위는 [catalog.py](../../server/nia/catalog.py)에 있습니다. archive의 해상도가 256이 아니거나
아키텍처가 다른 경우에는 로딩을 차단하며 해당 전처리/구조를 먼저 확인해야 합니다.

화면에서 체크포인트를 선택하고 **검증 및 로드**를 누르면 SHA-256, 전체 state_dict 키/shape,
fc 출력 차원, 비유한 텐서를 검사합니다. `model.eval()`과 `torch.inference_mode()`를 사용합니다.
파일 해시 일치는 파일 식별·변경 검출이지 배포자의 서명 검증이 아닙니다. `source`와
`label_evidence`는 운영자가 확인한 근거이며 자동으로 사실 여부를 판정하지 않습니다.

로더는 `torch.load(..., weights_only=True)`만 허용하며 `strict=True`를 적용합니다.
구형 pickle/NumPy 메타데이터 때문에 안전 로딩이 거절되면 오류를 표시합니다. 자동으로
`weights_only=False`를 재시도하지 않습니다. 이 경우 배포자에게 텐서·기본 타입 메타데이터만
포함하는 안전한 별도 export를 요청하고, 그 파일의 출처·해시를 별도 기록해야 합니다.
원본 체크포인트는 그대로 보존합니다. 실제 아카이브가 확보되면 이 호환성부터 확인해야 합니다.

## 데이터와 분할 연결

공식 디렉터리 형태를 유지합니다. 화면에서 입력하는 분할/CSV 경로는 데이터셋 루트 기준입니다.

```text
R:/private/NIA/dataset/
  img/<equ>/<subject>/<original filename>.jpg
  label/<equ>/<subject>/<subject>_<equ>_<angle>_<facepart>.json
  cropped_img/<equ>/<subject>/<subject>_<equ>_<angle>_<facepart>.jpg  # 있으면 우선 사용
  split/class/digital_camera/1_testset_info.json
  split/class/digital_camera/1_trainset_info.json
  split/class/digital_camera/1_valset_info.json
```

분할은 `{ "forehead_wrinkle": ["Sub_0001_Equ_1_Angle_0_Area_1", ...], ... }` 형태입니다.
이 descriptor의 번호는 **형식 설명용**이며 실제 부위 번호를 확정하지 않습니다.
라벨은 `annotations`(분류), `equipment`(회귀), `images.bbox`, `images.facepart`,
`info.filename`을 읽습니다. 원본 코드의 substring 선택 결과가 둘 이상이면 임의 선택하지
않고 실패합니다. 이미지·라벨 누락, 잘못된 범위, 반복 표본, 알려지지 않은 분할 형식도 중단합니다.
추출한 실제 라벨·부위와 체크포인트 설정의 일치 여부를 검사합니다.

공식 분할이 없고 원본 라벨만 있다면 화면에서 **공식 테스트 분할 없이 원본 라벨 사용**을
선택하고 `label` 또는 `label/1` 같은 디렉터리를 지정할 수 있습니다. 확인된 항목·부위의
원본 라벨에서 평가 표본을 구성하며 임의로 train/test를 생성하지 않습니다. 이 이미지들은
학습 표본을 포함할 수 있고, 분할 독립성은 기본적으로 미검증입니다. 보고서의
`dataset.selection_source`에서 공식 분할 기반 평가와 구분합니다.

장비는 공식 descriptor의 Equ 1/2/3을 DSLR/tablet/smartphone으로 구분합니다.
여러 장비를 한 보고서에서 비교하려면 같은 seed/mode의 공식 분할을 key별로 연결한
JSON을 로컬에 준비하고 원본 파일의 출처를 보관하세요. 서로 다른 seed를 섞지 마세요.
화면은 한 체크포인트의 모든 확인된 부위 또는 선택한 부위, 전체 장비 또는 한 장비를 평가합니다.

학습·검증 분할까지 입력하면 전체 제공 split의 `Sub` ID를 비교해 테스트와의 인물 중복을
검사합니다. 둘 중 하나라도 없으면 독립성은 미검증입니다. 중복이 있으면 독립적인 일반화
평가로 표시하지 않습니다. 이 검사는 **제공된 분할 파일 범위**에 한하며 다른 seed·누락된 장비의
누수를 보장하지 않습니다. `Sub`의 전역 동일인 식별 의미도 실제 배포 라벨에서 확인해야 합니다.

선택 메타데이터 CSV는 다음 열을 사용합니다. `sample_id`는 공식 descriptor와 같습니다.

```csv
sample_id,age_group,skin_tone,population
```

연령·피부톤·인구집단을 이미지나 파일명에서 추론하지 않습니다. 해당 열의 관측값과 출처가
실제로 있을 때만 채우고, config의 `metadata_evidence`에 수집·동의·라벨링 근거를 기록합니다.
정보가 없는 표본은 해당 하위그룹 지표에서 제외되며 전체 지표에는 포함됩니다. 그룹별 n을
함께 표시합니다. NIA 데이터만으로 글로벌 성능을 측정했다는 주장을 하지 않습니다.

## 지표·시간·이미지 취급

- 분류: Accuracy, MAE, ±1 Grade Accuracy, 전체 checkpoint 등급 기준 Macro F1,
  등급별 P/R/F1·support·예측 수, 혼동행렬. 관측이 없는 등급의 P/R/F1은 0입니다.
- 회귀: 원래 단위로 역변환한 뒤 MAE/RMSE/Pearson, 정답·예측 분포 및 산점도.
  n<2 또는 어느 한쪽의 분산이 0이면 Pearson은 null/계산 불가입니다.
- 단일 사용자 사진에는 정답이 없으므로 정확도 지표를 만들지 않습니다.
- 부위·기기·실제 등급별 지표, 근거가 제공된 인구통계별 지표를 보고서에 기록합니다.
- JSON에는 체크포인트 절대 경로·SHA-256·출처·라벨 근거·실행 장치·라이브러리 버전,
  설정·split/annotation/image 해시·누수 검사·전체 표본 결과를 기록합니다.
  CSV는 표본별 결과와 checkpoint hash/task/device/settings를 포함합니다.
  완전한 재현 정보는 JSON을 함께 보관하세요. 웹은 파일 다운로드, 모바일은 시스템 공유를 사용합니다.
- 초기 load 시간은 해시 검증·CPU 로딩·구조 검사·GPU 이동을 포함하며, 워밍업 3회 시간과 분리합니다.
  추론은 batch=1, float32, `inference_mode`이며 CUDA는 전후 동기화합니다. 평균/P50/P95는
  워밍업 이후 값입니다. P95는 선형 보간입니다. 여러 모델/부위를 순서대로 실행하는 총 시간도 제공합니다.
- 전처리 시간은 디코딩·Crop·JPEG 왕복·RGB·정규화·장치 이동 및 동기화를 포함합니다.
  단일 이미지의 PNG 진단 미리보기 생성 비용도 포함되며 데이터셋 평가는 PNG 생성 비용을 제외합니다.
  단일 요청 server 시간은 이미지 base64 디코딩 이후가 아니라 그 직전부터 추론 결과 조립까지의
  서비스 처리 시간입니다. HTTP 본문 수신·JSON 파싱·응답 직렬화와 Expo 프록시 비용은 제외됩니다.
  클라이언트 왕복−서비스 시간은 전송 부가 시간으로 별도 표시하며 업로드 단독 시간으로 부르지 않습니다.
- GPU 값은 모델 load 전후의 allocated bytes 차이와 추론 중 **프로세스 전체** peak allocated bytes입니다.
  다른 로드 모델과 입력·활성 텐서도 peak에 포함됩니다. 드라이버 전체 사용량이나 모델별 peak로
  오해하지 마세요. CPU에서는 GPU 값이 null입니다. CUDA 가용 시 GPU, 아니면 CPU로 fallback합니다.
- 지연 차트는 전체 관측, 산점도는 모바일 렌더링 성능을 위해 최대 약 300점으로 고르게 표시합니다.
  JSON/CSV에는 전체 결과가 있습니다. 고오차 표본은 상위 20개를 표시합니다.
- 원본 사진·Crop은 서버에서 디스크에 새로 쓰지 않습니다. 결과는 메모리에 최대 4개 job만 유지하며
  서버 재시작/새 job에 따른 제거 후에는 다시 평가해야 합니다. 실패한 job은 부분 성능을 발표하지 않습니다.
  동시에 한 데이터셋 평가만 받으며 GPU 실행은 lock으로 직렬화합니다.
- 데이터셋 이미지 열람은 기본 비활성화입니다. 이용 조건이 허용하는 로컬 개발 환경에서만
  `allow_dataset_previews: true`로 설정하세요. 이때 선택한 256px Crop만 메모리에서 전달하고
  `no-store`를 적용합니다. 외부 이미지 호스팅/업로드는 없습니다. JSON/CSV의 식별자도 개인정보로
  관리하고 필요한 범위에서만 내보내세요.

## 검증

```powershell
npm run check
uv run --project ml python -m unittest discover -s server/nia/tests -v
```

Python 테스트는 작은 인공 배열로 지표·정규화 역변환·예외를 확인합니다. Crop/JPEG 전처리는
독립적으로 재현한 공식 디스크 왕복과 텐서가 정확히 같은지 검사합니다. 누락 가중치, hash/head
불일치, backbone 누락의 strict 로딩 거절, ROI 오류, 경로 이탈, 인물 중복, 모호한 라벨도 검사합니다.
테스트 더블의 고정 출력은 계산 경로 검증만을 위한 것으로 실제 서버 모델이나 성능 결과에
등록하지 않습니다. Jest는 production/test/미지정 환경의 접근 차단과 토큰 비노출 프록시를 검사합니다.

2026-10-22 검증: `npm run check`(typecheck·lint·Jest 6 suites / 31 tests), Python unittest
21개가 통과했습니다. 이전 단계에서 웹 production export와 실제 HTTP의 토큰 미제공 403, Expo 프록시
상태 응답을 확인했습니다. Edge의 390×844 화면에서 미확보 안내·단일 추론 비활성화·데이터셋
탭 전환·평가 비활성화·가로 넘침 없음·브라우저 pageerror 없음을 확인했습니다.
이 초기 화면 검증은 원본 모델 성능 검증이나 Expo Go 실기기 검증을 의미하지 않습니다.

추가 검증 대상은 체크포인트 학습 해상도·등급 의미, 자동 ROI와 학습 주석의 일치,
주름 이외 모델의 정답 기반 성능, 독립된 인물/촬영 환경에서의 성능,
Expo Go의 사진 선택·미리보기·서버 접근·내보내기입니다.

글로벌 후속 검증에는 동일인/세션/원본 중복이 배제된 외부 데이터, 서비스 환경의 다양한 스마트폰·조명·
각도·압축·화장 조건, 합의된 주름 등급 정답과 ROI, 수집 동의 및 실제 관측한 연령·피부톤·인구집단
메타데이터가 필요합니다. 집단별 충분한 표본과 독립된 holdout을 확보하고 그 평가 이전에
분할을 고정해야 합니다.
