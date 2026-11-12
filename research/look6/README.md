# 시연 룩 6개: 화장 전·완성 장면 확보

목표는 룩 기준 재현이다. 영상마다 화장 전 정면, 완성 정면, 완성 후 좌우 각도 장면을 확보해 겹쳐 비교하고, 그 룩의 부위별 AR 설정을 맞춘다. 대상은 `lib/demoLookAr.ts`의 6개 영상이다.

## 진행 기록

- 2026-11-12: 사용자가 립·블러셔 도포 전후 캡처 4장을 추가 제공했다. `research/data/look6/manual/e1gSkUdG6Bo_stages/`에 Git 제외로 보관했다. 립은 얼굴 전체가 없는 저해상도 클로즈업으로 크기·입 모양이 달라 전체 얼굴 랜드마크 검사나 독립 각도 검증에는 쓸 수 없다. 블러셔 전후는 얼굴 각도·표정이 달라 정렬과 조명 영향 검토가 필요하다. 하이라이터 전후와 완성 좌우·입 벌림은 여전히 없다. 룩 색과 프로필은 채택하지 않았다.
- 2026-11-12: 사용자가 제공한 `e1gSkUdG6Bo` 맨얼굴·완성 캡처 두 장을 Git 제외 `research/data/look6/manual/`에 보관했다. `score.py`의 두 장 정면 검사와 pairReady는 통과했지만 validationReady는 false다(좌우·입 벌림 없음). 이 검사는 화장 여부·부위 가림을 판정하지 않는다. 완성 사진은 앞머리로 눈썹이 가려지고 고개 방향·분홍 목도리 반사가 다르다. 제품별 도포 전후와 독립 검증 장면이 없어 룩 색과 프로필은 채택하지 않았다. 사용자 결정으로 이번 캡처를 로컬 평가에 한해 사용하며 Git 등록·외부 전송은 하지 않는다.
- 2026-11-12: ZAozXs-ZZik 추가 사진 5장으로 탐색 확대. 각도 약 19.9°·16.9° 장면의 얼굴 폭은 240.5·237.2px로 기준 300px 미달, 약 14.4° 장면도 각도·해상도 미달이다. 정면 입 벌림은 정규화 간격 0.0092·0.0104로 기준 0.02 미달이고, 19.9° 장면은 입이 더 벌어졌지만 저해상도다. 전부 탐색에 사용하되 정식 검증으로 통과시키지 않는다.
- 2026-11-12: 같은 추적 프레임에서 립 덮임·결 및 블러셔 덮임·위치 후보를 렌더해 정면과 추가 장면에 비교한다(`fit_candidates.py`). 얼굴이 돌아간 맨얼굴이 없어서 정면 맨얼굴에 완성 장면을 워핑한 탐색이며 입 벌림도 같은 이유로 왜곡될 수 있다. 색 보정 실패와 저해상도, 동일 영상의 가까운 장면으로 생기는 한계 때문에 프로필을 채택하지 않았다.
- 2026-11-12: 턱 기준 상대 Lab 오차는 립 기본→덮임 0.5배가 정면 29.74→23.10, 16.9° 후보 장면 27.42→21.17이었다. 블러셔 기본→눈 아래 위치는 정면 10.53→9.75, 16.9° 후보 장면 10.36→10.21이었으나 19.9° 장면은 10.66→10.68로 악화됐다. 이 각도 수치는 완성 사진을 정면 렌더에 맞춘 값이라 회전한 얼굴의 실제 AR 검증이 아니다. 립 후보도 경계가 남아 보여 수치 개선만으로 자연스럽다고 볼 수 없다. `candidate_search/`의 렌더·CSV·한계 기록은 Git 제외다.
- 2026-11-12: 사용자가 제공한 `ZAozXs-ZZik` 화장 전·후 사진을 Git 제외 manual에 추가하고 정면·입 다묾을 확인했다. 실제 앱 룩의 전체 및 9부위 렌더와 정렬된 사진을 비교했다. 배경 보정은 대응점 부족으로 실패했고 턱 피부 상대 보정은 색조·파운데이션의 영향을 받을 수 있어 변화 영역은 후보일 뿐이다. 각도·입 벌림 검증 사진은 아직 없다. 정지 프레임에서 립 렌더는 완성 사진보다 경계가 두드러지고 결이 약해 보인다. 영상 원본이나 이미지를 외부 서버로 보내지 않았다.
- 2026-11-12: 사용자 캡처 4장 점검. `4QR0tre9yBI`는 bare 입 벌림, final 통과, left yaw 14.8°로 기준(15~35°) 미달, open 통과, right 없음. 나머지 5개 영상 자료 없음. 자동 점수는 부위별 가림과 화장 여부를 확정하지 못한다.
- 2026-11-12: 점수로 `frames.json`을 각 영상에 생성한다. 립은 bare 입 벌림으로 제외, 다른 부위는 추가 가림·색 보정 검토 전 탐색 가능으로만 기록한다. 적합한 좌우 검증 장면이 없어 프로필 채택은 보류한다.
- 2026-11-12: 실제 훅과 번들을 사용하는 6개 룩 상태 추출 도구 및 룩×부위 프로필 전달 경로를 준비했다. 검증된 프로필은 아직 없다.
- 2026-11-12: 크기가 다른 입력을 화면 비율에 맞춰 여백을 두고 실제 AR 전체·부위별 렌더를 생성한다. 얼굴 랜드마크 정렬과 상대 변화 탐색 코드를 준비했다. 화면 잘림, 조명과 기준 피부의 파운데이션 때문에 자동 변화 영역은 확정된 메이크업 경계가 아니다.
- 2026-11-12: `4QR0tre9yBI`의 8개 부위를 탐색 비교했다. 배경 선형 보정은 대응점 부족으로 실패했다. 턱 기준 상대 변화, 임계값 3·6·9 후보 겹침과 확대 비교는 생성했지만 피부 기준에도 파운데이션이 있어 조명과 화장을 분리하지 못한다. 입술은 분석에서 제외했다. 격자·국소 탐색, 다른 각도 검증, 프로필 적용 후 측정과 실기기 검증은 아직 수행하지 않았다.
- 2026-11-12: 임계값 민감도 예: 블러셔 IoU는 3에서 0.968, 6에서 0.567, 9에서 0.000이다. 이 수치는 후보 변화 영역의 겹침이며 화장 정답 경계나 개선 증거가 아니다. 같은 WebGL 프레임의 기존·프로필 없는 경로는 0픽셀 차이였다.

```powershell
research/ar_evaluation/.venv/Scripts/python.exe -B research/look6/score.py
research/ar_evaluation/.venv/Scripts/python.exe -B research/look6/frames.py
node node_modules/jest/bin/jest.js --runInBand --roots research/look6 --runTestsByPath research/look6/extractMakeup.test.ts
node research/ar_repro/build_page.mjs components/ar/faceTrackerHtml.ts components/ar/faceUV.ts research/data/look6/page.html
research/ar_evaluation/.venv/Scripts/python.exe -B research/look6/render.py
research/ar_evaluation/.venv/Scripts/python.exe -B research/look6/measure.py
research/ar_evaluation/.venv/Scripts/python.exe -B research/look6/fit_candidates.py
```

특정 영상만 처리할 때는 `render.py --video ZAozXs-ZZik`, `measure.py --video ZAozXs-ZZik`를 사용한다. 파일명 숫자는 시각이 아닌 식별자다.

입력 캡처의 잘림·해상도 차이, 영상의 색 보정·자동 노출, 한 사람의 한 영상, 추정된 카탈로그 hex는 결과를 제한한다. 턱 기준 영역에도 파운데이션이 있을 수 있어 상대 지표도 조명의 영향을 완전히 제거하지 못한다. 립 베이스가 벌어져 있고 유효한 좌우 검증 각도가 없는 현재 입력으로 프로필을 채택하지 않는다. Expo Go 실기기 미검증.

## 데이터 규칙

- 영상 파일은 다운로드하지 않는다. 재생 화면 캡처만 쓰고 `research/data/look6/`(Git 제외)에만 둔다. 문서나 발표 자료에 프레임을 넣지 않는다.
- 공개 영상 인물 사용은 `docs/AR_SPEC.md` 1-13과 충돌하며, 사용자 요청에 따른 예외다.
- 웹 Gemini가 준 장면 시각(2026-11-11)은 6개 모두 영상 길이부터 틀려 쓰지 않았다. 실제 길이(YouTube Data API): ZAozXs-ZZik 5,576초, 4QR0tre9yBI 1,403초, kWI7_DkDjZ0 1,380초, n5otfjJSSQc 271초, e1gSkUdG6Bo 1,319초, fDqBPI1SaWY 1,727초.

## 자동 캡처 (`scan.py`)

```powershell
research/ar_evaluation/.venv/Scripts/python.exe -B research/look6/scan.py --video 4QR0tre9yBI --start 0 --end 300 --step 3 --folder start_scan
```

2026-11-11 기준으로 동작하지 않는다. 페이지를 처음 열 때 받는 약 30초 구간 밖으로 이동하면, 영상 조각 요청은 200으로 응답하지만 플레이어가 계속 불러오는 중(readyState 1)에 머문다. 헤드리스·창 모드, 화질 변경 여부와 무관하다. 로그인하지 않은 자동화 브라우저에 대한 YouTube 제한으로 보고, 우회하지 않고 중단했다. `research/karina_look/capture.py`도 같은 지점에서 멈춘다.

## 직접 캡처

1. 본인 브라우저에서 1080p 전체 화면으로 재생하고, 마우스를 치워 재생 컨트롤을 숨긴 뒤 일시정지한 화면을 캡처한다.
2. 파일 이름은 `<영상ID>_<초>_<종류>.png`로 하고 `research/data/look6/manual/`에 넣는다. 종류는 `bare`(베이스 전 맨얼굴 정면), `final`(완성 정면), `left`·`right`(완성 후 고개를 20~30° 돌린 장면), `open`(완성 후 입 벌림)이다.
3. 점수를 매긴다.

```powershell
research/ar_evaluation/.venv/Scripts/python.exe -B research/look6/score.py
```

`scores.json`과 `sheet.jpg`(초록 테두리가 통과)가 같은 폴더에 생긴다. 검사 항목은 정면 각도(yaw 8°·pitch 12° 이내), 좌우 장면의 yaw 15~35°, 눈 뜸, 입 다묾, 얼굴 안의 손, 얼굴 폭 300px 이상, 선명도다. 화장 여부와 손에서 떨어진 도구는 판단하지 못한다. 카리나 캡처로 시험했을 때, `bare`로 이름 붙인 8.0초 인트로(완성 얼굴)는 통과로 나왔고 252초 립 펜슬은 잡아내지 못했다. 그래서 종류는 사람이 정확히 붙여야 한다.
