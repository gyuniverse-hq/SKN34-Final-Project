# 동일 저장소의 GPU 서버 / Expo 클라이언트 실행

같은 저장소를 clone하지만 역할별로 필요한 의존성만 설치하고 각각 실행한다. 서버는 Python/CUDA API만 실행하고, 사용자 개발 PC는 Node/Metro만 실행한다. 스마트폰은 Expo Go에서 로그인·촬영·가이드를 실행하며 촬영 JPEG 한 장만 GPU 서버에 보낸다. 기기 내 피부 모델은 기본 경로에서 다운로드하거나 실행하지 않는다.

## 사용자 개발 PC

```powershell
npm ci
Copy-Item .env.example .env.local
# .env.local의 기존 Supabase 공개 설정과 일반 백엔드 주소를 입력한다.
npm run client
```

공개 클라이언트 설정:

```dotenv
EXPO_PUBLIC_SUPABASE_URL=https://<project>.supabase.co
EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<publishable-key>
EXPO_PUBLIC_API_BASE_URL=<existing-general-backend>
EXPO_PUBLIC_ENABLE_SKIN_ANALYSIS=1
EXPO_PUBLIC_SKIN_ANALYSIS_MODE=server
EXPO_PUBLIC_SKIN_API_URL=https://send-lots-advanced-amended.trycloudflare.com
EXPO_PUBLIC_SKIN_AUTH_MODE=supabase
```

GPU API 주소와 일반 API 주소를 구분한다. 사용자 환경에는 Python·CUDA·ml/runs·ONNX 가중치가 필요하지 않다. `skin:prepare`도 실행하지 않는다. EAS 모델 준비 hook도 서버 모드에서는 가중치를 요구하지 않는다. Expo Go 카메라 자산은 Metro에서 받으므로 휴대폰과 사용자 개발 PC의 Metro 연결은 필요하다.

### 승인된 전송 대상

현재 사용자가 승인한 대상은 `https://send-lots-advanced-amended.trycloudflare.com` 하나뿐이다. 클라이언트는 `constants/skinServer.ts`의 승인 origin과 설정 URL이 일치해야 요청한다. 이전 LAN 주소, 다른 호스트, 포트, URL 자격증명, 경로·query 및 HTTP redirect는 거절한다. Bearer 토큰은 React Native 요청 코드에만 전달하며 WebView에는 넣지 않는다.

Tunnel은 데스크톱의 `http://127.0.0.1:8000`을 가리키며 이미 실행 중인 것을 사용한다. Tunnel 생성·재시작, DNS·방화벽 변경은 수행하지 않는다. 주소가 응답하지 않으면 연결 실패로 처리한다. 새로운 주소가 필요하면 사용자 승인 후 고정 origin과 환경설정을 함께 바꾼다.

### Expo Go 임시 시험 인증

서버의 `SKIN_AUTH_MODE=test-token` 지원은 커밋 `4fd7965`에 있다. 이 서버에 대한 앱 시험은
Git에서 제외된 `.env.local`에 다음 **공개 설정만** 넣는다. 실제 토큰은 파일에 넣지 않는다.

```dotenv
EXPO_PUBLIC_ENABLE_SKIN_ANALYSIS=1
EXPO_PUBLIC_SKIN_ANALYSIS_MODE=server
EXPO_PUBLIC_SKIN_API_URL=https://send-lots-advanced-amended.trycloudflare.com
EXPO_PUBLIC_SKIN_AUTH_MODE=test-token
```

`npm run client`로 Metro를 실행하고 동일 네트워크의 스마트폰 Expo Go로 접속한다.
기존 Metro가 열려 있으면 앱을 완전히 Reload하여 변경된 공개 설정을 반영한다.
마이페이지 → 피부 정보 등록의 개발용 입력란에 서버 관리자가 제공한 시험 토큰을 직접 입력한다.
서버의 로컬 비밀 설정 파일을 앱에 복사하거나 Metro로 제공하지 않는다.
토큰은 매 촬영마다 다시 입력하며 업로드 시작·취소·앱 비활성화·화면 이탈 시 메모리 참조와 입력란을 지운다.
JavaScript 문자열의 물리적 메모리 소거를 보장하지 않으며 토큰의 영구 보관은 수행하지 않는다.
사진 bytes는 업로드 완료/실패 시 기존 경로에서 0으로 채우고 해제한다.

이 모드는 `__DEV__`에서만 허용한다. 설정을 생략하거나 `supabase`로 지정하면 기존 로그인 경로를 따른다.
누락·잘못된 토큰은 `UNAUTHORIZED`이며 무인증·Supabase 재시도·기기 모델 대체 실행은 하지 않는다.
다른 기능의 인증은 바꾸지 않는다. 이 공유 토큰 방식은 일반 사용자 배포용 인증이 아니다.

공식 문서에서 [SDK 57 SecureStore](https://docs.expo.dev/versions/v57.0.0/sdk/securestore/)의 Expo Go 지원과
생체 인증 옵션 제한을 확인했다. 이번 시험은 영구 보관이 필요 없어 새 의존성 없이 RN의
[`TextInput.secureTextEntry`](https://reactnative.dev/docs/textinput#securetextentry)와 훅의 메모리 참조만 사용한다.
자동 완성·자동 수정·대문자 변환을 끄며 WebView·Zustand·AsyncStorage에 토큰을 전달하지 않는다.
[RN 보안 문서](https://reactnative.dev/docs/security)는 토큰의 AsyncStorage 보관을 금지하며,
[Expo 환경변수 문서](https://docs.expo.dev/guides/environment-variables/)는 `EXPO_PUBLIC_` 값이 번들에 노출됨을 명시한다.

실기기 인수 시험: 토큰 입력 → 기존 가이드에서 자동 촬영 → 10개 feature 응답 검증 → 필수 설문 3개 → 저장 완료를 확인한다.
마이페이지의 피부 분석 시간 화면에서 요청 왕복 `requestMs`와 서버 처리 `serverMs`를 따로 확인한다.
토큰 없이 시작 불가, 틀린 토큰의 거절, 촬영/업로드 중 취소 후 늦은 응답 미반영도 확인한다.

## Windows GPU 서버

Python 3.12, uv, RTX 4070 Ti SUPER를 지원하는 NVIDIA 드라이버를 준비한다. Node와 npm은 필요하지 않다.

1. 기존 `skin-analysis-v2` 번들 전체(manifest.json과 weights 네 파일)를 서버의 `ml/runs/skin-analysis-v2/`에 별도로 배치한다. 가중치는 Git에서 제외되므로 clone만으로 생성되지 않는다.
2. `.env.skin-server.example`을 `.env.skin-server.local`로 복사한다. 기본 `supabase` 모드에서는 **클라이언트와 같은 Supabase 프로젝트**의 URL 및 publishable key를 입력한다. 임시 `test-token` 모드에서는 `SKIN_AUTH_MODE=test-token`과 서버 전용 `SKIN_TEST_BEARER_TOKEN`이 필요하다. `service_role`이나 JWT signing secret은 사용하지 않는다.
3. 서버 환경 설치 후 실행한다.

```powershell
uv sync --project ml --locked --no-dev --group inference-server
.\scripts\start-skin-server.ps1 -HostAddress 127.0.0.1 -Port 8000
```

서버 전용 설정은 `SKIN_AUTH_MODE`, `SKIN_TEST_BEARER_TOKEN`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, 선택적 `SKIN_GPU_UUID`, `SKIN_MODEL_BUNDLE`, `SKIN_FACE_MODEL`, `SKIN_MAX_UPLOAD_BYTES`다. 런처는 허용한 이름만 로컬 설정 파일에서 읽으며 현재 프로세스의 명시적 설정을 우선한다. 비밀정보 값은 출력하지 않는다. 이전 `SKIN_API_TOKEN` 공유 키는 새 GPU API에서 사용하지 않는다.

기본 bind는 loopback이다. 현재 Tunnel은 데스크톱의 이 loopback 서버를 가리킨다. 이미 실행 중인 서버·Tunnel은 이 클라이언트 연결 작업에서 재시작하지 않는다. Uvicorn은 worker 하나, reload 비활성으로 실행하며 forwarded 헤더를 신뢰하지 않는다.

### 시작과 GPU 수명

시작 시 GPU UUID·이름·메모리를 확인하고 기존 bundle manifest/경로/네 체크포인트 SHA-256을 검증한다. 모델 네 개를 CUDA에 한 번 로드하고 eval·warmup 후 요청을 받는다. CUDA·설정·가중치가 잘못되면 시작에 실패하며 CPU로 대체하지 않는다. 요청마다 모델을 다시 읽지 않는다.

YuNet 얼굴 검출기는 별도 준비 명령에서 공식 OpenCV 파일을 다운로드하고 고정 SHA-256을 확인한다. API 시작/요청에서는 다운로드하지 않는다. 검출기는 CPU에서 한 번 만들어 재사용하며 네 피부 모델은 CUDA에서 실행한다. 라이선스는 `server/nia/YUNET-LICENSE.txt`에 있다.

## API와 인증

- `GET /health`: 인증된 준비 상태. `ready`, `cuda:0`, GPU 이름, `models_loaded=4`.
- `POST /analyze`: 클라이언트는 raw JPEG bytes와 `Content-Type: image/jpeg`를 전송한다. 기존 multipart의 `file` 필드 JPEG/PNG와 raw PNG도 유지한다.
- 두 경로 모두 Bearer 인증이 필요하다. 기본 모드는 Supabase 사용자 access token이며 로그인하지 않은 사용자는 촬영 전에 기존 로그인 화면으로 안내한다. 서버의 명시적 `test-token` 모드는 서버 로컬 시험 토큰만 받으며, 앱은 위의 개발 모드에서 사용자가 입력한 토큰을 보낸다.
- 인증은 본문 읽기 전에 수행한다. RS256/ES256은 캐시된 프로젝트 JWKS로 서명, exp, iss, aud, sub를 검증한다. HS256은 해당 Supabase 프로젝트의 Auth `/user`에 검증을 요청하고 프로젝트/만료/역할을 추가 확인한다. 사용자 role만 허용하며 익명·service_role은 거절한다. JWKS/Auth 장애는 인증 성공으로 취급하지 않는다.
- Supabase에는 토큰 검증 요청만 보내며 사진·ROI는 보내지 않는다.

성공 응답은 기존 `skin-recommendation-features-v1`와 10개 feature 및 `feature_status`, provenance, acne 점수·threshold, 연구용 검증 상태를 유지한다. 선택적 `execution`에 다음 실제 측정값만 추가한다.

```json
{"runtime":"pytorch-cuda","bundleVersion":"<manifest SHA-256>","serverMs":650.0}
```

`serverMs`는 인코딩 이미지 검증부터 얼굴 검출·ROI·전처리·추론·후처리까지다. 네트워크나 인증 시간을 순수 추론 시간으로 표시하지 않는다. 오류는 기존 `{error, code}` JSON이다.

| HTTP | 코드 예시 | 처리 |
|---|---|---|
|401|UNAUTHORIZED|로그인 토큰 누락·만료·위조·다른 프로젝트 등. 이미지를 처리하지 않음|
|503|AUTH_UNAVAILABLE|인증 서비스/키 확인 장애. 이미지를 처리하지 않음|
|503|SERVER_BUSY|다른 분석 진행 중. Retry-After: 1, 이미지 queue 없음|
|413|IMAGE_TOO_LARGE|전체 요청 12MiB 상한. Content-Length 없는 요청도 검사|
|415|UNSUPPORTED_IMAGE|JPEG/PNG 이외 형식|
|422|INVALID_IMAGE / FACE_NOT_FOUND / MULTIPLE_FACES / FACE_OUT_OF_BOUNDS|사진 재촬영 필요|
|500|INFERENCE_FAILED|내부 경로를 노출하지 않는 오류|

클라이언트 자동 재업로드는 하지 않는다. 요청 제한 시간은 30초다. 취소·화면 이탈·앱 비활성화는 업로드를 중단하며 늦은 응답은 폐기한다.

## 촬영 전달과 저장 호환성

기존 WebView 촬영·CaptureGate·가이드와 화면 흐름은 유지한다. 서버 모드는 촬영 전용 `capture.mjs`로 실행하며 ONNX, OpenCV 피부 전처리, 모바일 모델 manifest를 요구하지 않는다. JPEG는 10MiB 이하, base64 청크는 48KiB 이하로 제한하고 촬영 식별자·순서·개수·바이트 길이를 검증한다. 원본 bytes는 React state, AsyncStorage, 로그 또는 파일에 넣지 않는다.

서버는 YuNet 얼굴 박스 이후 기존 NIA ROI 비율·정사각 crop/JPEG/256px/ImageNet 정규화, 여드름의 기존 전처리, softmax/argmax 및 sigmoid/threshold를 재사용한다. ROI 방법은 `opencv_yunet_facebox_proportions_v1`로 명시한다. 자동 얼굴 검출 실패를 수동 고정 박스로 숨기지 않는다.

앱 어댑터는 완전한 10개 feature, 정수 범위, 각 feature의 predicted 상태, 여드름 점수와 threshold의 일관성을 확인한 뒤 `skin-analysis-server-v1`로 저장한다. 부분/잘못된 결과는 설문·저장 단계로 진행하지 않는다. 기존 `skin-analysis-mobile-v1` 및 저장 프로필 v1은 계속 읽는다. 서버 왕복/처리 시간은 별도 기록하고 모르는 모델별 시간은 생성하지 않는다. 사진·ROI·토큰은 저장 기록에 포함하지 않는다.

## 별도 기기 내 실험

`EXPO_PUBLIC_SKIN_ANALYSIS_MODE=on-device`를 명시하고 기존 `npm run skin:prepare` 및 모바일 실험 문서의 준비 절차를 따른다. Android 네이티브/Expo Go WASM 경로와 기존 결과는 유지한다. 서버 분석이 실패해도 기기 추론으로 자동 전환하지 않는다. skin-benchmark EAS 프로필은 on-device를 명시한다.

## 검사 및 실제 기기 인수 시험

```powershell
npm run check
npm run skin:test-client
uv run --project ml --group inference-server python -m pytest server/nia/tests ml/tests/test_model_pipeline.py
uv run --project ml --group inference-server ruff check server/nia/api.py server/nia/auth.py server/nia/face_detection.py server/nia/tests/test_api.py server/nia/tests/test_auth.py
```

자동 검사는 실서명 JWT·업로드 인증 선행·용량/메모리·동시 요청, 사진 청크 검증, 취소/시간초과, 서버 결과·기존 기록 호환성, 모델 없는 카메라 실행을 포함한다.

실제 기기에서는 Supabase 기본 모드 또는 위에 명시한 임시 토큰 모드의 Expo Go로 촬영→업로드→10개 결과→설문→저장을 확인한다. ASGI 앱 검증, 별도 HTTP 요청, 실제 스마트폰 인수 시험은 구분해서 기록한다. 실제 기기가 준비되지 않은 검사를 성공으로 보고하지 않는다.

참고: [Expo SDK 57](https://docs.expo.dev/versions/v57.0.0/), [Expo fetch](https://docs.expo.dev/versions/v57.0.0/sdk/expo/), [Supabase JWT](https://supabase.com/docs/guides/auth/jwts), [OpenCV YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet).


## 2026-10-25 초기 LAN/Supabase 구현 검증 기록

- 최신 develop을 기준으로 기기 분석 선행 작업을 통합한 `feat/server-skin-analysis`에서 구현했다.
- 앱 전체 타입검사·lint·Jest 60개, 서버/JWT/ML pytest 93개(추가 subtest 9개), 모델 없는 클라이언트 검사 2개 통과.
- Android JS export 성공. export 자산에 피부 체크포인트/ONNX 파일 또는 이전 서버 비밀키 값이 없는 것을 확인했다.
- 원본 스마트폰 JPEG를 승인된 LAN 주소의 실제 TCP API에 두 번 전송했다. 두 요청 모두 HTTP 200, complete 및 10개 feature가 반환되었고 결과가 일치했다.
- 요청 왕복은 약 652ms와 503ms였다. 모델 로딩은 시작 시 4회에서 증가하지 않았고, 실제 forward 20회에서 모델과 입력/출력이 모두 CUDA인 것을 확인했다.
- 이 TCP 검증의 인증은 RAM에서 생성한 시험 RS256 JWT와 시험 공개 키를 사용했다. JWT 서명/만료/issuer/audience 검증 코드는 실제로 실행했지만, 실제 Supabase 계정 로그인이나 원격 JWKS 서비스 연결을 대신했다고 주장하지 않는다.
- 실제 Supabase 로컬 설정 및 로그인한 Expo Go의 촬영→업로드→설문·저장은 사용자가 직접 설정 후 인수 시험한다. 비밀번호·실 access token은 저장소/보고서에 남기지 않는다.
- 테스트용 GPU 서버는 검증 후 종료했다. 실제 운영 시작은 위 런처와 로컬 설정으로 수행한다. 개인 사진별 결과 및 빌드 결과물은 Git에서 제외된 ml/runs 아래에만 둔다.

## 2026-10-25 Tunnel / Expo Go 시험 인증 연결 검증

기존 서버 지원 커밋 `4fd7965` 위에서 앱 연결을 이어 구현했다. 서버 인증·모델·전처리와 Tunnel 설정은 변경하지 않았다.

- 지정된 Tunnel의 인증된 `/health`: HTTP 200, `ready`, `cuda:0`, `NVIDIA GeForce RTX 4070 Ti SUPER`, `models_loaded=4`.
- 로컬에 이미 설치된 라이브러리의 예제 인물 JPEG를 메모리에서 직접 업로드: HTTP 200, `complete`, feature 10개, `pytorch-cuda`. 왕복 약 1,679ms와 서버 응답 `serverMs` 약 911.12ms를 구분했다. 이 입력은 스마트폰에서 새로 촬영한 사진이 아니다. 원본과 개인별 결과값은 새 파일·로그·보고서에 남기지 않았다.
- 토큰 누락·틀린 토큰으로 `/health` 요청: 각각 HTTP 401, `UNAUTHORIZED`. 정상 토큰은 서버 로컬 설정에서 메모리로만 읽고 출력하지 않았다.
- Metro의 LAN manifest와 촬영 스크립트 HTTP 200. Android 개발 JavaScript 번들 HTTP 200. 메모리에서 번들을 검사해 정확한 승인 origin·시험 모드 설정이 포함되고 실제 서버 토큰·서버 비밀 환경변수 이름은 포함되지 않음을 확인했다. Android SDK·Gradle·네이티브 빌드는 사용하지 않았다.
- `npm run check -- -- --runInBand --cacheDirectory .expo/jest-cache`: 타입 검사·lint·Jest 9개 suite / 70개 test 통과. 훅의 촬영 청크 → 실제 업로드 어댑터(HTTP 응답 모킹) → 설문 → 저장, 10개 feature·시간 분리·토큰 미저장, 취소·늦은 응답·잘못된 인증/주소 검사를 포함한다.
- `npm run skin:test-client`: 피부 모델 없이 카메라 자산을 제공하는 HTTP 검사 등 2개 통과. 제한 환경의 loopback `EACCES` 후 네트워크 허용 환경에서 재실행했다. 최초 Jest 임시 캐시 `EPERM`은 Git 제외된 `.expo/jest-cache` 사용으로 해결했다.
- 실기기 접속 시 Expo Go SDK 58 / 프로젝트 SDK 57 불일치가 Metro 로그에 보고되었다. SDK 57용 Expo Go 설치 안내 후 촬영→서버 결과→설문·저장의 실기기 결과를 기다리는 상태이며, 위 코드/HTTP 검사를 실기기 성공으로 기록하지 않는다.
