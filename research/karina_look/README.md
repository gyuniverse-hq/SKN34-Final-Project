# 카리나 멧갈라 룩: 영상 예비 확인

대상: `https://www.youtube.com/watch?v=n5otfjJSSQc`. 사용자가 현재 영상에서 가능한 부위부터 부분 분석하기로 선택했다. 립과 블러셔의 **탐색용 현재 AR 비교**를 만들었으며, 프로필 적용·개선 검증은 하지 않았다.

## 데이터와 재현 조건

- 영상 파일은 다운로드하지 않는다. Playwright에서 YouTube를 재생하고 `video` 요소의 화면만 캡처했다. 봇 확인·로그인·동의 화면이 뜨면 우회하지 않는다.
- 받은 Gemini 결과는 `research/data/karina_look/gemini_segments.json`, 예비 프레임과 후보 측정치는 `research/data/karina_look/overview/`에만 둔다. 이 경로는 Git 제외이며 프레임은 문서에 첨부하지 않는다.
- Python은 `research/ar_evaluation/.venv/Scripts/python.exe`, 랜드마커는 `research/data/models/face_landmarker.task`, MediaPipe 웹 파일은 `research/data/mediapipe-web/`을 사용했다. YouTube 재생은 Chrome과 네트워크가 필요하지만, AR 렌더링 중 허용된 로컬 자료 외의 요청은 차단한다.
- `docs/AR_SPEC.md` 1-13의 평가용 얼굴 사진 제한과 공개 영상 인물 사용 요청은 충돌한다. 이번 영상의 예비 확인은 사용자 요청에 따른 예외로 보고했다.

## 직접 확인한 사항

| 대략적 시각 | 영상에서 확인한 것 | 해석상 주의 |
|---|---|---|
| 9.25초 | 네이밍 올데이 마스터 쿠션 23N 자막, 얼굴 정면 | 손과 컴팩트가 턱을 가리고 입이 벌어져 있다. 완전히 맨얼굴인지 불명 |
| 9.75초 | 쿠션을 얼굴에 대고 바르기 시작 | Gemini가 제시한 9~18초 전체를 베이스 전 구간으로 볼 수 없다 |
| 20초 | 키스미 헤비로테이션 내추럴 파우더 아이브로우 애쉬브라운 자막 | 앱의 제품명과 일치. Gemini의 `에어브라운`과 다르며 호수는 이 화면에서 확인하지 못했다 |
| 50초 | 데이지크 브이컷 블렌딩 쉐딩 쿨 블렌딩 자막 | 앱의 제품명과 일치. Gemini의 `바이올렛 블렌딩 섀딩`과 다르다 |
| 183.78초 | 에이오유 매트바 슴슴바 자막과 제품 | 앱의 립 슬롯과 제품명 일치. Gemini가 제시한 302초는 영상 길이 밖 |
| 181.75~183초 | 퍼프로 입 주변을 누름 | 161초 립 입력과 매트바 도포 사이에 쿠션이 끼어들므로 매트바만의 전후 비교가 아니다 |
| 191.5초 | 립 브러시가 턱 아래에 있고 제품 도포 진행 중 | 입이 벌어져 있고 마무리 전이라, 161초 입력과 모양 및 상태가 다르다 |
| 203.97초 | 3CE 샤인 리플렉터 오팔샤워를 입술에 바름 | 매트바 뒤에 다른 립 제품을 겹친다 |
| 213.94초 | 어뮤즈 젤핏 글로스 로즈 크림 펄 글로스 제품 자막 | 최종 립은 매트바 단독 결과로 해석할 수 없다 |
| 224.11초 | 클리오 에센셜 블러쉬 탭 쉬폰 핑크를 볼에 바름 | 앱 블러셔 슬롯 외에 추가 블러셔가 보인다 |

영상 길이는 브라우저 기준 약 270.141초다. 제공된 Gemini 결과는 하이라이터·립 등을 302~409초에 배치하여, 관련 제품과 시각은 영상에서 검증하기 전에는 근거로 사용할 수 없다. JSON 뒤의 코드 펜스와 인용 표기는 제외하고 JSON 객체만 연구 데이터 경로에 저장했다.

MediaPipe 예비 측정에서 9.25초 후보의 얼굴 너비는 화면의 약 23.2%(약 231px), 254초 후보는 약 46.2%(약 460px)였다. 전자는 손 가림과 벌어진 입, 후자는 눈을 내린 자세가 있다. 선명도·광택·결의 차이는 화장뿐 아니라 촬영 배율과 자세의 영향도 받으므로 이 두 장을 제품 발림의 독립 검증으로 취급하지 않는다.

## 부분 분석과 재현

1. 사전 조건: Git 제외 설정을 확인하고 Playwright, Chrome, 기존 Python 환경·MediaPipe 파일을 준비한다. 다른 파일은 수정하지 않는다. 다음 명령은 브라우저 재생 화면에서만 캡처하며 파일 다운로드 도구를 사용하지 않는다.

   ```powershell
   git check-ignore -v research/data/karina_look/blush_candidates/0000.png
   research/ar_evaluation/.venv/Scripts/python.exe research/karina_look/capture.py --start 29 --end 47 --step 0.5 --folder blush_candidates
   research/ar_evaluation/.venv/Scripts/python.exe research/karina_look/capture.py --start 160 --end 162 --step 0.25 --folder lip_input
   research/ar_evaluation/.venv/Scripts/python.exe research/karina_look/capture.py --start 190.5 --end 192.5 --step 0.25 --folder lip_target
   ```

2. 다음 명령은 실제 `useVideoTryOn`/`resolveDemoLookProducts()`와 번들을 통해 메이크업 상태를 추출하고, 실제 AR 페이지에 메시지로 주입한다. 별도 `research/vto_benchmark/compare_lips.py`가 있어야 립 지표 명령을 사용할 수 있다.

   ```powershell
   node node_modules/jest/bin/jest.js --runInBand --roots research/karina_look --runTestsByPath research/karina_look/extractMakeup.test.ts
   node research/ar_repro/build_page.mjs components/ar/faceTrackerHtml.ts components/ar/faceUV.ts research/data/karina_look/page.html
   research/ar_evaluation/.venv/Scripts/python.exe research/karina_look/render_zone.py --zone lip
   research/ar_evaluation/.venv/Scripts/python.exe research/karina_look/render_zone.py --zone blush
   research/ar_evaluation/.venv/Scripts/python.exe research/karina_look/analyze_lip.py
   research/ar_evaluation/.venv/Scripts/python.exe research/karina_look/analyze_blush.py
   research/ar_evaluation/.venv/Scripts/python.exe -B -m unittest discover -s research/karina_look -p 'test_*.py' -v
   ```

`lip_baseline/`에는 161초 입력의 립 끔·현재 AR과 191.5초 영상(도포 중)을 나란히 둔 이미지 및 기존 립 도구의 기술 지표가 있다. 현재 실행에서 립 명암 폭 L* p90-p10은 입력 17.08, AR 16.04, 도포 중 영상 15.11이고, 고역 표준편차는 각각 1.397, 1.634, 1.099다. 영상은 보정·정렬하지 않았고 입 모양과 선행 쿠션 처리가 다르므로 숫자는 제품의 정확도나 개선율이 아니다.

`blush_baseline/`은 35초 입력과 릴리바이레드 사용 후·다음 제품 전인 42초를 사용한다. 얼굴 랜드마크 삼각형으로 영상을 입력에 맞추고 얼굴 바깥 배경 대응점으로 선형 RGB 채널별 gain/offset을 맞췄다. 볼 마스크 6,714px의 탐색용 평균 ΔE2000은 6.07이다. 배경의 픽셀을 나눠 남겨 둔 보정 잔차 RMSE는 RGB 각각 약 0.052(선형값 0~1)이고 이웃 픽셀은 독립 표본이 아니다. 컷·노출·압축·와핑 및 큰 보정 잔차 때문에 이 값은 실측 오차나 프로필 채택 기준이 아니다. 지표와 마스크, 비교 이미지는 Git 제외 데이터 경로에만 저장한다.

입술은 사용자 영상과 AR이 이미 다른 상태에서 시작하고 블러셔도 다른 각도의 화장 전후 쌍이 없다. 독립 검증 없이 `video-fit` 값을 지어내거나 채택하지 않았다. 제품 색 hex·렌더러·앱 동작은 변경하지 않았다.

## 전체 룩 겹치기와 위치 후보

사용자 의도에 맞춰 9.25초 화장 전 후보에 앱의 카리나 룩 전체를 실제 훅과 메시지 경로로 적용하고, 250초의 거의 완성된 영상 얼굴을 랜드마크 삼각형으로 같은 위치에 옮겨 겹쳤다. `all_baseline/whole_look_exploration.png`의 순서는 전, 현재 앱, 정렬한 영상, 전·후 50% 겹침이다. 9.25초는 손과 제품이 턱을 가리고 250초는 고개가 돌아가고 얼굴 위쪽이 잘렸으며 그 뒤 약간의 터치업이 이어진다. 얼굴 밖 배경 대응으로 색 보정을 시도했으나 신뢰할 수 있는 보정을 얻지 못했으므로 이미지에는 보정이 없고 픽셀 차이를 화장 영역이라고 단정하지 않는다.

`all_baseline/face_landmarks_exploratory.json`의 좌표는 동영상 속 **얼굴 랜드마크**이며, 화장을 한 위치나 경계로 검증된 값이 아니다. 볼의 별도 35→42초 비교에서는 보정된 전후 a* 변화 후보의 가중 중심을 눈의 양끝 중심과 얼굴 너비로 정규화했다. `blush_baseline/blush_location_candidates.png`의 초록 십자는 앱, 자주색 십자는 영상의 후보이며, 상세 수치는 옆 JSON에 있다. 임의의 변화량 기준 1.5와 단일 정면 쌍을 쓰므로 얼굴·조명과 컷의 영향이 섞일 수 있다. 다른 각도나 실제 도포 경계에 대한 검증을 거치지 않은 후보이며 앱의 룩 좌표로 사용하지 않는다.

```powershell
research/ar_evaluation/.venv/Scripts/python.exe research/karina_look/capture.py --start 8 --end 10 --step 0.25 --folder whole_before
research/ar_evaluation/.venv/Scripts/python.exe research/karina_look/capture.py --start 250 --end 268 --step 0.5 --folder whole_after
research/ar_evaluation/.venv/Scripts/python.exe research/karina_look/render_zone.py --zone all
research/ar_evaluation/.venv/Scripts/python.exe -B research/karina_look/explore_full_look.py
research/ar_evaluation/.venv/Scripts/python.exe -B research/karina_look/locate_blush.py
```

위 명령은 앞 절의 메이크업 추출, 페이지 빌드 및 블러셔 분석 실행이 먼저 필요하다. 1080p 재생 화면을 캡처해 AR 페이지는 996×560 뷰포트에서 렌더했다. 다른 부위의 영상 도포 경계와 발림 특성은 아직 추출·검증하지 않았다.

## 다른 부위의 전후 후보와 블러셔 설정 시험

영상의 눈썹 18→35초, 쉐딩 48→67초, 섀도 67→95초, 아이라인 107→119초 후보를 실제 앱의 해당 부위 단독 렌더와 정렬해 각각의 `*_baseline/stage_comparison.png`에 저장했다. 눈썹은 여러 제품이 섞이고 배경 보정이 실패했다. 쉐딩은 턱에 브러시가 걸리고 턱과 코에 서로 다른 제품이 쓰였다. 섀도는 두 제품 이상이 쓰이고 시선이 다르며 배경 보정이 실패했다. 아이라인은 영상상 107초 전에 섀도 밑그림이 이미 있으며 119초에는 다른 제품이 눈 가까이에 있다. 눈썹·섀도·아이라인 시트는 랜드마크 주변의 넓은 눈 영역만 겹쳐 손이나 제품이 얼굴에 전사되는 현상을 줄였다. 이 영역은 화장 경계가 아니며 색 차이를 제품 발림량으로 간주할 수 없다.

블러셔는 고정된 제품 hex로 기존 위치 세 가지와 진하기(0.45·0.65·0.85), 기존 위치의 진하기(0.25~0.85), 앱 기본값까지 16개 설정을 **한 정지 프레임과 같은 페이지**에서 시험했다. 장면 밝기·분할 추정은 고정했지만 랜드마크에는 작은 떨림이 남을 수 있다. 35→42초의 한 쌍에서만 mean ΔE2000, 평균 Lab 변화 차이, 원본 고역 질감 변화의 가중합(`ΔE + 0.25 × Lab 변화 차이 + 0.1 × 질감 변화`)을 탐색했다. 기본 설정이 7.912, 기존 위치 진하기 0.55 후보는 7.917이었다. 결과 순위는 영상·보정 오차와 가중치에 따라 달라질 수 있으며, 다른 각도의 독립 검증이 없어 **어떤 후보도 앱에 채택하지 않았다**. 수치·스크린샷·설정은 Git 제외 `blush_fit_exploratory/`에만 둔다.

```powershell
research/ar_evaluation/.venv/Scripts/python.exe -B research/karina_look/capture.py --start 15 --end 35 --step 1 --folder brow_scan
research/ar_evaluation/.venv/Scripts/python.exe -B research/karina_look/capture.py --start 45 --end 75 --step 1 --folder contour_scan
research/ar_evaluation/.venv/Scripts/python.exe -B research/karina_look/capture.py --start 75 --end 105 --step 1 --folder shadow_scan
research/ar_evaluation/.venv/Scripts/python.exe -B research/karina_look/capture.py --start 105 --end 140 --step 1 --folder liner_scan
research/ar_evaluation/.venv/Scripts/python.exe -B research/karina_look/render_zone.py --zone brow
research/ar_evaluation/.venv/Scripts/python.exe -B research/karina_look/render_zone.py --zone contour
research/ar_evaluation/.venv/Scripts/python.exe -B research/karina_look/render_zone.py --zone eyeshadow
research/ar_evaluation/.venv/Scripts/python.exe -B research/karina_look/render_zone.py --zone eyeliner
research/ar_evaluation/.venv/Scripts/python.exe -B research/karina_look/explore_stage.py --zone brow
research/ar_evaluation/.venv/Scripts/python.exe -B research/karina_look/explore_stage.py --zone contour
research/ar_evaluation/.venv/Scripts/python.exe -B research/karina_look/explore_stage.py --zone eyeshadow
research/ar_evaluation/.venv/Scripts/python.exe -B research/karina_look/explore_stage.py --zone eyeliner
research/ar_evaluation/.venv/Scripts/python.exe -B research/karina_look/fit_blush_exploratory.py
```

## 추가 후보 탐색과 다른 각도 확인

35→42초 학습 쌍에서 34개 후보를 시험했다. 가중 오차는 기본 7.910, 기존 위치에 강도 0.55인 후보 7.907로 거의 같고 화면 차이도 미미했다. 같은 영상의 34→41초 쌍은 입력 얼굴이 돌아가 있고 목표 얼굴은 정면에 가깝다. 양쪽 피부 분할 마스크를 겹쳐 도구가 가리지 않은 화면 왼쪽 볼만 평가했으며, 기본 약 13.027, 강도 0.55 후보 약 12.742였다. 같은 편집 영상의 가까운 시점에 의존하고 가림·노출과 분할 오류가 남으므로 독립적인 일반화 검증이나 제품의 발림 특성으로 간주하지 않는다. 어떤 후보도 앱에 등록하지 않았다. 정렬 이미지, 마스크와 후보별 수치는 Git 제외 `blush_angle_validation/`, `blush_fit_extended/`에 둔다.

제품별 프로필을 전달하고 렌더링할 수 있는 경로를 추가했으나 등록된 프로필은 없다. 동일 프레임 WebGL 비교에서 프로필이 없을 때 기존 경로와 0픽셀 차이였고, 시험용 프로필은 3,286픽셀을 바꿨다. 이는 해당 시험 장면의 결과이며 실제 제품 재현을 입증하지 않는다.

```powershell
research/ar_evaluation/.venv/Scripts/python.exe -B research/karina_look/fit_blush_exploratory.py --extended
research/ar_evaluation/.venv/Scripts/python.exe -B research/karina_look/fit_blush_exploratory.py --validation
research/ar_evaluation/.venv/Scripts/python.exe -B research/karina_look/check_unprofiled_sameframe.py
```

## 남은 작업

검증 가능한 화장 전후 프레임과 제품별 중간 단계, 독립적인 다른 각도 입력을 확보해야 한다. 후보별 가림·조명·컷·레이어를 확인하고, 기준선 및 비교 지표를 얻기 전에는 `video-fit` 프로필을 앱에 적용하지 않는다. 최종 사용 시 단일 인물·영상 보정·자동 노출·카탈로그 hex 추정값의 한계를 함께 기록하고 Expo Go 실기기에서 같은 자리·조명으로 정면, 좌우 20~30°, 입 벌림을 확인한다.
