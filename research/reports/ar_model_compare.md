# AR 입술 영역과 렌더러 비교 — 2026-11-08 부분 실험

**AR_SPEC 1-4(얼굴 영상 기기 밖 전송 금지) 예외 실험, 앱에는 반영하지 않음.** 얼굴 이미지는 로컬 `research/data/`에만 보관했고 외부로 보내지 않았다.

## 요약

- 정답 마스크가 없어 입술 영역 모델의 우열과 기존 앱 방식을 검증할 수 없다. 앱의 현재 방식을 유지하며 LaPa 동일 입력 재측정이 필요하다.
- 공개 사진 5장 × 셰이드 5개로 현 렌더러와 스티커 대조군을 비교했다. 실제로 바른 사진이 없으므로 실물 기준 현실감 점수는 **데이터 없음**이다.
- CPU 스모크 추론 중앙값은 MediaPipe 10.195ms, BiSeNet 124.503ms다. 서로 다른 입력 전처리·출력, 5장·콜드 스타트 포함 환경이라 성능 판정 근거가 아니다. 이후 BiSeNet 파일 해시·전처리·클래스를 확인했다.
- CUDA가 샌드박스 안팎에서 비활성이고 LaPa와 팀 데이터가 없어 핵심 비교 및 GPU 서버 측정은 미완료다.
- 다음 단계는 데이터·가중치 출처를 확보하고 A를 완성한 뒤 B의 실제 바른 사진 및 사람 평가를 진행하는 것이다.

## 실험 조건과 입력

고정 목록 `research/data/ar_model_compare/set/manifest.csv`는 5장, SHA-256 `7bdf9fa41265575890249594f85558a2cc732519be42c703b05f1814e9b50e86`이다. 동일 명령 2회 해시가 같다. 이 해시는 manifest 내용에 대한 것이며 이미지 바이트 해시가 아니다. 전부 `cc_faces`로 기록했고 정답·각도·피부톤·입 상태는 미확인으로 남겼다. 맨입술 여부도 촬영 메타데이터로 검증되지 않았다. LaPa, 팀 사진·영상 및 실제 발색 사진은 지정 경로에 없다. 조건별·피부톤별 분포와 실제 720×960 프레임의 얼굴 크기 분포는 **미측정**이다. 출처 정보와 라이선스의 완전성은 재검토해야 한다.

## A — 입술 영역 인식과 속도

| 방식 | 관찰된 CPU 시간 중앙값 | 모델 파일 크기 | 정답 기반 IoU·경계 오차 |
|---|---:|---:|---|
| MediaPipe Face Landmarker, 이미지 모드 | 10.195ms | 3.58 MiB | 데이터 없음 |
| BiSeNet R18 ONNX, 512×512, 전처리 가정 | 124.503ms | 50.74 MiB | 데이터 없음 |
| 앱 렌더 변화량 >24 | 미측정 | 해당 없음 | 데이터 없음 |
| 로컬 GPU / localhost 왕복 | CUDA 사용 불가 | — | 미실행 |

출처: `research/data/ar_model_compare/a/smoke/metrics.csv` 및 `research/ar_model_compare/results/a_summary.json`. MediaPipe는 5/5 얼굴 검출이다. 시간에는 첫 호출이 포함되고, 추론 전후 전처리 및 전송은 제외된다. 기기 안 모바일 FPS나 서버 비용과 직접 비교할 수 없다. 앱 렌더 변화 마스크는 서로 다른 프레임 간 화면 변화까지 포함할 수 있고, 분할 모델의 예측 영역과 같은 의미가 아니다. BiSeNet은 정답 부재로 정확도 또는 성공률을 내지 않았다. 이전 실행 기록의 '출처·전처리 미확인'은 다음 후속 조사로 정정한다.

MediaPipe는 사진에서 얼굴 랜드마크를 예측하고, 앱 코드의 `LIPS_OUTER`·`LIPS_INNER`로 다각형을 만든다. 머리 회전과 가림, 입술 경계의 개인차에서 한계가 있다. BiSeNet은 픽셀 단위 의미 분할 후보다. [SegFormer face-parsing 모델 카드](https://huggingface.co/jonathandinu/face-parsing)는 비상업 연구·교육 사용을 명시하며 더 무거운 후보로 조사했으나 다운로드·실행하지 않았다. FaRL·SAM 2는 미실행이다.

동일 이미지 기반 조건별 IoU·Dice·spill·miss·경계 오차, 부트스트랩 CI, 눈 영역, yaw/어두움/피부톤별 그리드, 속도·정확도 개선량과 선택 근거는 **미실행**이다. `metrics_a.py`의 계산 함수만 합성 마스크로 검사했다. 기존 10-25 기록의 LaPa 200장 IoU는 현재 결과가 아니며 재현용 원본이 이 환경에 없으므로 새 모델 비교의 수치로 사용하지 않는다. 당시 다문 입도 약 0.75였다는 기록은 주석 경계의 한계를 시사하지만 엄밀한 이론적 상한으로 보지 않는다. 영상 정지·회전·가림 평가는 **데이터 없음**이다. `docs/AR_PROGRESS.md`에는 이전 실기기 HUD 약 23~24fps 기록이 있으나 본 실험·현재 기기 측정은 아니다.

## B — 렌더러 표현 (실물 발색과 별도)

얼굴 5 × 5셰이드 = 25쌍. 기존 페이지를 헤드리스 Chrome에서 렌더했고, 원본·스티커·현재·detail·wide·anisotropic은 동일 사진과 셰이드를 사용한다. 제품 hex는 그대로고 강도는 0.6이다. 캡처 간 랜드마크가 미세하게 움직일 수 있어 완전한 동일 프레임은 아니다. 사진에 원래 립 제품이 있는지도 확인되지 않았다.

| 지표, 25쌍 중앙값 | 맨입술로 가정한 입력 | 스티커 | 현재 |
|---|---:|---:|---:|
| L* 명암 폭 | 29.67 | 0.00 | 22.02 |
| 같은 밝기 비율 | 0.333 | 1.000 | 0.372 |
| 고주파 결 표준편차 | 1.943 | 0.044 | 1.592 |
| 맨입술 결 상관 | 1.000 | 0.100 | 0.919 |

출처: `research/data/ar_model_compare/b/current/metrics.csv`, 집계 `research/ar_model_compare/results/b_summary.json`. 위 표는 색상과 제형을 함께 묶은 기술 통계이며 자연스러움 점수나 통계적 우열이 아니다. 0=스티커, 1=입력 사진에 일치하도록 지표별 거리를 계산한 참고 위치의 중앙값은 L* 명암 폭 **0.762**, 결 **0.886**이다. 입력 사진이 실제 립스틱 정답이 아니므로 이 숫자를 ‘실물에 가까움’으로 해석할 수 없다. 분모가 0인 지표는 계산하지 않으며 범위 밖은 0~1로 제한했다. 후보별 통계는 JSON에 있다. `edge_w_pct`, 후보별 `gl_corr`, real 대비 ΔE2000·SSIM과 실물 발색 정확도는 **미측정**이다.

마스크에 정답이 없어 동일 기준을 만들려고 MediaPipe 입술 다각형과 렌더 변화량의 교집합을 3% 침식했다. 따라서 실험 B의 측정 영역도 실제 입술 GT와 렌더 영역에 의존한다. 변화 기준·조명·렌더별 떨림이 결과에 영향을 준다. 정성 시트는 `research/data/ar_model_compare/b/current/sheet_<face>.png`이며 얼굴 픽셀이 있어 Git에 포함하지 않는다. 오프라인 블라인드 도구는 `research/ar_model_compare/rating/index.html`, 사람 평가는 **대기**다. 사용 방법은 `research/ar_model_compare/README.md`를 따른다.

## 한계와 남은 작업

- LaPa test를 준비하고 GT 경계 노이즈, 사람 단위 샘플링, yaw 추정과 톤 구간을 검증해야 한다. 합성 어둠은 실제 저조도 센서 조건의 대체가 아니다. 현재 build_set은 LaPa·어두움·팀 데이터 처리를 구현하지 않았다.
- 검증 가능한 모델 라이선스·가중치 출처·전처리·클래스 맵을 확보한 다음 BiSeNet, SegFormer, heavy/hybrid, 앱 렌더를 같은 입력에서 평가해야 한다. 현재 A 도구는 스모크 수준이며 눈 영역·조건별 정량·그리드·CI 집계가 없다.
- GPU 장치와 CUDA 실행 환경을 복구해야 localhost GPU 왕복을 잴 수 있다. 모바일 네트워크 지연은 별도 실측이 필요하며 이 실험에서 추측하지 않는다.
- 팀원 동의 사진·영상과 제품 정보 및 사람 블라인드 평가가 필요하다. 시트는 오프라인 소프트웨어 렌더라 실제 Expo Go 화면·프레임 속도와 다를 수 있다.
- 앱 코드는 변경하지 않았다. 앱 검사 `npm.cmd run check` 통과(타입·lint·Jest 929개), 연구용 합성 지표 테스트 3개 통과, 평가 페이지 로컬 열기·CSV 다운로드 확인.

## 11-08 후속: 후보·라이선스 및 입 주변 크롭

| 후보 | 출처·버전·조건 | 실행 상태 |
|---|---|---|
| SegFormer | [jonathandinu/face-parsing](https://huggingface.co/jonathandinu/face-parsing), MiT-B5, CelebAMask-HQ 미세조정, 모델 카드 비상업 연구·교육용 | CUDA 및 라이브러리·가중치 부재로 미실행 |
| FaRL LaPa | [facer `farl/lapa/448`](https://github.com/FacePerceiver/facer/blob/main/facer/face_parsing/farl.py), 448px, 공개 코드 MIT. [LaPa 라이선스](https://github.com/jd-opensource/lapa-dataset)는 비상업적 사용으로 제한 | 미실행. LaPa train과 test가 **학습 데이터 동일 출처**이므로 test 결과는 반드시 표시하고, 독립된 cc_faces·team에서도 별도 비교해야 한다. 현재 비-LaPa 사진에도 정답은 없다 |
| FaRL CelebM | [facer `farl/celebm/448`](https://github.com/FacePerceiver/facer/blob/main/facer/face_parsing/farl.py), 448px, 코드 MIT. [CelebAMask-HQ](https://github.com/switchablenorms/CelebAMask-HQ#dataset-agreement)는 비상업 연구 목적 | 미실행 |
| SAM 2 | [공식 SAM 2](https://github.com/facebookresearch/sam2#license), 모델 체크포인트와 코드 Apache-2.0(선택적인 제3자 구성요소 별도 조건) | 미실행. 랜드마크 기반 양·음성 프롬프트 생성만 구현·합성 테스트; 이미지 추론 및 영상 마스크 전파는 미구현 |

FaRL의 MIT **코드** 라이선스를 가중치 사용 허가와 동일시하지 않는다. 각 체크포인트 자체의 명시적 사용 조건과 재배포 권리는 추가 확인 전까지 미확인으로 두고 가중치를 받지 않았다. FaRL 사전학습 데이터와 관련 학습 데이터 조건은 [공식 논문의 데이터 사용 설명](https://openaccess.thecvf.com/content/CVPR2022/supplemental/Zheng_General_Facial_Representation_CVPR_2022_supplemental.pdf)도 확인해야 한다. 새 후보 모델 가중치는 내려받지 않았다.

기존 BiSeNet은 로컬 SHA-256 `0d9bd318e46987c3bdbfacae9e2c0f461cae1c6ac6ea6d43bbe541a91727e33f`가 [공개 ONNX](https://huggingface.co/PayamFard123/dermaintel-face-parsing)의 2026-11-08 응답 `X-Linked-ETag`와 같았다. 리비전 `c1c5fd399cc72b45e3613019879fc6c17a7d8f6a`, 512px·19클래스·입술 12/13이다. 제공 모델 카드는 MIT를 표기하나 학습 데이터는 CelebAMask-HQ이므로 그 데이터 사용 조건을 별도 고려한다. RGB/ImageNet 평균·표준편차는 [원 저자의 ONNX 추론 코드](https://github.com/yakhyo/face-parsing/blob/main/onnx_inference.py)와 일치한다.

후속 `hybrid_crop.py`는 위·아래 입술 점으로 입 주변을 입 너비 1.6배 정사각형으로 자른다. 128·192·256px로 샘플링한 뒤 **512px 고정 ONNX 입력으로 다시 확대**하고 예측을 원래 좌표로 복원한다. 따라서 샘플 해상도와 실제 네트워크 해상도는 다르다. 단일 스레드 CPU와 데스크톱 Chrome의 ONNX Runtime Web WASM 단일 스레드 추론 시간은 `research/ar_model_compare/results/hybrid_summary.json` 및 `research/data/ar_model_compare/a/hybrid_{cpu,wasm}/metrics.csv`에 있다. 각 크기 5장, 워밍업 이후 모델 추론만 측정했고 얼굴 추적·전처리·복원·전송은 빠진다. **실제 폰 WebView에서는 미측정**이며, 정답 데이터가 없어 3개 크기의 IoU·경계 오차와 우열은 미측정이다. 얼굴 전체로 학습한 모델이 입 주변만 입력받는 경우의 분포 차이도 검증해야 한다. 현 크롭 구현은 BiSeNet 전용이며 다른 모델의 크롭과 GPU 추론은 미구현이다.

| 크롭 표본화 | 네트워크 입력 | CPU 추론 중앙값 | 데스크톱 WASM 추론 중앙값 | IoU / 경계 오차 |
|---|---|---:|---:|---|
| 128px | 512px | 301.8ms | 1057.9ms | 데이터 없음 |
| 192px | 512px | 302.3ms | 1034.0ms | 데이터 없음 |
| 256px | 512px | 304.7ms | 1051.1ms | 데이터 없음 |

Chrome 156.0.8078.74, ONNX Runtime Web 1.30.0, n=5. 위 WASM 값은 기기에서 선택해 쓰기 위한 근거를 마련하는 데스크톱 탐색값이며 앱의 폰 FPS 또는 GPU 추론 시간이 아니다.
