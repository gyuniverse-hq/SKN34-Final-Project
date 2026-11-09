# LaPa 모델 비교 실행 안내

현재 RunPod의 BiSeNet 작업이 끝난 뒤 진행한다. 공개 LaPa 연구용 데이터만 이 절차에 사용한다. 이 절차는 앱의 사용자 얼굴 전송이나 모델 탑재를 뜻하지 않는다. LaPa 및 각 모델의 비상업·가중치 사용 조건은 별도 확인한다.

## 먼저 결과 보존

JupyterLab에서 `/workspace/ar-smoke20/results/`의 각 모델 폴더에 있는 `metrics.csv`, `summary.json`을 PC에 내려받는다. 현재 Pod에 `/workspace` 볼륨이 없으면 중지 시 컨테이너 파일은 사라질 수 있다.

## MediaPipe: 기존 20장

PC의 `research/data/ar_model_compare/runpod-transfer/comparison-tools.zip`을 RunPod `/workspace`에 업로드하고 업로드가 끝난 뒤 실행한다. 파일은 기존 `ar-smoke20`과 다른 경로에 푼다.

```bash
python -m zipfile -e /workspace/comparison-tools.zip /workspace/ar-next
apt-get update
apt-get install -y libegl1 libgles2
python -m venv --system-site-packages /workspace/ar-next/venv
/workspace/ar-next/venv/bin/python -m pip install 'mediapipe==1.2.0'
/workspace/ar-next/venv/bin/python /workspace/ar-next/tools/landmark_lapa.py --dataset /workspace/ar-smoke20/lapa/test --output /workspace/ar-next/results/mediapipe-20 --landmarker /workspace/ar-next/tools/face_landmarker.task --rings /workspace/ar-next/tools/app_lip_rings.json --mode mediapipe --limit 20
```

MediaPipe 패키지 설치는 새 venv에만 적용한다. 현 Pod Python 3.12에서의 설치 및 GPU 환경은 미검증이다. 실행 오류가 나면 출력 전체를 보관한다. 이 결과는 앱의 20점 입술 윤곽을 사용한 **정지 이미지 근사치**이며 실제 셰이더, 실시간 비디오, Expo Go 전체 성능은 측정하지 않는다. 실패한 얼굴은 빈 예측으로 기록한다. 20장은 파일명순으로 앞 20장이며 대표 표본이 아니다.

## LaPa 2,000장 전송

`research/data/ar_model_compare/runpod-transfer/`의 `manifest.json`과 `lapa-test-01.zip`부터 `lapa-test-10.zip`까지 11개 파일을 RunPod `/workspace/lapa-transfer/`에 한 번에 하나씩 업로드한다. 각 업로드가 끝나고 다음 파일을 시작한다. 얼굴 데이터는 공개 저장소에 올리지 않는다.

```bash
python /workspace/ar-next/tools/verify_runpod.py --transfer /workspace/lapa-transfer --destination /workspace/ar-full
```

각 ZIP의 크기와 SHA-256, 압축 무결성을 확인한 뒤 푼다. 오류가 나오면 해당 파일만 다시 업로드하고 검증 명령을 다시 실행한다. 완료 후 입력 경로는 `/workspace/ar-full/lapa/test`다. 기존 모델 스크립트들의 `--dataset`에 이 경로를, `--output`에 서로 다른 새 폴더를 지정한다. `--limit 20`을 빼면 전체를 처리한다. 모든 모델에 동일한 분할과 사진을 사용하고, 사진별 ID와 실패 건수를 함께 비교한다. 수치는 중간에 파일을 덮지 않도록 실험마다 새 결과 경로에 저장한다.

## SAM 2.1 대형 모델

SAM 2 모델의 공식 저장소와 체크포인트: https://github.com/facebookresearch/sam2 . 아래는 비교 도구의 준비 절차이며 현 RunPod에서는 아직 실행 검증하지 않았다. 새 venv를 만들었으므로 시스템 PyTorch를 직접 교체하지 않는다. `--no-deps` 설치 후 누락된 패키지가 있으면 환경을 확인한다.

```bash
git clone https://github.com/facebookresearch/sam2.git /workspace/ar-next/sam2
/workspace/ar-next/venv/bin/python -m pip install setuptools wheel
SAM2_BUILD_CUDA=0 /workspace/ar-next/venv/bin/python -m pip install --no-build-isolation --no-deps -e /workspace/ar-next/sam2
/workspace/ar-next/venv/bin/python -m pip install hydra-core iopath tqdm
mkdir -p /workspace/ar-next/checkpoints
curl -L -o /workspace/ar-next/checkpoints/sam2.1_hiera_large.pt https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt
/workspace/ar-next/venv/bin/python /workspace/ar-next/tools/landmark_lapa.py --dataset /workspace/ar-smoke20/lapa/test --output /workspace/ar-next/results/sam2-10 --landmarker /workspace/ar-next/tools/face_landmarker.task --rings /workspace/ar-next/tools/app_lip_rings.json --mode sam2 --sam-checkpoint /workspace/ar-next/checkpoints/sam2.1_hiera_large.pt --limit 10
```

힌트는 정답이 아니라 MediaPipe 예측의 입술 점과 상자에서 생성한다. SAM 자체 점수 최대 마스크를 선택하며, SAM이 윗입술과 아랫입술을 하나의 물체로 인식하지 않을 수 있다. MediaPipe 실패와 힌트 생성 실패는 빈 마스크로 기록한다. 실제 품질과 속도는 확인 전이다. 해당 결과는 랜드마크+SAM 결합 방식이다.

## iPhone 13: 현재 앱 기준선

1. PC와 iPhone을 같은 Wi-Fi에 연결하고, iPhone에 Expo Go를 준비한다. Expo CLI와 Expo Go가 같은 Expo 계정에 로그인되어 있어야 한다.
2. PC 저장소 루트에서 `npx expo start`를 실행하고 iPhone 카메라로 QR을 연다. Expo CLI가 개발 빌드를 선택하면 Expo Go 모드로 전환한다. Expo Go 버전과 SDK 호환성을 확인한다.
3. 현재 AR 화면에서 입술을 선택하고 정면·입 벌림·고개 좌우·가림·밝은 곳과 어두운 곳을 같은 조건으로 확인한다. 진입·얼굴 감지 실패, 윤곽 넘침, 추적 떨림과 기기 발열을 기록한다. HUD가 보이는 경우 표시된 FPS는 표시 방식과 측정 시간도 기록한다.
4. 비교 대상 모델은 아직 앱에 통합되지 않았다. RunPod 결과만으로 iPhone의 해당 모델 FPS나 실제 립 렌더 성능을 말할 수 없다. 모델별 기기 실행 경로와 Expo Go 지원 여부를 별도로 구현·검증한 뒤 같은 조건에서 반복한다.

참고: https://docs.expo.dev/get-started/start-developing/ . 연결이 안 될 때 앱·폰 화면의 오류를 기록하고 계정 정보·토큰은 공유하지 않는다.
