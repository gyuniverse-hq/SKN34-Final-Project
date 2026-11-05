# PBR 립 재질 데모 명세서 (로컬 PC)

> **목적:** 본 명세서(`AR_SPEC.md`)의 3D 메시 + PBR 재질 모델(6-4, 6-5-2)과 조명 자동 추정(6-6-1)을 **노트북 웹캠과 데모 색**으로 먼저 확인한다. 결과(제형 7종 재질값, 빛 방향 추정이 쓸 만한지)는 본 앱 M3·M5·M6 작업에 그대로 가져간다.
> **범위:** 입술만. 데모 색 5개 × 제형 7종. 2D 방식과의 비교는 하지 않는다.
> **실행 환경:** Windows PC, Chrome 최신, 노트북 웹캠, Node.js 20 이상. 휴대폰·Expo Go는 이 데모 범위 밖이다.
> **작업 위치:** 저장소 밖 별도 폴더 `C:\Users\playdata2\pbr-demo` (기본). 저장소 규칙(이슈·브랜치·PR)을 거치지 않고 빠르게 실험하기 위해서다. 결과가 좋으면 본 앱 AR 페이지(`components/ar/faceTrackerHtml.ts`)로 옮긴다.

> **저장소 적용 메모 (2026-10-21):** 사용자 요청으로 별도 폴더 대신 본 앱 AR 페이지에 바로 적용해 Expo Go에서 확인한다. 진행 상태는 `docs/AR_PROGRESS.md`의 "순서 밖 작업"에 적는다.

---

## 0. 진행 방법 (코딩 에이전트에게)

사람은 처음에 **"`PBR_DEMO_SPEC.md`를 읽고 D0부터 시작해줘"**라고 말하고, 이후에는 **"다음"**이라고 말한다.

1. 이 문서의 1장(원칙)을 5줄 이내로 요약해 확인한다.
2. 4장의 단계(D0 → D5)를 **한 번에 하나씩** 진행한다.
3. 단계마다 구현 → `npm run build` 성공 → 완료 기준을 표(통과 / 실패 / **사람 확인 필요**)로 보고 → 멈추고 "다음 단계: Dx"를 알린다.
4. 진행 상태를 `PROGRESS.md`(데모 폴더 안)에 적는다. 새 대화에서도 이 파일을 보고 이어간다.
5. 웹캠·화면을 직접 볼 수 없으므로, 눈으로 확인할 항목은 "사람 확인 필요"로 남기고 **무엇을 보면 되는지** 적는다.
6. 새 라이브러리는 이름·버전·라이선스를 먼저 보고한다.

| 사람 명령 | 동작 |
|---|---|
| `다음` | 다음 단계 진행 |
| `Dx 다시` | 해당 단계 수정 |
| `상태` | `PROGRESS.md` 요약 |
| `확인 결과: …` | 사람이 본 결과를 `PROGRESS.md`에 적고, 문제가 있으면 고칠지 묻기 |

---

## 1. 원칙 (본 명세서와 같음)

| # | 원칙 | 데모에서 |
|---|---|---|
| 1 | 제품 색은 바꾸지 않는다 | albedo는 데모 색 값 그대로. 보기 좋게 조정하지 않는다 |
| 2 | 실제 그대로 | 피부 보정·얼굴형 필터·배경 흐림 없음 |
| 3 | 명암과 입술 결은 카메라의 실제 값 | 반사(하이라이트)만 PBR로 계산한다 |
| 4 | 얼굴 영상은 밖으로 보내지 않는다 | 프레임 저장·업로드 없음. 스크린샷은 사람이 직접 찍는다 |
| 5 | 데모 색은 실제 제품 색이 아니다 | 화면에 "데모 색 (실제 제품 아님)"을 항상 표시 |

---

## 2. 기술 구성

| 영역 | 선택 | 라이선스 |
|---|---|---|
| 개발 서버 | Vite + TypeScript (`localhost`라 카메라 사용 가능, HTTPS 불필요) | MIT |
| 얼굴 추적 | `@mediapipe/tasks-vision` (npm, 버전 고정) FaceLandmarker + ImageSegmenter(`selfie_multiclass_256x256`) | Apache 2.0 |
| 모델 파일 | `face_landmarker.task`, `selfie_multiclass_256x256.tflite`를 `public/models/`에 내려받아 로컬에서 로드 | Apache 2.0 |
| 표준 얼굴 모델 | [canonical_face_model.obj](https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/modules/face_geometry/data/canonical_face_model.obj) → UV·삼각형 배열 | Apache 2.0 |
| 렌더링 | WebGL2 직접 작성 또는 Three.js(`ShaderMaterial`, 버전 고정) | MIT |
| 색 계산 | 직접 작성: 정식 sRGB EOTF, Lab(D65), CIEDE2000 | — |

```
pbr-demo/
  public/models/            face_landmarker.task, selfie_multiclass_256x256.tflite
  assets/                   canonical_face_model.obj (출처·라이선스 주석)
  scripts/buildFaceUV.ts    obj → src/render/faceUV.ts (정점 468개 UV + 삼각형)
  src/
    main.ts                 카메라 시작, 프레임 루프
    tracking/face.ts        FaceLandmarker (VIDEO, GPU → 실패 시 CPU)
    tracking/oneEuro.ts     정점 떨림 줄이기
    tracking/segment.ts     배경 분할 (조명 추정용)
    light/estimate.ts       조명 색(Gray World) + 빛 방향(얼굴 메시)
    color/srgb.ts lab.ts deltaE.ts
    render/faceUV.ts        생성된 UV·삼각형
    render/mesh.ts          매 프레임 정점 갱신, 법선 계산
    render/uvPainter.ts     UV 텍스처에 입술 마스크·채널 그리기
    render/lipShader.ts     6장 셰이더
    material.ts             제형 7종 재질값 (5장)
    demoShades.ts           데모 색 5개 (3장)
    ui/panel.ts             조절 패널
  PROGRESS.md
```

---

## 3. 데모 색 (실제 제품 색 아님)

| id | 이름 | HEX (sRGB) | 비고 |
|---|---|---|---|
| `demo-rose` | 데모 로즈 | `#C25A6E` | 중간 밝기 핑크 |
| `demo-coral` | 데모 코랄 | `#E06A4E` | 따뜻한 주황 계열 |
| `demo-red` | 데모 레드 | `#B3202E` | 진한 레드 |
| `demo-berry` | 데모 베리 | `#7E2A4A` | 어두운 보라 계열 |
| `demo-nude` | 데모 누드 | `#C08A7A` | 피부에 가까운 색 |

- 모든 데모 색의 a1(1회 덮는 정도)은 0.6으로 둔다(데모용 고정값).
- 실제 제품을 쓸 때는 본 명세서 6-15의 측정값으로 바꾼다.

---

## 4. 단계와 완료 기준

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| **D0** | 프로젝트 만들기 | Vite + TS 프로젝트 생성, `npm run dev`로 `http://localhost:5173` 열림, 모델 파일 2개와 obj 파일 위치 확인, 의존성·라이선스 목록 보고, `PROGRESS.md` 생성 |
| **D1** | 웹캠 + 얼굴 추적 | 전면 카메라 영상 표시, 얼굴 점 오버레이(디버그 켜고 끄기), FPS 표시, GPU 실패 시 CPU 전환 로그, One Euro 적용. **사람 확인:** 점이 입술을 정확히 따라가는지 |
| **D2** | 3D 메시 + UV | `buildFaceUV.ts`로 UV 배열 생성, 매 프레임 메시 갱신, 입술 마스크를 UV에 그려 단색으로 표시, 입 안쪽·치아는 비어 있음. **사람 확인:** 정면·30°·45°에서 색이 입술에 붙어 있는지, 입을 벌려도 치아에 안 칠해지는지 |
| **D3** | 베이스 컬러 + 실제 명암 | 데모 색 5개 선택, 6장 1~4번 계산(albedo × 조명 색 × 실제 명암 + 실제 입술 결), 진하기 슬라이더(coverage). **사람 확인:** 입술 주름과 그림자가 그대로 보이는지, 색이 페인트처럼 평평하지 않은지 |
| **D4** | 조명 추정 | 배경 Gray World로 조명 색, 얼굴 메시로 빛 방향·세기 계산(0.5초마다), 패널에 추정값과 신뢰도 표시, 빛 방향을 손으로 바꾸는 "수동" 모드. **사람 확인:** 스탠드 조명을 좌우로 옮기면 빛 방향 값이 따라 바뀌는지 |
| **D5** | PBR 반사 + 제형 7종 | 6장 5~7번(GGX 반사, 쉬머 입자), 제형 7종 선택, 재질값 슬라이더(roughness, specular 배율)로 실시간 조정, 조정한 값을 JSON으로 화면에 표시(복사용). **사람 확인:** 매트와 글로시 차이가 분명한지, 고개를 돌리면 하이라이트가 빛 쪽에 맺혀 움직이는지, 쉬머 반짝임이 자연스러운지 |

---

## 5. 제형 7종 재질값 (시작값, D5에서 조정)

| 제형 | 한국어 | roughness | specular 배율 | coverage 배율 | 펄 입자 |
|---|---|---|---|---|---|
| matte | 매트 | 0.90 | 0.3 | 1.0 | 없음 |
| velvet | 벨벳 | 0.75 | 0.4 | 1.0 | 없음 |
| cream | 크림 | 0.55 | 0.7 | 1.0 | 없음 |
| satin | 새틴 | 0.45 | 0.8 | 1.0 | 없음 |
| sheer | 시어 | 0.30 | 1.0 | 0.6 | 없음 |
| glossy | 글로시 | 0.15 | 1.2 | 1.0 | 없음 |
| shimmer | 쉬머 | 0.40 | 0.8 | 1.0 | 있음 |

- roughness가 클수록 빛이 퍼져 보송해 보이고(매트), 작을수록 하이라이트가 또렷하다(글로시).
- 최종 값은 D5 화면의 JSON을 복사해 본 앱 `constants/material.ts`에 넣는다.

---

## 6. 셰이더 계산 (입술 픽셀마다)

```
1. cam    = 카메라 픽셀 (sRGB → 선형, 정식 EOTF)                 ← 실제
2. shade  = 카메라 밝기 / 입술 평균 밝기 (하이라이트·그림자 제외 중앙값, 0.5초마다)  ← 실제 명암
3. base   = albedo(데모 색, 선형) × 조명 색 × shade
4. detail = 카메라의 미세 밝기 차이 (입술 평균 대비)              ← 실제 입술 결
5. spec   = GGX(메시 법선, 빛 방향, 시선, roughness) × specular 배율 × 조명 세기
6. flake  = shimmer일 때만: 고정된 UV 노이즈 × 빛 방향 반짝임
7. out    = mix(cam, base + detail + spec + flake, coverage × 마스크)
8. 화면   = 선형 → sRGB
```
- 빛 방향 신뢰도가 낮으면 5번은 "원래 입술의 밝은 곳에 하이라이트를 더하는" 단순 방식으로 바꾼다.
- 6번 노이즈는 **UV 좌표에 고정**해서, 고개를 돌려도 입자가 입술에 붙어 있게 한다.
- 입술 경계는 2~4px로 부드럽게 처리하고, 경계에서는 반사를 줄여 빛 번짐을 막는다.
- 입술 밖 픽셀은 절대 바꾸지 않는다.

---

## 7. 조절 패널

| 조절 | 범위 |
|---|---|
| 데모 색 | 5개 버튼 (항상 "데모 색" 표시) |
| 제형 | 7개 버튼 |
| 진하기 | 0~1 슬라이더 |
| 빛 방향 | 자동(추정) / 수동(가로·세로 슬라이더) |
| roughness, specular 배율 | 제형별 슬라이더 (D5) |
| 표시 | 얼굴 점, 메시 선, 빛 방향 화살표, FPS 켜고 끄기 |
| 재질값 JSON | 현재 7종 값 표시 + 복사 버튼 |

---

## 8. 실행 방법

```bash
# PC에서 (처음 한 번)
mkdir C:\Users\playdata2\pbr-demo
cd C:\Users\playdata2\pbr-demo
# 이 폴더에서 Claude Code를 열고: "PBR_DEMO_SPEC.md를 읽고 D0부터 시작해줘"

# 실행
npm install
npm run dev
# Chrome에서 http://localhost:5173 → 카메라 허용
```
- `PBR_DEMO_SPEC.md`를 데모 폴더에 복사해 둔다.
- 모델 파일(`.task`, `.tflite`)과 obj는 D0에서 에이전트가 받을 주소를 알려 주고, 사람이 내려받아 넣어도 된다.
- 조명 실험은 스탠드 조명 하나를 좌우로 옮기며 하면 빛 방향 확인이 쉽다.

---

## 9. 본 앱으로 가져갈 것

| 데모 결과 | 본 명세서 |
|---|---|
| 조정한 제형 7종 재질값 JSON | `constants/material.ts` (6-5-2) |
| UV 생성 스크립트·메시 코드 | M3 (`scripts/buildFaceUV.ts`, 6-4) |
| 조명 추정 코드와 신뢰도 기준 | M5 (6-6-1) |
| 셰이더 | M6 (6-5-2), AR 페이지 HTML 문자열로 옮김 |
| FPS 기록 | M9 성능 단계 기준 참고 |

- 본 앱으로 옮길 때는 본 명세서 6-0 규칙을 따른다: AR 페이지 안에서는 저장·네트워크 호출 금지, 메시지는 숫자만, Expo Go 유지.
