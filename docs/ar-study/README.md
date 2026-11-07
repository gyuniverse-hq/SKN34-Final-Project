# VISHUE AR 멘토링 대비 학습 가이드

> 작성 기준: **현재 저장소 소스코드** (`components/ar/faceTrackerHtml.ts` 등).  
> 명세(`docs/AR_SPEC.md`)에만 있고 코드에 없는 기능은 **계획/미구현**으로 표시했다.  
> 코드 수정 없음. 학습용 문서만 추가.

## 읽는 순서 (발표 전)

| 순서 | 파일 | 용도 | 예상 시간 |
|---|---|---|---|
| 1 | [01-ar-overview.md](./01-ar-overview.md) | AR 전체 구조 1페이지 요약 | 10분 |
| 2 | [02-feature-status.md](./02-feature-status.md) | 구현/부분/미구현 현황표 | 10분 |
| 3 | [03-feature-principles.md](./03-feature-principles.md) | 기능별 동작 원리 (파일·함수) | 40분 |
| 4 | [04-glossary.md](./04-glossary.md) | 반드시 외울 용어집 | 20분 |
| 5 | [05-tech-comparison.md](./05-tech-comparison.md) | 기술 비교·채택 이유 | 30분 |
| 6 | [06-mentor-qa.md](./06-mentor-qa.md) | "왜?" 질문 모범답변 | 60분 |
| 7 | [07-study-plan.md](./07-study-plan.md) | 단계별 학습 계획 | 참고 |
| 8 | [08-cram-sheet.md](./08-cram-sheet.md) | 발표 직전 5분 복습 | 5분 |

## 한 줄로 말하는 VISHUE AR

**Expo 앱(React Native)이 WebView 안에 HTML 페이지를 띄우고, 그 페이지가 카메라 → MediaPipe Face Landmarker → UV/화면 마스크 → WebGL 셰이더로 메이크업을 합성한다. 얼굴 영상은 기기 밖으로 나가지 않는다.**

## 핵심 파일 지도

| 역할 | 경로 |
|---|---|
| AR 런타임 전부 (카메라·추적·마스크·셰이더) | `components/ar/faceTrackerHtml.ts` |
| RN WebView 호스트 | `components/ar/ArFaceView.tsx` |
| 468점 UV·삼각형 | `components/ar/faceUV.ts` |
| AR 화면 UI | `app/(tabs)/ar.tsx` |
| 부위 상태·어떤 존을 칠할지 | `store/makeupStore.ts`, `types/index.ts` |
| 명세 / 진행 / 부위 요약 | `docs/AR_SPEC.md`, `docs/AR_PROGRESS.md`, `docs/AR_ZONES.md` |

## 문서 vs 코드 — 헷갈리기 쉬운 점

| 문서/기억 | 현재 코드 |
|---|---|
| Hand Landmarker로 손 가림 | **미구현**. 손·머리카락 가림은 selfie multiclass 분할 + `makeupOcclusion` |
| COASTING/FADING 상태기계 | **미구현**. 얼굴 없으면 ~700ms 후 `no-face` |
| WebGL → Canvas 2D 대체 렌더 | **미구현**. WebGL 없으면 `unavailable` → 호스트가 스와치 |
| `outputFacialTransformationMatrixes` | `createLandmarker` 옵션에 **없음** (명세와 불일치) |
| Expo SDK 57 | 프로젝트 규칙은 **SDK 58** (`AGENTS.md`) |

## 근거 표기 규칙

- **코드 근거**: 파일·함수명으로 확인됨
- **문서 근거**: `AR_SPEC` 등에 명시됨
- **추측**: 코드/문서에 선택 이유가 없을 때 명시
