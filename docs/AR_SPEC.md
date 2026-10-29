# K-뷰티 AR 가상 메이크업 구현 명세서 (설계서 v2.1)

> **부제:** 내 얼굴에서 실제로 보일 모습 그대로 (Realism)
> **문서 용도:** 서비스 구조(A부)와 구현 설계(B부)를 한 문서로 묶었다. 저장소에는 `docs/AR_SPEC.md`로 두고(`CLAUDE.md`·`AGENTS.md`는 저장소 것을 그대로 쓴다) **"9. 명령 예시"**의 문장으로 지시한다.
> **작성일:** 2026-10-21 · **대상 저장소:** `gyuniverse-hq/SKN34-Final-Project` (`develop`, Expo SDK 57) · **범위:** 기존 Expo 앱의 AR(WebView 안 HTML 페이지) MVP, 립 우선 + 레시피 추출·대화형 조정(API 라우트) + 숙제 02·04 실험
> **주요 내용:** Expo Go 실행 구조(6-0) · 제형 7종(6-9-2) · 조명 자동 추정, 갤럭시·아이폰 공통(6-6) · 유사 제품 추천(F7-2) · 데이터 가져오기(6-15) · 기초화장품 추천(F16, 후순위) · 추가 기능(F17~F23, MVP 다음) · 숙제 02·04 실험(8-A) · 평가 도구 적용 방법(8-B) · **진행 방법(0-A): "0-A 절차대로 시작해줘" → "다음"**

---

# A부. 서비스 구조

## A-1. 멘토 피드백의 핵심 두 가지

1. **AR로 보여 주는 것과 실제 제품 효과를 예측하는 것은 서로 다른 기술 문제다.**
2. **AI 기능을 많이 썼다는 것과 AI가 있어야만 풀리는 사용자 문제가 있다는 것은 다르다.**

이 둘을 구분하면 기술 선택과 평가 기준이 명확해진다. 이 설계서의 원칙(1장), 기능별 AI 근거(2-1), 평가 트랙(8장)은 모두 이 두 가지에서 나온다.

## A-2. 서비스 방향

| 방향 | 역할 | 핵심 경쟁력 | 난점과 대응 |
|---|---|---|---|
| **① K-스타일 재현** | **중심** | 원하는 메이크업을 AI가 분석해 내 얼굴에 적용 | 룩 데이터 사용 권리 → 영상은 공식 API·임베드만, 이름·사진 미표시, 사용자 이미지는 저장하지 않고 레시피만 |
| **③ 대화형 메이크업 코치** | **중심** | 대화로 단계별 안내하고 AR을 수정 | 여러 차례 대화의 맥락 유지 → 대화 상태 관리(6-13) |
| ② 실물 발색 예측 | 부가 (연구 트랙 B) | 구매 결정에 직접 기여 | 검증 난도가 매우 높음 → 절대 목표가 아니라 "보정 전 대비 감소율"로 측정 |
| ④ 뷰티 쇼핑 플랫폼 | 부가 (사업) | 추천·샘플·구매, B2C·B2B 확장 | 제휴·수익성 검증 필요 → 제휴 링크로 시작, 인디 브랜드 중개는 이후 |

## A-3. 대표 사용자 경험

```
① K-스타일 선택 / 이미지 입력         원하는 메이크업 탐색
      - 주간 신규 룩(유튜브 레시피 파이프라인)
      - 이미지 입력: 저장하지 않고 레시피만 추출, 화면엔 컨셉 이름만
          ↓
② AI 메이크업 레시피 추출 [VLM]       부위 · 순서 · 색상 · 기법 구조화
          ↓
③ AR 시뮬레이션 + 대화형 조정 [CV + STT + LLM]
      - 3D 얼굴 메시 + UV(고개를 돌려도 유지), 조명 색 × 명암
      - 보기: 지금 조명 / 표준 조명 / 갈 곳 조명
      - "아이라인 조금 연하게", "내 피부톤에 어울리는 색으로" → 레시피 수정 → AR 갱신
      - 진하기 ↔ 바르는 횟수
          ↓
④ 화장법 가이드 + 실제 상품 연결      따라 하기 · 제품 비교 · 샘플 · 구매
      - 순서별 가이드(기초 → 베이스 → 색조), 음성 코치
      - 기초 추천: 직접 답한 피부 타입 × 써 본 제품의 성분 (사진 분석 없음, 6-16)
      - 따라 바르기 모드: 실제 바른 색 측정 → 안내 → 내 발색 보정
      - 제품 비교: 두 줄 추천, 실측 사진, 가진 제품 비교, 정확도 표시
          ↓
⑤ 공유: 얼굴 바깥 글씨·프레임만, "AR 예상 이미지" 표시
```

각 AI 기술이 따로 존재하지 않고 이 한 흐름을 완성하는 데 기여한다.

## A-4. 근거

| 근거 | 내용 | 적용 |
|---|---|---|
| MediaPipe Face Landmarker (Google) | JavaScript에서 얼굴 랜드마크·표정 데이터 추출 지원 | 웹 기반 AR 실험 가능 (트랙 A) |
| MediaPipe Face Mesh 문서 | 표준 얼굴 모델 UV, 페이스 페인팅 렌더링, 깊이 가림막 | 고개를 돌려도 유지 (트랙 A) |
| Face Mesh V2 모델 카드 | 80° 넘게 돌리거나 50% 넘게 가려지면 부적합 | 각도 범위 안내 |
| arXiv 2512.21988 (2025, 동료 심사 전) | 한국인 965명 × 얼굴 5개 부위. 보정 전 스마트폰 카메라는 DSLR 대비 평균 ΔE 10.63, 태블릿 13.27. 전체 색 보정 행렬로 61~74% 감소했지만 중앙값이 여전히 ΔE 2 초과. 부위별 보정 시 ITA 기기 간 일치도(ICC) 0.72 → 0.93. 기기보다 **얼굴 부위**가 색 차이의 더 큰 원인 | 트랙 B 난도 근거, 부위별 측정 설계 |
| Oliver (1980) 기대 일치 이론 | 만족은 기대와 실제의 차이로 결정 | Realism 원칙의 이유 |
| Yun & Seo (2026) 한국패션기술학회지 | 가상 피팅이 반품을 줄이는 건 기대와 실제의 차이를 좁힐 때 | 트랙 B의 사업적 의미 |

## A-5. 포지셔닝과 수익 구조 (사업 참고 — 구현 대상 아님)

| 플랫폼 | 답하는 질문 | 핵심 가치 |
|---|---|---|
| 올리브영 | 어디서 사지? | 유통·경험 |
| 화해 | 뭘 고르지? | 정보·검증 (성분, 리뷰) |
| 다이소 | 얼마에 사지? | 가성비 |
| **우리** | **내 얼굴에서 실제로 어떻게 보이지?** | **구매 전 확인 (Realism)** |

- **관계:** 세 플랫폼과 정면 경쟁하지 않는다. 구매 직전 "확인 단계"를 맡아 그들의 매장·온라인몰로 손님을 보내는 **입구**가 된다.
- **차별점:** ① 보정 없는 실제 그대로 ② 색 기준 듀프 찾기(색·제형 사실만) ③ 매장 가기 전 미리 발라 보기 + 한국어 쇼핑 리스트(외국인 관광객) ④ K-룩 레시피를 내 얼굴에 ⑤ 얼굴 영상이 기기 밖으로 나가지 않음
- **수익 순서:** 1단계 구매 연결 제휴(쇼핑 리스트·판매처 링크, 쿠폰 코드로 전환 확인) → 2단계 브랜드 셰이드 측정 제휴("측정 완료" 표시, 순위는 색으로만, 1-14) → 3단계 인디 브랜드 AR 위젯·관광 제휴·익명 트렌드 리포트(동의한 집계만)
- **가격 정하는 법:** 원가(셰이드 측정 시간·재료, 서버, AI API 사용량)를 최저선으로 → 브랜드가 얻는 가치(기대 일치도가 높아 반품·불만 감소)로 설득 → 상용 SDK보다 낮은 진입 가격(인디 브랜드). 사용자는 무료.
- **하지 않는 것:** 수수료 높은 제품을 위로 올리기, 실제보다 예쁘게 보여 주기, 가짜 긴급성("3개 남음"), 효능 단정, 근거 없는 최상급 표현("실제와 100% 같음"). 경쟁사 이름을 쓴 비교 광고는 검토 후.
- **핵심 지표:** 추천 → 담기 비율, 쇼핑 리스트 생성률, 판매처 링크 클릭률, **"AR에서 본 것과 비슷했나요?"(1~5, 트랙 B 기대 일치도)**, 재방문 후 다시 담기.
- **확인이 필요한 숫자 (발표 전):** 판매처 제휴 수수료율, 외국인 관광객 뷰티 쇼핑 통계, 셰이드 1개 측정 비용, AI API 사용량별 비용. 확인 전에는 "가정"으로 표시한다.

---

# B부. 구현 설계

### 반드시 구분하는 두 가지
| 구분 | A. 시뮬레이션 현실감 (Visual Realism) | B. 실물 발색 정확도 (Color Accuracy) |
|---|---|---|
| 질문 | 내 얼굴에 자연스럽게 붙어 보이는가? | 실제 제품을 바르면 이 색이 나오는가? |
| 관련 모듈 | 추적, 메시·UV, 명암, 경계, 노이즈, 끊김 대응 | 제품 측정값, 조명 보정, 부위별 피부 측정, 발색 혼합 모델, 사용자 보정 |
| 평가 | 사람 평가(자연스러움·진짜/가짜 판별), LPIPS, 추적 안정성 | 실제 사진 대비 ΔE2000(보정 전 대비 감소율), 기대 일치도 |
| 실험 | 8장 트랙 A | 8장 트랙 B |

두 트랙은 연결되지만 **같은 실험으로 평가하지 않는다.** A가 좋아도 B는 틀릴 수 있다.

---

## 0. 작업자(코딩 에이전트)에게

- 이 문서의 **1장 절대 원칙**은 어떤 작업에서도 어기지 않는다. 원칙과 충돌하는 요청을 받으면 구현하지 말고 충돌 내용을 먼저 보고한다.
- 마일스톤(7장) 단위로 작업한다. 한 번에 하나의 마일스톤만 진행하고, 끝나면 **완료 기준**을 하나씩 확인한 결과를 보고한다.
- 새 의존성을 추가할 때는 이름, 버전, 라이선스를 보고한다. **비상업 라이선스 모델은 기본 비활성 플래그 뒤에만** 둔다(1-7).
- 측정되지 않은 제품 색을 지어내지 않는다. 테스트용 색은 `measureMethod: "placeholder"`로 표시한다.
- 팀 기술 스택이 3장과 다르면 3장만 바꿔 쓰고 나머지 규칙은 유지한다.
- **저장소의 `AGENTS.md` 규칙을 먼저 따른다**(Expo SDK 57 문서 확인, `npx expo install`, `npm run check`, i18n 네 언어, 브랜치·커밋·PR 규칙, 실제 이슈 번호). 이 명세서와 `AGENTS.md`가 충돌하면 구현하지 말고 먼저 보고한다.
- **Expo Go에 포함된 모듈만** 쓴다. 커스텀 네이티브 모듈이 필요해 보이면 추가하지 말고 먼저 보고한다(development build 전환은 팀 결정, 11장).
- 4장에서 [기존]으로 표시한 파일은 **수정**한다. 같은 역할의 새 파일을 따로 만들지 않는다. 범위 밖 화면(4장 끝)은 건드리지 않는다.
- 화면 문구는 직접 쓰지 않고 `lib/i18n` 키로 만들어 en·ko·ja·zh 네 사전에 모두 넣는다. 이 명세서의 한국어 문구("거의 같아요" 등)는 ko 사전 값이다.
- 숙제 실험 코드는 `research/`에만 둔다. 앱 마일스톤(M)과 숙제 실험(R)은 따로 진행하고, 숙제가 앱 작업을 막지 않게 한다.

## 0-A. 진행 방법 — 이 명세서만 넣고 단계적으로 진행하기

사람은 처음에 **"`docs/AR_SPEC.md` 0-A 절차대로 시작해줘"**라고만 말하고, 이후에는 **"다음"**이라고 말한다. 에이전트는 아래 절차를 스스로 따른다.

**처음 받았을 때 (한 번만)**
1. `AGENTS.md`, `CONTRIBUTING.md`, 이 문서의 0장·1장을 읽고, 절대 원칙과 저장소 규칙을 10줄 이내로 요약해 보고한다.
2. `docs/AR_PROGRESS.md`(진행표)가 있는지 확인한다. 없으면 7-1의 **S0**부터 시작한다.
3. 진행표가 있으면 그 상태를 이어서 쓴다. 대화 기록이 없어도 진행표만 보고 이어갈 수 있어야 한다.

**마일스톤 하나마다 (반복)**
1. **고르기:** 7-1 진행 순서표에서 상태가 `대기`인 것 중 **가장 앞 순서**이면서 **선행 마일스톤이 `완료`**인 것을 고른다.
2. **선행 조건 확인:** 표의 "사람이 준비할 것"(API 키, 측정 데이터, 실기기, 사진 등)이 없으면 **구현하지 않는다.** 무엇이 필요한지 알리고, 지금 할 수 있는 다음 마일스톤을 제안한다. 진행표에 `보류(이유)`로 적는다.
3. **이슈 번호 받기:** 사용자에게 GitHub 이슈 번호를 묻는다. 번호를 지어내지 않는다(`AGENTS.md`). 받은 번호로 `develop` 최신에서 브랜치를 만든다.
4. **읽기:** 해당 마일스톤의 절(6장)과 완료 기준(7-2)만 다시 읽는다. 원칙(1장)과 충돌하면 구현 전에 멈추고 보고한다.
5. **구현:** 한 마일스톤만 한다. 범위 밖 파일(4장 끝)은 건드리지 않는다.
6. **검사:** `npm run check`(타입체크 + 린트 + 테스트)를 통과시킨다. Python 스크립트가 있으면 해당 테스트도 돌린다. 테스트를 지우거나 완화하지 않는다.
7. **보고:** 완료 기준을 항목별 표(통과 / 실패 / **사람 확인 필요**)로 보고한다. 실기기·사진·사람 판단이 필요한 항목은 "사람 확인 필요"로 남기고, 무엇을 어떻게 확인하면 되는지 적는다.
8. **진행표 갱신:** `docs/AR_PROGRESS.md`에 상태, 날짜, 브랜치, 남은 문제, 사람 확인 결과 칸을 적는다.
9. **커밋:** `AGENTS.md` 규칙대로 커밋한다(`<type>: 한국어 설명`, 목적별로 나눔). **푸시와 PR은 사용자가 승인한 뒤에만** 한다.
10. **멈추기:** "다음 마일스톤: Mx — 내용, 사람이 준비할 것: …"을 알리고 기다린다.

**사람이 쓰는 짧은 명령**

| 명령 | 에이전트 동작 |
|---|---|
| `다음` | 진행표 기준으로 다음 마일스톤을 고르고 1번부터 진행 |
| `Mx 진행` | 순서와 상관없이 Mx 진행 (선행 조건은 그대로 확인) |
| `Mx 건너뛰기` | 진행표에 `건너뜀(사유)`으로 적고 다음으로 |
| `상태` | 진행표 요약: 완료·진행 중·보류·남은 것, 사람이 준비할 것 목록 |
| `사람 확인 결과: …` | 실기기·사진 확인 결과를 진행표에 적고, 실패 항목이 있으면 고칠지 묻기 |

**하지 않는 것:** 여러 마일스톤 한 번에 진행, 선행 조건 무시, 이슈 번호 지어내기, 사용자 승인 없는 푸시·PR, 측정값·가격·라이선스 지어내기, 범위 밖 기능 추가.

**진행표 형식 (`docs/AR_PROGRESS.md`, S0에서 만든다)**
```markdown
# AR 진행표
마지막 갱신: YYYY-MM-DD

| 순서 | 마일스톤 | 상태 | 이슈 | 브랜치 | 날짜 | 사람 확인 | 남은 문제 |
|---|---|---|---|---|---|---|---|
| 1 | S0 명세서 연결 | 완료 | #15 | docs/15-ar-spec | 10-21 | — | — |
| 2 | M0 저장소 확인 | 대기 | | | | | |
...

## 사람이 준비할 것
- [ ] Gemini API 키 (.env, M10·M11)
- [ ] 공공데이터포털 인증키 (M1-D 실데이터)
- [ ] 숙제 01 측정 CSV (M7 실데이터, 트랙 B)
- [ ] 아이폰·갤럭시 실기기 확인 (M0-E부터)

## 결정 기록
- YYYY-MM-DD: (11장 결정 사항 중 정해진 것)
```
상태 값: `대기` / `진행 중` / `완료` / `보류(이유)` / `건너뜀(이유)`

## 0-B. 저장소 연결 — `CLAUDE.md`와 `AGENTS.md`

- 저장소의 `CLAUDE.md`는 `@AGENTS.md` 한 줄로 `AGENTS.md`를 불러온다. **`CLAUDE.md`는 수정하지 않는다.** 규칙은 `AGENTS.md`에 둔다(`CONTRIBUTING.md`: 규칙은 이 문서와 `AGENTS.md`를 함께 맞춘다). 그래야 Claude Code, Cursor, Codex가 같은 규칙을 읽는다.
- **이 명세서 전체를 `CLAUDE.md`나 `AGENTS.md`에 불러오지 않는다**(`@docs/AR_SPEC.md` 금지). 약 1,600줄이라 작업마다 컨텍스트를 많이 차지한다. 대신 안내 줄만 넣고, 작업할 때 필요한 절만 읽는다.
- S0에서 `AGENTS.md`의 `## This project` 아래에 다음 두 줄을 추가한다.

```markdown
- AR 가상 메이크업, 제품 추천, 대화형 조정, 평가·숙제 실험 작업은 `docs/AR_SPEC.md`를 따른다. 작업 전에 0-A 진행 방법, 1장(절대 원칙), 해당 마일스톤·모듈 절을 먼저 읽고, 원칙과 충돌하면 구현 전에 보고한다.
- 진행 상태는 `docs/AR_PROGRESS.md`에 있다. 새 세션에서는 이 파일을 먼저 읽고, 0-A 절차대로 다음 마일스톤을 이어서 진행한다.
```

- `docs/AR_PROGRESS.md`는 짧게 유지한다(표 + 준비할 것 + 결정 기록). 길어지면 완료된 줄은 요약한다.

---

## 1. 절대 원칙

| # | 원칙 | 구현 규칙 |
|---|---|---|
| 1-1 | **제품 색은 바꾸지 않는다** | 제품 Lab·진하기를 보기 좋게 바꾸는 처리 금지. 바뀌는 건 조명 곱하기·명암·진하기(사용자 조절)뿐 |
| 1-2 | **Realism: 내 얼굴에서 실제로 보일 모습 그대로** | 미화 모드 없음. 배경 흐림·분위기 배경·링라이트 같은 연출 프리셋 없음. 보기 옵션은 "지금 조명 / 표준 조명 / 갈 곳 조명"뿐이며 모두 현실 조건을 재현하는 것 |
| 1-3 | **피부 보정·얼굴형 필터 금지** | 피부 매끈하게, 얼굴 축소, 밝기 올리기 등은 어디에도 넣지 않는다(공유 카드 포함). 공유 카드에 허용되는 건 얼굴 바깥의 글씨·프레임뿐 |
| 1-4 | **사용자 얼굴 영상은 기기 밖으로 보내지 않는다** | 카메라 프레임·사용자 얼굴 이미지 업로드 금지. 서버에는 Lab 값 등 숫자만, 그것도 동의 시에만. 카메라 프레임은 **AR 페이지(WebView) 안에서만** 처리하고, 앱과 페이지 사이에도 숫자·상태만 오간다. 페이지 안에서는 네트워크 호출·저장을 하지 않는다(기존 `__tests__/faceTracker.test.ts`, 6-0). (참고 이미지 입력은 1-11) |
| 1-5 | **판단은 수식, 말은 LLM** | 제품 선택·색·진하기·횟수는 결정적 코드로 계산. LLM은 발화→함수 호출 변환과 설명 문장만 |
| 1-6 | **유명인 이름·사진 표시 금지** | UI에는 컨셉 룩 이름만. 내부 검색 키워드는 클라이언트 번들에 포함하지 않는다 |
| 1-7 | **라이선스** | Apache/MIT/BSD만 기본 활성. `face-parsing`(비상업) 등은 `FEATURE_NONCOMMERCIAL_MODELS=false` 기본값의 플래그 뒤에 |
| 1-8 | **측정값과 추정값을 구분** | 모든 제품 색에 `measureMethod`(measured / user_verified / estimated / placeholder)를 두고 UI에 표시 |
| 1-9 | **점수 표시 금지** | 따라 바르기 결과는 점수가 아니라 안내 문장으로만 |
| 1-10 | **AI는 AI가 필요한 문제에만** | 각 AI 모듈은 2-1 표의 "AI가 필요한 이유"가 있어야 한다. 수식으로 풀리는 문제(색 계산, 매칭, 횟수)에 모델을 쓰지 않는다 |
| 1-11 | **참고 이미지 입력은 레시피만 남긴다** | 사용자가 올린 메이크업 참고 이미지는 서버 VLM 호출에만 쓰고 **저장하지 않는다**(메모리 처리 후 폐기). 결과는 레시피 JSON만 저장. 화면에는 원본 이미지·인물 정보를 다시 보여 주지 않고 컨셉 이름만 |
| 1-12 | **두 평가 트랙을 섞지 않는다** | 시뮬레이션 현실감(A)과 실물 발색 정확도(B)는 별도 스크립트·별도 데이터로 평가하고 보고서에도 따로 적는다 |
| 1-13 | **연구 코드와 앱 코드를 나눈다** | 비상업 모델·외부 평가 API는 `research/`에서만 import. 평가용 얼굴 사진은 동의한 팀원 것만, `data/`(저장소 제외)에만 둔다 |
| 1-14 | **제휴는 순서에만, 비슷함 표시는 색으로만** | 유사 제품 추천(F7-2)에서 "거의 같아요 / 비슷해요 / 조금 달라요" 묶음은 색·제형(ΔE2000 + 제형 벌점)만으로 정한다. 제휴 벌점은 같은 묶음 안의 순서에만 반영하고, 제휴 제품에는 "제휴" 표시를 붙인다 |

---

## 2. 기능 범위 (MVP)

| ID | 기능 | MVP 포함 | 비고 |
|---|---|---|---|
| F0 | Expo 앱 셸 + WebView AR 연결 | ✅ | Expo Go로 실행 (6-0) |
| F1 | 카메라 + 얼굴 추적 | ✅ | |
| F2 | 조명 자동 추정 (갤럭시·아이폰 공통) | ✅ | 6-6-1. 흰 종이 등 도구 없음. 플랫폼 조명 추정(ARKit·ARCore)은 조건부 후보(6-6-2) |
| F3 | 3D 메시 + UV 텍스처 립 렌더링 | ✅ | 고개를 돌려도 유지 |
| F4 | 추적 끊김 대응 | ✅ | |
| F5 | 진하기 슬라이더 ↔ 바르는 횟수 | 🔶 블러셔·파운데이션만 막대 | 10-27 전 부위 막대 제거. 10-28: 블러셔 탭만 연하게↔진하게(0.15~1). 10-29: 파운데이션 탭에 커버력 막대(사용자 요청). 다른 부위는 룩·기본 `intensity` |
| F6 | 보기 옵션: 지금 조명 / 표준 조명 / 갈 곳 조명 | ✅ | v1의 체험/비교 모드 대체 |
| F7 | 제품 매칭(ΔE2000) + 두 줄 추천 + 실측 사진 + 가진 제품 비교 | ✅ | 로컬 JSON DB. 목표 룩 기준 |
| F7-2 | **유사 제품 추천**: 지금 AR 색 + 제형이 비슷한 순 | ✅ | 6-9-2. 대화로 조건 변경 |
| F8 | 따라 바르기 모드 | ✅ | 립만 |
| F9 | 기기 성능 단계 | ✅ | |
| F10 | **레시피 추출 (VLM)**: 유튜브 영상 + 참고 이미지 | ✅ | 서버. 영상은 사전 작업, 이미지는 요청 시 |
| F11 | **대화형 조정 (텍스트)**: LLM 함수 호출 + 대화 상태 | ✅ | 서버. 텍스트 입력부터 |
| F12 | 음성 입력 (Whisper) | ⏳ | F11에 입력 경로만 추가 |
| F13 | 블러셔·아이라인·섀도 (+ 마스카라·하이라이터·쉐딩, 10-25 사용자 요청; + 아이브로우·파운데이션, 10-27) | 🔶 렌더링 구현(데모 색) | 6-5-4. 10-27: AR 카메라는 마스카라·하이라이터·쉐딩을 칠하지 않음(룩 데이터는 유지). 아이브로우·파운데이션은 색만(보정 없음). 대화형 `set_geometry`(M11)는 아직 |
| F14 | SNS 공유, 어디서든 AR, 제휴 구매 | ⏳ | AR 범위 밖 |
| F15 | 행동 이벤트 기록 | ✅ | 동의 시, 숫자·ID만, 기기 안 저장 + 평가용 내보내기 (6-14). 추천 계산에는 아직 쓰지 않음 |
| D | 데이터 가져오기 (측정 CSV, 식약처 성분 API, 공식몰 수동 입력, 판매 플랫폼 수집 데이터) | ✅ | 6-15 |
| F16 | **기초화장품 추천**: 피부 타입 질문(직접 응답) + 써 본 제품 성분 겹침 + 피하고 싶은 성분 | ✅ 후순위 | 6-16, M14. 얼굴 사진 분석 없음. 성분 데이터(D)가 먼저 필요 |
| F17 | 30분 뒤 색 보기 (틴트) | ⏭ MVP 다음 | 6-17, M15. 측정값 있는 셰이드만 |
| F18 | 겹쳐 바르기 (레이어링) | ⏭ MVP 다음 | 6-17, M16 |
| F19 | 반반 비교 | ⏭ MVP 다음 | 6-17, M17. 퍼스널컬러 진단 대신 |
| F20 | 내 립 서랍 + 바로 담기 | ⏭ MVP 다음 | 6-17, M18 |
| F21 | 가격 기능 (듀프 가격 차이, 판매처 가격) | ⏭ MVP 다음 | 6-17, M19 |
| F22 | 여행 쇼핑 플래너 | ⏭ MVP 다음 | 6-17, M20 |
| F23 | 구매 후 확인 + 지표 이벤트 | ⏭ MVP 다음 | 6-17, M21 |

### 2-1. 기능별 AI가 필요한 이유

| 기능 | 기술 | AI가 필요한 이유 | AI 없이 처리하는 부분 | 평가 트랙 |
|---|---|---|---|---|
| 얼굴 부위 인식 | CV, MediaPipe Face Landmarker | 매 프레임 얼굴 위치·윤곽 찾기는 규칙으로 불가 | — | A |
| 손 가림 감지 | MediaPipe Hand Landmarker | 손 위치 찾기는 규칙으로 불가 | 입술 영역과의 겹침 판정 | B |
| 메이크업 표현 | 3D 메시 + UV, 색 합성 | — (CV 결과 위의 그래픽 처리) | 전부 셰이더·수식 | A |
| 발색 혼합 모델 | 직접 학습한 작은 회귀 모델 | 피부·입술 색, 제품, 바르는 양이 섞인 발색이 단순 공식으로 오차가 클 때 데이터로 보정 | 초기에는 선형 혼합 공식 | B |
| 스타일 분석 | VLM, 구조화 출력 | 영상·이미지마다 다른 화장 과정을 사람이 정리할 수 없는 규모로 구조화 | 교차검증 투표, 색 계열 → HEX 팔레트 매핑 | C |
| 대화형 수정 | LLM 함수 호출, 대화 상태 관리 (+ STT) | 표현이 무한한 자연어를 정해진 명령으로 변환 | 명령 실행(색·진하기·길이 변경) | D |
| 상품 추천 | 콘텐츠 기반 → 이후 ML(LightGBM 등 랭킹 후보) | 초기엔 불필요. 사용 기록이 쌓이면 선호 학습. 학습에는 사용자-상품 반응(선택·저장·수락) 데이터가 있어야 하며, 피부·색 측정값만으로는 지도학습이 성립하지 않는다 | 초기 추천 전부(ΔE, 제형, 성분) | E |
| 유사 제품 추천 (F7-2) | 수식 | **불필요** — ΔE2000 + 제형 벌점 + 제휴 벌점. LLM은 조건(제형 방향, 가격대)만 정함 | 정렬 전부 | E |
| 색 계산·조명 보정·매칭·바르는 횟수 | 수식 | **불필요** — 결정적이고 설명 가능해야 함 | 전부 | B |

---

## 3. 기술 스택

저장소 `gyuniverse-hq/SKN34-Final-Project`(`develop`)의 현재 구성을 따른다. 저장소 규칙은 `AGENTS.md`가 우선한다(Expo SDK 57, Expo Go 테스트, `npx expo install`, `npm run check`, i18n, Git 규칙).

| 영역 | 선택 | 상태 | 라이선스 |
|---|---|---|---|
| 앱 | Expo SDK 57 + Expo Router, Expo Go로 테스트 | 기존 | MIT |
| AR 페이지 실행 | `react-native-webview`(Expo Go 포함)에 HTML 문자열을 `baseUrl: 'https://localhost/'`로 로드. 웹은 `iframe srcDoc` | 기존 | MIT |
| 카메라 권한 | `expo-camera` (권한 요청만, 프레임은 AR 페이지 안에서) | 기존 | MIT |
| 얼굴 추적 | `@mediapipe/tasks-vision` — AR 페이지가 CDN에서 고정 버전(`MEDIAPIPE_VERSION`)으로 로드 | 기존 | Apache 2.0 |
| 렌더링 | AR 페이지 안 WebGL 셰이더 (현재: 2D 마스크 + LAB 재채색). 3D 메시 + UV는 M3에서 추가 | 기존 + 확장 | — |
| 손·분할 | `@mediapipe/tasks-vision` HandLandmarker, ImageSegmenter(`selfie_multiclass_256x256`) — 같은 CDN 방식 | 신규 | Apache 2.0 |
| 색 계산 | `lib/color/` 자체 구현(sRGB EOTF, Lab D65, CIEDE2000). AR 페이지에도 같은 수식을 넣고 테스트로 결과를 맞춘다 | 신규 | — |
| 상태 | Zustand (`store/`) | 기존 | MIT |
| 저장 | AsyncStorage (`lib/storage.ts`의 `persistStorage`) — 보정값·설정·사용 기록. **AR 페이지 안에서는 저장하지 않는다** | 기존 | MIT |
| 서버 (F10, F11) | Expo Router API 라우트(`app/api/**/*+api.ts`) + 서버 전용 로직(`server/`), TypeScript | 기존 구조 | — |
| 레시피 추출 | Gemini API 영상·이미지 이해 + 구조화 출력. 키는 `.env`(서버 전용) | 신규 | 상용 API |
| 대화형 조정 | LLM API 함수 호출, `server/llm/` 어댑터로 모델 교체 가능. 로컬 Qwen2.5-7B는 별도 서비스가 필요하므로 11장 결정 후 | 신규 | 상용 API / Apache 2.0 |
| 다국어 | `lib/i18n` (en, ko, ja, zh). 새 문구는 네 사전에 모두 추가 | 기존 | — |
| 테스트 | Jest (`jest-expo`), `__tests__/` | 기존 | MIT |
| 평가·숙제 스크립트 | Python + colour-science + lpips + scikit-image — 앱 밖(`scripts/eval/`, `research/`) | 신규 | BSD |
| 음성 (F12) | 후순위. 방식은 11장 결정 | — | — |

---

## 4. 디렉터리 구조

기존 저장소 구조에 맞춘다. **[기존]** = 이미 있는 파일(수정), **[신규]** = 새로 만드는 파일. 경로 앞 `@/`는 저장소 루트(`tsconfig.json`의 paths).

```
AGENTS.md                      [기존] 저장소 규칙 (CLAUDE.md가 불러옴). 이 명세서 위치 한 줄 추가(사람이 PR로)
docs/
  AR_SPEC.md                   [신규] 이 명세서
app/                           화면 + API 라우트 (Expo Router)
  (tabs)/ar.tsx                [기존] AR 화면 — 보기 옵션(F6), 진하기↔횟수(F5), 조명 보정 진입(F2), 유사 추천 시트(F7-2), 대화 입력(F11)
  (tabs)/celeb.tsx             [기존] 룩 목록 — 레시피(Recipe) 기반 룩 표시(F10)
  (tabs)/my.tsx                [기존] 마이 — 사용 기록 동의·내보내기·지우기(F15), 디버그 메뉴(렌더 저장, FPS)
  look/[id].tsx                [기존] 룩 상세 — 레시피 단계 표시
  product/[id].tsx             [기존] 제품 상세 — 측정 상태 배지(1-8), 유사 제품 진입
  follow-along.tsx             [신규] 따라 바르기 (F8)
  skin-profile.tsx             [신규] 피부 타입 질문·써 본 제품·피하고 싶은 성분 (F16)
  ingredients.tsx              [기존] "좋았던 성분으로 스킨케어 찾기" — 동작 연결 (F16)
  api/
    skincare/recommend+api.ts  [신규] F16 기초 추천 계산 (성분 데이터는 서버 전용)
    recipe/extract+api.ts      [신규] F10 참고 이미지 → Recipe (이미지는 메모리 처리 후 폐기)
    dialog+api.ts              [신규] F11 발화 + 대화 상태 요약 → Command[]
    products+api.ts 등         [기존] 제품·룩·매장·판매처 가격·YouTube 검색
components/
  ar/ArFaceView.tsx            [기존] WebView 호스트 — BridgeMessage 검증 추가
  ar/ArFaceView.web.tsx        [기존] 웹(iframe) 호스트 — 같은 프로토콜
  ar/faceTrackerHtml.ts        [기존] AR 페이지 HTML 문자열 (추적·렌더·보정·측정). 6-0 참고
  ar/bridgeProtocol.ts         [신규] BridgeMessage 타입·검증·길이 상한 (호스트 쪽)
  ar/SwatchFallback.tsx        [기존] AR을 못 쓸 때 대체 화면
  reco/SimilarList.tsx         [신규] 유사 추천 묶음별 목록 (F7-2)
  reco/MeasureBadge.tsx        [신규] measured / user_verified / estimated / placeholder 표시
  dialog/DialogBar.tsx         [신규] 텍스트 입력 + 되묻기 표시 (F11)
constants/
  skinQuestions.ts             [신규] 피부 타입 질문 목록 (F16)
  textureKeywords.ts textureRules.ts  [신규] 제형 판정 키워드 사전·설문 기준 (6-15-2)
  similarity.ts                [신규] 제형 축 순서(TEXTURE_AXIS), 제형 벌점표(7×7), 묶음 기준, unavailablePenalty, _changelog (6-9-2)
lib/
  color/srgb.ts lab.ts deltaE.ts layering.ts   [신규] 색 계산 (6-5, 6-7)
  reco/match.ts                [신규] 목표 룩 기준 매칭 (F7)
  reco/similar.ts              [신규] 지금 AR 색 기준 유사 추천 (F7-2)
  reco/reasonPhrases.ts        [신규] ΔL·Δh·제형 → i18n 문장 키
  reco/skincare.ts             [신규] 기초 추천 정렬·근거 문장 (F16)
  dialog/commands.ts           [신규] Command 실행 (수식)
  dialog/dialogState.ts        [신규] 참조 해석 ("아까보다", "이거")
  events/eventLog.ts           [신규] 사용 기록 (F15)
  followAlong/guidance.ts      [신규] 따라 바르기 안내 규칙
  storage.ts                   [기존] STORAGE_KEYS에 calibration·userCalibration·events 추가
  queries.ts api.ts            [기존] 새 API 호출 추가
  i18n/en.ts ko.ts ja.ts zh.ts [기존] 새 문구 키를 네 사전 모두에
store/
  makeupStore.ts               [기존] 진하기·제품 선택. 보기 옵션·갈 곳 상태 추가
  calibrationStore.ts          [신규] 조명 보정·부위별 피부 Lab·사용자 보정 (persist)
  dialogStore.ts               [신규] DialogState (레시피 버전, 조건, 후보 목록)
  drawerStore.ts               [신규] 내 립 서랍 (기기 안, F20)
  skinProfileStore.ts          [신규] 피부 타입·써 본 제품·피하고 싶은 성분 (기기 안, F16)
  settingsStore.ts             [기존] 사용 기록 동의 플래그, 기기 성능 단계 기록 추가
server/
  env.ts                       [기존] GEMINI_API_KEY 등 서버 전용 키 추가
  ingredients/flags.ts         [신규] 성분 플래그 판정 (6-15)
  llm/adapter.ts gemini.ts     [신규] LLM·VLM 호출 어댑터 (모델 교체용)
  recipe/extract.ts vote.ts    [신규] F10 레시피 추출, 영상 교차검증 투표
  dialog/toCommands.ts         [신규] F11 함수 호출 스키마, 검증, 되묻기
  catalog.ts                   [기존] 제품을 불러올 때 measurements.json을 Shade에 합치고 성분 플래그를 붙임
  youtube.ts naver.ts cache.ts http.ts  [기존]
data/catalog/
  products.ts                  [기존] Product·Shade (수동 입력, 측정값 필드 추가, 5장)
  measurements.json            [신규] 측정 CSV에서 생성 (6-15). server/catalog.ts가 Shade에 합침
  looks.ts                     [기존] CelebLook (+ recipe)
  stores.ts                    [기존] 매장 (이번 범위 밖, 건드리지 않음)
data/ingredients/              [신규] 서버 전용 (앱 번들에 넣지 않음, 6-15)
  master.json restrictions.json  식약처 API에서 생성
  raw/<productId>.txt          공식몰 전성분을 사람이 옮겨 적은 원본
  products.json                정규화된 제품별 전성분
types/index.ts                 [기존] 공용 타입 확장 (5장)
__tests__/                     [기존] Jest 테스트
  faceTracker.test.ts          [기존] AR 페이지 스크립트 검사 (프레임 업로드·저장 금지)
  color.test.ts similar.test.ts bridge.test.ts dialog.test.ts events.test.ts  [신규]
scripts/data/                  [신규] Python 데이터 가져오기 스크립트 (6-15). 개발자 PC에서만 실행
  import_measurements.py import_mfds_ingredients.py import_mfds_restrictions.py
  normalize_ingredients.py import_monk.py import_reference.py
  extract_chip_color.py judge_texture.py   컬러칩 색 추출, 제형 판정 (6-15-2)
scripts/eval/                  [신규] Python 평가 스크립트 (트랙 A~E, 8장)
  reference/monk.json          Monk 10단계 Lab (평가 전용)
research/                      [신규] 숙제 실험 (8-A). 앱 코드에서 import 금지
  protocol/ hw02_cv_compare/ hw04_eval_methods/ reports/
  check_imports.py             비상업 모델이 앱 코드(app/ components/ lib/ server/ store/)에서 import되지 않는지 검사
  data/                        .gitignore 추가. 로컬에만 (얼굴 사진·측정 CSV)
    hw01_raw/ hw01_masks/ hw01_ppt/ track_a/ track_b/ measurements/ reference/
```

- 화면 밖 코드는 `app/`에 두지 않는다(Expo Router 규칙, `AGENTS.md`).
- `data/catalog/`는 앱이 쓰는 제품 데이터라 저장소에 올린다. 얼굴 사진·평가 데이터는 반드시 `research/data/`(저장소 제외)에 둔다. 두 폴더를 섞지 않는다.
- 로그인·멤버십·리워드·장바구니·체크아웃·매장·법률 화면(`login.tsx`, `membership.tsx`, `rewards.tsx`, `(tabs)/cart.tsx`, `checkout.tsx`, `lists/`, `legal/`, `saved.tsx`)은 이 명세서 범위 밖이다. 건드리지 않는다.

---

## 5. 데이터 타입

`types/index.ts`의 기존 타입을 **확장**한다. 기존 필드 이름은 바꾸지 않는다(다른 화면이 쓰고 있음).

```ts
// ---- 기존 타입 확장 (types/index.ts) ----
export type MeasureMethod = 'measured' | 'user_verified' | 'estimated' | 'placeholder';
export interface LabColor { L: number; a: number; b: number }   // D65 기준

// 제형은 기존 Texture 7종을 그대로 쓴다 (AR 페이지 TEXTURES와 같은 이름). 4종으로 묶지 않는다.
// Texture = 'matte' | 'velvet' | 'glossy' | 'satin' | 'sheer' | 'cream' | 'shimmer'

export interface Shade {
  id: string;
  name: string;
  hex: string;                 // 기존. 공식몰 참고치. 측정값이 있으면 labOnPaper가 우선
  // ---- 추가 ----
  labOnPaper?: LabColor;       // 종이(바탕) 위 1회 바름. 조명·카메라를 고정한 측정 환경에서 촬영 (6-15)
  labOnPaper3x?: LabColor;     // 3회 바름 (a1 역산용)
  a1?: number;                 // 1회 바를 때 덮는 정도 0~1
  labAfter30min?: LabColor;    // 틴트 등 시간 변화
  measureMethod: MeasureMethod;  // hex만 있으면 'estimated', 테스트용은 'placeholder'
  colorSource?: 'measured' | 'option_chip' | 'color_compare' | 'official_hex' | 'placeholder';  // 6-15-2 ①
  labEstimated?: LabColor;     // 컬러칩·색상비교 이미지에서 뽑은 추정 Lab
  colorSourceUrl?: string;     // 출처 주소 (이미지는 저장하지 않음)
  colorCheckedAt?: string;
  measuredAt?: string;
  measureDevice?: string;      // 측정 기종
  measureCount?: number;       // 같은 셰이드 측정 횟수 (6-15)
  textureOverride?: Texture;   // 같은 제품 안에서 이 셰이드만 제형이 다를 때 (예: 펄 셰이드만 shimmer)
  glossMeasured?: number;      // 측정한 광택 정도 0~1 (숙제 01, 6-15). 제조사 표기와 실제 광택 비교용
}

export interface Product {
  // 기존 필드 그대로: id, brand, name, nameKo, category, makeupZone, texture, priceKRW, volume,
  //                  shades, description, keyIngredients, tags, imageUrl, searchKeyword
  // ---- 추가 ----
  partner?: boolean;           // 제휴 여부. 없으면 false. 유사 추천에서 같은 묶음 안 순서에만 반영(1-14)
  priceCheckedAt?: string;     // priceKRW(참고 가격) 확인 날짜
  textureLabel?: string;       // 제조사 원래 표현 그대로 (예: "글로우", "벨벳", "블러")
  textureNote?: string;        // 7종 중 그것을 고른 근거 (예: "공식몰 설명 '촉촉한 광택' → glossy")
  textureSource?: 'measured' | 'team_panel' | 'name_keyword' | 'official_description'
                | 'review_summary' | 'review_survey' | 'default';   // 6-15-2 ②
  textureConfidence?: 'high' | 'medium' | 'low';
  sourceUrl?: string;          // 공식몰 확인 주소 (6-15)
  checkedAt?: string;          // 공식몰 확인 날짜
  ingredientFlags?: IngredientFlag[];  // API 응답에서만 채움 (서버가 계산)
  subCategory?: SkincareType;  // 기초 제품 세부 종류 (F16)
  skinTypeLabel?: string;      // 제조사 원래 표현 (예: "건성·민감성 피부용")
  skinTypes?: SkinType[];      // 사람이 매핑. 근거는 skinTypeNote
  skinTypeNote?: string;
}

export type SkinType = 'dry' | 'oily' | 'combination' | 'normal' | 'sensitive' | 'all';
export type SkincareType = 'cleanser' | 'toner' | 'essence' | 'serum' | 'lotion' | 'cream' | 'sunscreen' | 'mask' | 'other';
export interface SkinProfile {            // 기기 안에만 저장 (F16)
  skinType?: Exclude<SkinType, 'all'> | 'unknown';
  answers: Record<string, string>;        // 2단계 질문 답 (constants/skinQuestions.ts의 id)
  likedProductIds: string[];
  dislikedProductIds: string[];
  avoid: IngredientFlag[];                // 사용자가 확인한 것만
  updatedAt: number;
}

export type IngredientFlag =
  | 'titanium_dioxide' | 'iron_oxides' | 'tar_colorant' | 'menthol' | 'denatured_alcohol' | 'fragrance';
// 화면 문구는 사실만: "멘톨이 들어 있어요". 효과·느낌 단정 금지 ("화한 느낌", "착색 없음" 등)
}

// 기존 ZoneSetting { hex, intensity, texture } 는 AR 페이지로 보내는 값이다.
// hex는 shade.labOnPaper가 있으면 그것을 sRGB로 바꾼 값, 없으면 shade.hex. 이 변환 외에 색을 바꾸지 않는다(1-1).

export interface CelebLook {
  // 기존 필드 그대로 (title, inspiration, items, makeup, tutorialQuery ...)
  recipe?: Recipe;             // 추가: F10 레시피
}

// ---- 신규 ----
export interface LookStep {    // 룩 레시피의 목표 효과
  part: MakeupZone;            // MakeupZone: 'lip' | 'blush' | 'eyeshadow' | 'eyeliner' | 'mascara' | 'highlighter' | 'contour' (뒤 넷은 10-25 추가, MakeupState에서 선택 필드)
  hueMin: number; hueMax: number;
  deltaL: number;
  chroma: number;
  texture: Texture;            // 7종
  defaultIntensity: number;
}

export interface LightCalibration {
  lightRGBLinear: [number, number, number];   // 조명 색 (휘도 1 정규화)
  source: 'gray_world' | 'arkit' | 'arcore';   // MVP는 'gray_world'만. arkit·arcore는 6-6-2 도입 시
  confidence: 'high' | 'low';  // 배경이 충분하고 고르면 high
  lightDir?: [number, number, number];   // 주된 빛 방향 (얼굴 메시로 추정, 6-6-1 ②)
  lightIntensity?: number;
  cameraColorTempK?: number;   // 카메라가 알려 줄 때만 (6-6-1 ③)
  whiteBalanceLocked?: boolean;
  calibratedAt: number;
  refSkinLab: LabColor;
  skinLabByRegion: { forehead: LabColor; cheekL: LabColor; cheekR: LabColor; chin: LabColor; lipInner: LabColor; lipOuter: LabColor };
}

export interface UserProductCalibration {
  shadeId: string;
  labOffset: LabColor;         // 실제 - 예측
  a1User: number;
  samples: number;
  updatedAt: number;
}

export type ViewOption = 'current_light' | 'standard_light' | 'destination_light';
export type Destination = 'daylight' | 'office' | 'dinner' | 'photo';
export type DeviceTier = 'high' | 'mid' | 'low';
// 추적 상태기계(TRACKING/COASTING/FADING/LOST)는 AR 페이지 내부 상태다.
// 호스트에는 기존 ArStatus('loading'|'tracking'|'no-face'|'denied'|'unavailable')로만 알린다.

// ---- 레시피 (F10) ----
export type Part = 'base' | 'lip' | 'eyeliner' | 'eyeshadow' | 'blush' | 'brow';
export interface RecipeStep {
  order: number;
  part: Part;
  technique: string;           // 고정 선택지에서만
  colorFamily: string;         // 고정 팔레트 이름
  intensity: number;
  texture: Texture;            // 7종
  geometry?: { length?: number; angle?: number; thickness?: number };
  optional: boolean;
  confidence: number;
  sourceRefs?: { videoId: string; startSec: number }[];
}
export interface Recipe {
  recipeId: string;
  conceptName: string;         // 화면 표시용. 인물 이름 금지
  source: 'youtube_vote' | 'user_image';
  steps: RecipeStep[];
  createdAt: string;
}

// ---- 대화 상태 (F11) ----
export type Command =
  | { op: 'set_intensity'; part: Part; value?: number; delta?: 'up' | 'down'; step?: number }
  | { op: 'set_geometry'; part: 'eyeliner'; field: 'length' | 'angle' | 'thickness'; delta: 'up' | 'down' }
  | { op: 'shift_tone'; part: Part; dir: 'warmer' | 'cooler' | 'deeper' | 'lighter' }
  | { op: 'match_skin_tone'; part: Part }
  | { op: 'remove_step'; part: Part }
  | { op: 'set_destination'; value: Destination }
  | { op: 'undo'; steps?: number }
  | { op: 'explain' }
  | { op: 'find_similar'; part: Part;
      textureShift?: 'more_matte' | 'more_glossy';   // 제형 축에서 한 칸 이동 (6-9-2)
      texture?: Texture;                             // "글로시로"처럼 직접 말한 경우
      priceMin?: number; priceMax?: number;
      priceDir?: 'cheaper' | 'pricier';
      excludeShimmer?: boolean;                      // "반짝이는 건 빼줘"
      reset?: boolean }
  | { op: 'select_candidate'; index: number };

export interface SimilarFilter {
  texture?: Texture; priceMin?: number; priceMax?: number; excludeShimmer?: boolean;
}
export interface DialogTurn {
  utterance: string;
  commands: Command[];
  recipeVersionBefore: number;
  recipeVersionAfter: number;
  at: number;
}
export interface DialogState {
  sessionId: string;
  recipeHistory: Recipe[];
  turns: DialogTurn[];
  focusPart?: Part;
  similarFilter?: SimilarFilter;
  candidateList?: string[];    // 마지막으로 보여 준 유사 추천 shadeId 순서
}

// ---- 호스트 ↔ AR 페이지 메시지 (F0, components/ar/bridgeProtocol.ts) ----
// 기존 프로토콜은 유지하고 메시지만 추가한다. 숫자·상태만, 이미지·프레임 금지.
// host → page (기존): { type: 'makeup', makeup: MakeupState } | { type: 'compare', value: boolean }
// page → host (기존): { type: 'hello' } | { type: 'status', status: ArStatus, detail?: string }
export type HostToPage =
  | { type: 'makeup'; makeup: MakeupState }                       // 기존
  | { type: 'compare'; value: boolean }                           // 기존
  | { type: 'view'; value: ViewOption; destination?: Destination }
  | { type: 'calibration'; value: LightCalibration | null }       // 저장된 보정값 전달
  | { type: 'calibrate_start' }                                   // 조명 다시 추정
  | { type: 'user_calibration'; value: UserProductCalibration[] }
  | { type: 'measure_lip'; enabled: boolean };                    // 따라 바르기
export type PageToHost =
  | { type: 'hello' }                                             // 기존
  | { type: 'status'; status: ArStatus; detail?: string }         // 기존
  | { type: 'ar_ready'; tier: DeviceTier; gpu: boolean; webgl2: boolean }
  | { type: 'fps'; value: number }
  | { type: 'current_look'; zone: MakeupZone; intensity: number; labStandard: LabColor }
  | { type: 'calibration_result'; value: LightCalibration }
  | { type: 'light_changed'; deltaE: number }
  | { type: 'lip_measured'; lab: LabColor; stable: boolean };

// ---- 사용 기록 (F15) : 동의 시에만, 숫자·ID만 ----
export type AppEvent =
  | { kind: 'shade_applied'; productId: string; shadeId: string; at: number }
  | { kind: 'similar_shown'; baseShadeId: string; shadeIds: string[]; filter?: SimilarFilter; at: number }
  | { kind: 'similar_selected'; shadeId: string; rank: number; at: number }
  | { kind: 'look_saved'; lookId: string; at: number }
  | { kind: 'seller_link_opened'; productId: string; at: number }
  | { kind: 'skincare_shown'; productIds: string[]; at: number }       // 피부 타입 값은 넣지 않음
  | { kind: 'skincare_selected'; productId: string; rank: number; at: number }
  | { kind: 'added_to_cart'; productId: string; shadeId?: string; from: 'ar' | 'similar' | 'skincare'; at: number }
  | { kind: 'list_created'; itemCount: number; at: number }
  | { kind: 'expectation_rating'; shadeId: string; rating: 1 | 2 | 3 | 4 | 5; at: number }
  | { kind: 'drawer_added'; shadeId: string; at: number }
  | { kind: 'layer_tried'; baseShadeId: string; topShadeId: string; at: number }
  | { kind: 'split_compared'; leftShadeId: string; rightShadeId: string; at: number };
```

---

## 6. 모듈 명세

### 6-0. Expo 앱 + AR 페이지 연결 (F0)

**지금 저장소의 구조 (그대로 쓴다):** Expo Go는 앱에 들어 있는 모듈만 쓸 수 있어서 네이티브 MediaPipe를 쓸 수 없다. 그래서 AR은 HTML 문자열(`components/ar/faceTrackerHtml.ts`)로 만들고, 앱이 WebView에 띄운다.
- 폰: `ArFaceView.tsx`가 `react-native-webview`에 `source={{ html: FACE_TRACKER_HTML, baseUrl: 'https://localhost/' }}`로 로드한다. `baseUrl`이 HTTPS라서 카메라를 열 수 있고, **별도 HTTPS 서버나 터널이 필요 없다.**
- 웹: `ArFaceView.web.tsx`가 같은 HTML을 `iframe srcDoc`으로 띄운다. 노트북 브라우저에서 바로 시험할 수 있다(`npx expo start` 후 `w`).
- WebView 설정(이미 적용됨): `mediaCapturePermissionGrantType="grant"`, `allowsInlineMediaPlayback`, `mediaPlaybackRequiresUserAction={false}`, `originWhitelist={['*']}`.
- 카메라 권한은 `app/(tabs)/ar.tsx`의 동의 화면 → expo-camera 권한 요청 순서로 이미 처리된다. 거부되면 WebView를 열지 않는다.

**앱(호스트)이 하는 일:** 화면, 제품 선택, 진하기, 보기 옵션, 서버 호출(`lib/api.ts` → `app/api/`), 저장(`store/` + AsyncStorage), 추천 계산(`lib/reco/`), 대화 명령 실행(`lib/dialog/`).
**AR 페이지가 하는 일:** 카메라 영상, 얼굴·손 추적, 렌더링, 조명 보정 측정, 입술 색 측정(6-1 ~ 6-11).

**AR 페이지 코드 관리 (11-1 결정 사항)**
- 지금은 페이지 스크립트가 템플릿 문자열 안에 있어서 타입체크·린트가 보지 못한다(`AGENTS.md`). 기능이 커지면(3D 메시, 보정, 손 추적) 한 문자열로 관리하기 어렵다.
- 기본안: 기능을 추가하는 동안에는 기존 방식(한 파일)을 유지하되, 페이지 스크립트를 수정할 때마다 `npm test`(`__tests__/faceTracker.test.ts`)를 돌린다. 파일이 지나치게 커지면 분리 방식을 팀과 정한 뒤 바꾼다(원본 폴더 → 빌드 스크립트가 `faceTrackerHtml.ts` 생성 등). 에이전트가 임의로 구조를 바꾸지 않는다.
- 외부 라이브러리(예: Three.js)를 페이지에 쓸 경우 MediaPipe처럼 **CDN 고정 버전**으로 불러오고, 버전 상수를 `faceTrackerHtml.ts`에 둔다. 새 라이브러리는 이름·버전·라이선스를 먼저 보고한다.

**브리지 규칙 (1-4)**
- 메시지는 5장 `HostToPage` / `PageToHost`만 쓴다. 기존 메시지(`makeup`, `compare`, `hello`, `status`)는 이름과 형식을 바꾸지 않는다.
- 호스트 → 페이지는 기존처럼 `injectJavaScript`로 `window.__kb.receive(...)`를 부르고, 페이지 → 호스트는 `window.ReactNativeWebView.postMessage`(웹은 `parent.postMessage`)를 쓴다.
- `components/ar/bridgeProtocol.ts`에서 받은 메시지를 검증한다. 형식이 틀리면 버리고(개발 모드에서만 경고), 문자열 길이 상한(초기 8KB)을 넘는 메시지는 버린다.
- 이미지, 프레임, base64, Blob URL은 메시지에 넣지 않는다.
- **AR 페이지 안에서는 네트워크 호출과 저장을 하지 않는다.** 기존 테스트가 페이지 스크립트에 `fetch(`, `XMLHttpRequest`, `localStorage`, `indexedDB`, `toDataURL`, `toBlob`이 없는지 검사한다. 이 테스트는 지우거나 완화하지 않는다.
  - 저장할 값(조명 보정, 사용자 보정)은 숫자로 호스트에 보내고, 호스트가 `store/calibrationStore.ts`(AsyncStorage)에 저장한다. 앱을 다시 켜면 호스트가 `calibration`·`user_calibration` 메시지로 다시 넣어 준다.
  - 예외: MediaPipe 모듈·모델 파일을 CDN에서 불러오는 것(기존 `import(...)`, `modelAssetPath`)은 그대로 둔다.
  - 디버그용 "렌더 결과 저장"(평가용, 8장)은 페이지가 직접 저장하지 않는다. 방법은 M0-E에서 정하고 개발 모드에서만 켠다(11-1).
- MediaPipe GPU 실행이 실패하면 CPU로 바꾸고 `ar_ready.gpu=false`로 알린 뒤 기기 성능 단계를 `low`에서 시작한다(6-11). 현재 페이지에 있는 WebGL → 2D 대체 렌더러는 유지한다.

**서버 호출**
- 앱은 기존 `lib/api.ts`로 같은 개발 서버의 API 라우트(`app/api/...`)를 부른다. 별도 서버 주소 설정이 필요 없다.
- LLM·VLM 키(`GEMINI_API_KEY` 등)는 `.env`에 두고 `server/env.ts`에서만 읽는다. `EXPO_PUBLIC_` 접두어를 붙이지 않는다. `.env.example`에 키 이름을 추가한다.

**로컬 개발 실행 방법 (README에 이미 있음)**
```bash
npm install
cp .env.example .env      # 키 입력 (없어도 실행됨: 해당 기능만 비활성)
npx expo start -c
```
- 폰: PC와 같은 Wi-Fi에서 QR 스캔. iOS Expo Go는 PC와 같은 Expo 계정으로 로그인 필요. 같은 Wi-Fi가 아니면 `npx expo start --tunnel`.
- 웹: 터미널에서 `w`.
- Windows는 처음 실행할 때 방화벽 창에서 "허용".
- Expo Go 앱은 SDK 57과 맞는 버전(57.x)을 쓴다.
- 커밋 전 `npm run check`(타입체크 + 린트 + 테스트).

### 6-1. 카메라 (F1)
- `getUserMedia({ video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } } })`
- `track.getSettings()`로 실제 해상도·프레임 속도를 읽어 렌더 해상도에 반영.
- 가능하면 `whiteBalanceMode`, `exposureMode`를 `"manual"`로 요청하되 실패해도 계속 진행(지원 기기 제한).
- 프레임 루프는 `requestVideoFrameCallback` 우선, 없으면 `requestAnimationFrame`.
- 이 절부터 6-11까지는 **AR 페이지(`components/ar/faceTrackerHtml.ts`) 안의 코드**다. 기존 페이지의 `TUNING`, `TEXTURES`, 입술·눈 인덱스, One Euro, WebGL → 2D 대체 렌더러를 먼저 읽고, 같은 역할은 고쳐 쓴다(새로 만들지 않음).
- 기존 셰이더는 WebGL1(`getContext('webgl')`)이다. 6-5의 예시는 WebGL2 문법(`texture()`)이므로, WebGL2가 없으면 WebGL1 문법(`texture2D`)으로 바꿔 쓴다.

### 6-2. 얼굴 추적 (F1)
- `FaceLandmarker.createFromOptions`: `runningMode: "VIDEO"`, `numFaces: 1`, `delegate: "GPU"`, `outputFacialTransformationMatrixes: true`.
- 매 프레임 `detectForVideo(video, timestampMs)`.
- 입술·윤곽 인덱스는 **직접 하드코딩하지 말고** `FaceLandmarker.FACE_LANDMARKS_LIPS` 등 라이브러리 상수에서 가져온다.
- 정점마다 One Euro Filter 적용(기본값: `minCutoff=1.0, beta=0.007, dCutoff=1.0`, 튜닝 가능하게 설정으로 노출).
  - **기준점은 거르지 않는다(10-25).** 정점마다 기준점(입 근처는 입술 점 평균, 그 밖은 얼굴 전체 평균, 거리로 부드럽게 섞음)은 필터 없이 그대로 쓰고, 기준점에서의 오프셋에만 One Euro를 건다. 고개를 흔들어도 같은 프레임에 따라온다. 30fps 모의: 2Hz ±60px 흔들기 최대 오차 20.8px → 2.2px, 얼굴보다 입이 더 움직이는 돌리기 27.3px → 2.2px. 현재 값 `smoothMinCutoff 1.5, smoothBeta 25, smoothDCutoff 2.0`(정규화 좌표).

### 6-3. 추적 끊김 대응 (F4)
상태기계 `trackingState.ts`:

| 상태 | 진입 조건 | 동작 |
|---|---|---|
| TRACKING | 얼굴 검출됨 | 정상 렌더, 화장 알파 1 |
| COASTING | 검출 실패 후 0~300ms | 마지막 정점 + 마지막 속도로 외삽, 알파 1 |
| FADING | 300~600ms | 마지막 위치 고정, 알파 1→0 선형 감소 |
| LOST | 600ms 초과 | 화장 숨김 |
| (복귀) | LOST/FADING 중 재검출 | 5프레임 동안 이전 위치→새 위치 보간, 알파 0→1 |

- 시간 상수는 설정값으로 노출.
- 고개 각도(변환 행렬에서 yaw 추출)가 **45°를 넘으면** "반측면까지 돌려 보세요" 안내 표시. 80° 이상은 모델 한계.

### 6-4. 3D 메시 + UV 텍스처 렌더링 (F3)
- MediaPipe 표준 얼굴 모델(`canonical_face_model.obj`)에서 **정점 468개의 UV**와 **삼각형 인덱스**를 뽑아 상수 배열로 만든다(스크립트 `scripts/buildFaceUV.ts`, 결과는 `components/ar/faceUV.ts`). AR 페이지는 파일을 불러올 수 없으므로(6-0) 이 배열을 HTML 문자열에 넣는다. 원본 obj 파일은 저장소에 두고 출처·라이선스(Apache 2.0)를 주석에 적는다. UV의 V 뒤집기는 데이터와 텍스처 중 **한쪽만** 적용.
- 정점 위치는 매 프레임 랜드마크 468개로 갱신(홍채 10개는 메시에서 제외). 비디오와 같은 정사영 카메라 공간에 배치하고 `z`는 깊이 테스트에 사용.
- 메시에는 입 안쪽·눈이 구멍으로 비어 있어야 한다(치아·눈 칠해짐 방지). 확인 테스트 필수.
- `uvPainter.ts`: 1024×1024 캔버스에 부위별 마스크를 그린다.
  - 립: 바깥 입술 다각형 − 안쪽 입술 다각형, 경계 페더링(가우시안 2~4px).
  - 텍스처 RGBA = (제품 선형색, 마스크×진하기). **레시피·진하기·제품이 바뀔 때만 다시 그림.**
- `scene.ts` 렌더 순서:
  1. 전체 화면 비디오 평면
  2. 얼굴 메시 깊이 기록 (가림막)
  3. 얼굴 메시 + `makeupShader` (깊이 테스트 on, 뒷면 컬링)

### 6-5. 색 계산 (F2, F5, F7 공통)
- sRGB↔선형은 **정식 sRGB EOTF**(구간식) 사용. 2.2 근사 금지.
- Lab 변환은 D65 기준.
- 셰이더 핵심:

```glsl
// 입력: uCamera(비디오 텍스처), uMakeupUV(화장 텍스처), uLightColor(선형), uLipMeanLum, uAlphaGlobal
vec3 cam      = srgbToLinear(texture(uCamera, screenUV).rgb);
vec4 mk       = texture(uMakeupUV, vUv);              // rgb=제품 선형색, a=마스크×진하기
float lum     = dot(cam, vec3(0.2126, 0.7152, 0.0722));
float shading = clamp(lum / uLipMeanLum, 0.0, 2.0);   // 명암 유지
vec3 product  = mk.rgb * uLightColor * shading;       // 지금 조명 곱하기
float clipped = smoothstep(0.92, 1.0, max(cam.r, max(cam.g, cam.b)));
float alpha   = mk.a * uAlphaGlobal * (1.0 - clipped);// 하이라이트 날아간 곳은 덜 칠함
vec3 outLin   = mix(cam, product, alpha);
outColor      = vec4(linearToSrgb(addNoise(outLin)), 1.0); // 카메라 노이즈 맞추기
```

- `uLipMeanLum`은 CPU에서 입술 영역 픽셀(하이라이트·그림자 제외 중앙값)로 0.5초마다 갱신, 이동 평균.
- 제형은 `shade.textureOverride ?? product.texture`로 정한다.
- **쉬머 립:** 지금 AR 페이지는 반짝이(`shimmerStrength`)를 눈 섀도에만 적용한다. `shimmer` 립에도 반짝이 처리를 추가한다(입술 마스크 안, 진하기에 비례).
- 제형: 기존 AR 페이지의 `TEXTURES`(7종별 gloss·matte 값)를 그대로 쓴다. `glossy`·`sheer`는 원래 밝은 부분을 따라 반사광 가산(`sheer`는 진하기도 낮춤, 기존 `sheerFactor`), `matte`·`velvet`은 반사광 감쇠, `shimmer`는 노이즈 기반 반짝임(F10 이후 고도화). 7종 값은 실기기 튜닝 대상(`TUNING`).

### 6-5-3. 입술 사실감 — "실제로 바른 것처럼" (F3)

입술에 올린 색은 스티커가 아니라 직접 바른 것처럼 보여야 한다. 입술 전체가 같은 밝기의 불투명 면이면 실패다. 고른 색이 주름, 윗입술 그늘, 아랫입술 볼륨을 따라가고 제형에 맞는 윤기가 있어야 한다. 색 값 자체는 바꾸지 않는다. 숫자만 조금 바꿔 화면이 그대로면 고친 것으로 치지 않는다.

입술이 실제로 바른 것처럼 보이려면 색·명암·광택·조명·경계·카메라 질감·안정성이 모두 맞아야 한다. 색은 6-7·6-15, 명암·광택은 6-5, 조명은 6-6, 안정성은 6-2~6-4가 맡는다. 이 절은 **경계와 카메라 질감**, 그리고 이를 확인하는 평가를 정한다.

**구현됨** (`components/ar/faceTrackerHtml.ts`, 값은 `TUNING`, 실기기 확인 전)

| 디테일 | 동작 | 기준값 |
|---|---|---|
| 바깥 경계 부드럽게 | UV 마스크 경계를 흐림 처리 | `lipFeatherPx: 3` |
| ~~안쪽 입술 그라데이션~~ | **제거(10-27)**. 안쪽 입술선으로 갈수록 덮는 정도를 낮추던 농도 그라데이션. 풀립은 안쪽까지 같은 진하기 | `innerFadeStrength: 0` |
| 입술 윤곽(화면 공간) | 매 프레임 얼굴 점(One Euro)으로 바깥 입술선을 **화면에** 곡선으로 그림. 입꼬리(61·291)는 접선 0으로 뾰족하게, 큐피드 활(37·0·267)과 입꼬리는 고정하고 나머지는 Taubin 평활(줄어들지 않음). 입을 벌리면 안쪽 곡선이 구멍. 카메라 흐림만큼 경계를 부드럽게. UV 스플라인은 메시 삼각형마다 휘어 꺾임·부리 모양 입꼬리가 생겼음(10-25 클로즈업) | `lipOutlinePx: 512`, `lipOutlineSmooth: 0.5` |
| 카메라 노이즈·흐림 | 층 쌓기 방식이라 카메라 픽셀의 노이즈와 흐림이 결과에 그대로 남음(인위적 노이즈를 따로 넣지 않음). 노이즈는 측정만 해서 HUD에 표시 | `grainMax: 0.2`(측정 상한) |
| 입꼬리까지 칠하기 | 실제 립스틱은 입꼬리 끝까지 닿는다(10-25 참고 사진). 입꼬리(61, 291) 주변 원형 감쇠는 끝점에만 약하게, 입술 마스크와 경계 띠에 함께 곱함 | `cornerFadeSize: 0.06`(입 너비 대비 반경), `cornerFadeStrength: 0.1` |
| 입술 안은 끝까지 진하게 | UV 마스크는 '어디가 입술인가'만 정하고 덮는 양이 아니다. 마스크 × 1.6(1에서 자름)으로 부드러운 경계·얇은 입꼬리 쐐기·안쪽 페이드가 반만 칠해지지 않게 함. 경계 다듬기는 모델 입술을 최대 20%만 깎음(그늘진 가장자리가 옅어지던 문제) | `lipFill: 1.6`, `0.8 + 0.2 * max(t, onHl)` |
| 선명도(흐림) 맞추기 | 볼 영역 잔차(5×5 평균과의 차)의 이웃 픽셀 상관으로 카메라 흐림 폭을 잼(0.5초 이동 평균). 그 폭으로 ① 다시 넣는 노이즈를 같은 크기의 알갱이(value noise)로 만들고 고역 세기를 보정, ② 마스크를 mip bias로 같은 만큼 흐리게 읽음 | `blurMax: 4`. HUD에 `blur` 표시 |
| 입술 평균 밝기 | 바깥·안쪽 입술선 사이 점(입꼬리 61·291 제외)의 trimmed mean. 메시 정점은 입을 벌리면 입 안을 집어 명암이 평평해짐 | `sampleScene` 입술 본체 샘플 |
| 투명 코팅 윤기 | 실제 메시 법선과 추정 빛 방향으로 GGX 반사를 더함. 빛 방향 신뢰도가 낮아도 완전히 끄지 않음. 입술 융기의 잔광택(glint)도 더함. 둘 다 덮는 정도만큼만 | `specFill: 0.7`, `lipSpecMax: 0.25` |
| 제형별 주름·하이라이트 | 매트는 주름을 조금 메우고 카메라 하이라이트를 줄임. 글로시는 유지. **카메라 하이라이트는 최대 1배까지만**(키워서 다시 더하면 윗입술에 흰 띠) | `MATERIALS.*.detail`, `hlKeep: [0.15, 1.0]` |
| **층 쌓기 (핵심)** | 카메라 = 조명 × 명암 × 맨입술 색. 맨입술 색은 0.5초마다 재고, 색 방향은 픽셀 주변 5점 평균에서. 덮는 정도만큼 맨입술을 제품 색 쪽으로 먼저 섞고(모든 제형), **비쳐 보이는 몫만** 염료의 **색조로만** 물들임(밝기는 위 섞기에 이미 들어 있음, 10-26: 제품 색 전체로 거르면 두 번 어두워졌다. 시어 누드가 빨간 입술을 더 진한 빨강으로 만들던 문제 L* 43 < 47, 시어 코랄이 옅은 붉은 입술을 L* 50 → 41로 만들던 문제). 덮인 몫은 카메라 **밝기만** 가져오고(조명·명암·주름), 덮이지 않은 몫만 카메라 색을 채널별로 유지(채널별 비율이 카메라 색 노이즈를 키워 노랑·초록 반점) | `paperWhite: 0.85`, `ratioMax: 4` |
| 추정 색 밝기 상한 | 덮이지 않고 비쳐 보이는 몫에만 적용(투명도 × (1 − 덮는 정도)). 덮인 안료는 입술을 밝게 할 수 있음 | `lumGainMax: 1.15` |
| 불투명 제형의 맨입술 얼룩 | 덮인 몫에서 **큰 규모의 밝기 차이만** 줄임(입술 두께 비율 반경 8점, 입술 픽셀만의 평균). 주름 같은 미세 결은 그대로(전체를 누르면 평평한 셀카에서 매끈한 색 면). 밝은 색이 흰색으로 날아가지 않게 최고 채널에 부드러운 무릎 | `opaqueShadeGamma: 0.6`, `lowReach: 0.35`, 무릎 0.7 |
| 하이라이트 분리 범위 | 카메라 하이라이트 분리는 입술 안쪽(core)에서만, 그리고 진짜 반사광만: 채도가 낮고 ① 주변 3px 평균보다 튀는 좁은 반사(주름·굴곡, 모든 제형에서 표면 결로 유지) 또는 ② 입술 평균의 2.2배를 넘는 넓은 반사(맨입술의 젖은 광택, 매끈한 제형일수록만 유지·매트는 덮음). 넓게 밝은(옅은) 아랫입술은 확산 명암으로 색 아래에 남김. 10-23 회색 테두리, 10-25 아랫입술 흰 막 문제 | `min(hlCap, max(hlPeak, hlWide × smoothT)) × core`, `hlLocal: 1.15`, `hlSat: [0.3, 0.55]`, `hlBlown: 2.2` |
| 반사광도 입술 | 반사광은 흰색이라 붉기로는 피부처럼 보이지만 입술이다. 모델 입술 안에서는 칠할 영역을 깎지 않고(경계 다듬기·A2 공통), 경계 광선도 반사광에서 멈추지 않는다. 모델 입술 밖(번들거리는 피부)에서는 영역을 넓히지 않는다. 10-25 실기기: 빛 받은 부분이 칠해지지 않음 | `onHl`, `isReflection` |
| ~~붉기로 경계 넓히기/깎기, A2 측정 윤곽~~ | **제거(10-25)**. 256px UV 판정이 클로즈업에서 10배 확대돼 입술선을 따라 혹이 생김. A2는 실제 얼굴 200장에서 얼굴 점보다 나빴음(IoU 0.703 vs 0.736). 광선 측정(`measureLipEdge`)은 HUD 진단용으로만 남김 | — |
| 다문 입술 사이 | 입 구멍 삼각형은 항상 그리고, 화면 윤곽이 결정: 다문 입(안쪽 틈 / 입 너비 < 기준)은 틈까지 칠하고, 벌린 입은 매끈한 안쪽 곡선까지만(치아 안 칠함) | `mouthClosedGap: 0.06` |
| 입술 형태(볼륨·윤기) | **10-25 사용자 요청으로 추가**("직접 바른 느낌, 제형 특성대로, 지금 조명에서"). 그 사람의 화면 윤곽에서 윗·아랫입술을 따로(다문 입은 안쪽 선에서 나눔) 흐린 형태 장을 만들고, 그 기울기로 입술마다 둥근 법선을 만든다(템플릿·그린 주름 아님). 위아래 방향은 입 전체 평균 방향(메시 법선이 아랫입술을 20~40° 위로, 윗입술을 60° 아래로 과하게 기울임), 좌우는 메시(치열 따라 감김, 옆얼굴에서 가까운 쪽이 카메라를 향함). ① 볼륨: 추정 빛 방향의 Lambert ② 윤기: 광원 자체의 또렷한 반사 + 주변 번짐 두 로브. 색은 투명 코팅(글로시)만 빛 색, 안료 윤기(새틴·크림)는 그 제품 색이 밝아진 값(매끈함³으로 섞음)(GGX 모양, 방 조명 크기만큼 넓힘), 추정 빛과 항상 있는 정면 광원(화면·앞쪽 방) 중 큰 쪽, 세기 = 제형 상한 × 피부 밝기(장면 노출). 매트는 거의 없음, 새틴은 부드러운 번짐, 글로시는 아랫입술 가운데 위쪽·윗입술 능선에 흰 반사 | `lipForm: true`, `formReach: 0.45`, `formTilt: 1.0`, `lipVolume: 0.6`, `glossMax: [0.04, 0.85]`(매끈함³), `glossGain: 3`, `frontGloss: 0.6`, `lightSize: [0.35, 0.6]`, `wideGloss: 0.3` |
| 벌린 입 안쪽 입술 | 얼굴 점 안쪽 선은 젖은 안쪽 입술보다 입 바깥쪽에 있음(LaPa 벌린 입 1,132장: 실제 입술의 13%가 안쪽 선 안). 안쪽 선을 입 안으로 옮김, 벌린 정도에 따라 | `innerInset: [0.05, 0.2]` (gap/너비 0.1 이하 → 0.05, 0.5 이상 → 0.2). 살짝 벌린 입에 0.15를 주면 폰 크기 200장 렌더에서 치아까지 칠해짐(IoU 0.624 → 0.615) |
| 화면 밖 얼굴 점 | 클로즈업에서 프레임 밖 정점은 가장자리 픽셀을 읽어 빛 방향·피부 밝기를 왜곡함 → 조명 추정에서 제외 | `inFrame` |
| 입술선 밖 피부의 흰 테 | 윤곽 가장자리에서 피부(붉기 낮음) 위에 칠한 불투명 색은 피부가 밝은 만큼 밝아져 흰 테가 됨 → 그 픽셀은 입술 평균 밝기를 바탕으로 | `skinW`, `uRefine`이 켜질 때만 |
| ~~UV 그라데이션~~ | **제거(10-25)**: 윗입술 어둡게·아랫입술 가운데 밝게를 빛과 상관없이 UV 위치로 주던 것. 명암은 카메라와 추정 빛의 입술 형태(Lambert)만 | — |
| 고르지 않은 도포 | 매트는 주름 골에 조금 더 쌓이고, 글로시는 융기에서 얇아짐(3px 주변 밝기 대비) | `creaseCover: 0.15` |
| 넓은 코팅 윤기 | 거친 메시 법선으로는 좁은 GGX 반사가 잘 안 맺혀 글로시가 매트처럼 보임(10-23 실기기). 메시 법선과 빛 방향으로 넓은 윤기를 (1−거칠기)²만큼 더함 | `lipSheen: 0.25` |
| 평평한 셀카 윤기 | 카메라에 반사광이 없으면 `keepHl`이 0이라 글로시가 매트처럼 보임(10-25). **형태 하이라이트**만 (1−거칠기)²만큼 키움. YouCam처럼 입술 UV에 흰 점을 심지 않음. 카메라에 반사가 있으면 배율 ≈ 1 | `glossFlat: 1.2` |

헤드리스 확인(10-22, 층 쌓기 적용 후, 옅은 윗입술·위에서 오는 조명·세로 주름을 그린 가짜 얼굴): 윗/아랫입술 밝기비 카메라 0.84 → 0.79~0.81(이전 고정 모양 0.59~0.75), 주름 편차 카메라 6.2 → 4.4~5.3(이전 레드 매트 13.4, 그린 주름), 색상각은 제품과 일치, 입술 밖 픽셀 불변. 윗입술이 피부만큼 붉지 않아도 칠해짐.

이전 헤드리스 확인(10-22, MediaPipe 예제 인물 사진을 가짜 카메라로 사용): 입꼬리 부근 칠해짐이 감쇠를 끈 경우의 0.80~0.90배(입술 중앙은 실행 간 오차 범위). 흐림 측정은 선명한 영상 1.29, 반경 2px 가우시안 흐림 영상 4.00(상한). 흐린 영상에서 화장 경계 폭 6px, 카메라 입술 경계 4~6px로 화장 쪽이 더 선명하지 않음(해상도가 낮아 대략적인 값).

**추가할 것**

| 디테일 | 내용 | 완료 기준 |
|---|---|---|
| 채도 과다 확인 | 가상 쪽이 실제보다 밝고 선명해 보이는 문제를 잡는다. 트랙 B ②③에서 ΔE2000과 함께 **채도 차이 ΔC\*ab**(AR − 실제)를 따로 보고한다(8-B-1) | 보고서에 ΔC 평균·부호가 있음. 양수로 치우치면 혼합 공식(②) 또는 렌더링(③) 점검 |

- 위 값은 모두 추정 시작값이다. 숙제 01의 "실제로 바른 사진"과 나란히 비교해 조정한다.
- **립스틱 + 글로스**(립 위에 글로스를 덧바른 모습)는 F18 겹쳐 바르기에 속하므로 MVP 다음(M16)에 둔다. MVP로 당길지는 팀이 결정한다(`docs/AR_PROGRESS.md` 결정 기록).
- **검증 화면:** 같은 사람·같은 조명·같은 자세에서 왼쪽은 맨입술 영상에 AR로 제품 X, 오른쪽은 제품 X를 실제로 바른 사진을 나란히 둔다. 트랙 B ③(ΔE2000·ΔC)과 Real or AR 평가(숙제 04)에 같은 세트를 쓴다.

### 6-5-4. 블러셔·섀도·아이라인·마스카라·하이라이터·쉐딩·아이브로우·파운데이션 (F13, 10-25·10-27)

사용자 요청("나머지 부위별로 넣어서", 범위 = 아이라인·블러셔/섀도 다듬기·하이라이터/쉐딩·속눈썹)으로 추가했고, 10-27에 아이브로우·파운데이션을 같은 경계로 넣었다. **원칙 1-2·1-3 경계:** 모든 부위는 제품 색을 정해진 영역에 얹을 뿐이고(진하기 0이면 픽셀 그대로), 얼굴형·피부 결·밝기 보정은 하지 않는다. 하이라이터가 밝게 하는 것은 그 제품의 색과 반사뿐이며 고정된 UV 영역(광대 위·콧등·인중 위·눈 앞머리) 밖으로 나가지 않는다. 파운데이션은 피부를 매끈하게 하거나 밝히지 않고 얼굴 윤곽 안쪽만 반투명하게 물들인다. 아이브로우는 눈썹 점을 옮기지 않고, 그 사람 윗선·아랫선 사이만 제품 색으로 채운다. 실제 제품처럼 두 층이다: 펜슬·파우더는 부드러운 눈썹 모양 안을 반투명하게 물들이고(피부·털 결이 비치며 밝아지지 않음), 브로우 마스카라는 털로 찾은 픽셀만 색조를 옮긴다. 가닥을 새로 그리지 않는다.

| 부위 | 그리는 방식 | 기준값 (`TUNING`) |
|---|---|---|
| 블러셔 | UV 타원(기존). **반투명 가루**: 덮는 층과 피부를 거르는 층을 섞음(밝은 색이 어두운 피부에 잿빛 막으로 얹히지 않게). AR 탭에서는 제형 칩을 보여 주지 않고 색만 고른다(10-28). 제품 hex는 그대로. YouCam `blush.glowStrength`는 0 | `blushCoverage 0.6`, `powderTint 0.6`, `faceSheen 0.5`, 경계 `blushPow` ← `uFaceRough.x` |
| 섀도 | UV 눈두덩→쌍꺼풀 선 + 같은 hex를 눈꼬리 아래 속눈썹 바깥쪽에. 제품 Texture 7종·hex는 그대로. 섀도를 켠 뒤에만 매트·쉬머·글리터·글로시. **매트** 펄 없음, 곱하기 opacity 0.70, roughness 1, spec 0. **글로시** 펄 없음, 곱하기 수분막 0.25, roughness 0.05, 더하기 오일 하이라이트 spec 0.9. **쉬머** YouCam 잔펄: 바탕 곱하기 opacity 0.30, density 0.35, scale 520, 쿨 화이트 펄은 눈동자 위에서 가장자리로 가우시안. **글리터** 쉬머와 같은 잔모래·곱하기 바탕·가운데 페이드. 밀도 0.75, 스케일 600. 매트는 가루만. Soft Peach `sparkle: 0`은 매트 | `SHADOW_FINISHES`, `shimmerScale 520`, `glitterScale 600` |
| 아이라인 | **화면 공간**(눈 캔버스 R). 칩 6개(내추럴·캣 윙·강아지·스모키·갸루·언더 포인트, 값은 `LINER_LOOKS`, 두께·꼬리 길이·각도·번짐·아래 라인 조합). **눈매 윙 칩과 그 렌더 경로는 10-29에 삭제**했고 모든 스타일이 같은 띠 + 꼬리 경로를 쓴다. 선은 **또렷하고 거의 불투명**하게 읽는다: 카메라 흐림 매칭을 쓰지 않고 반 텍셀 AA로 읽으며(`uLinerAA`), 매트·벨벳은 `max()`로 번진 테두리만 더한다(검은 중심 유지). 덮는 정도는 모든 스타일 `min(0.98, 0.97·(0.6+0.4·진하기)/0.94)`, 띠는 눈 캔버스 1.5텍셀 아래로 내려가지 않는다(`EYELINER_DARK`). 룩 데이터의 선택 필드: `linerSoftness`(0~1, 같은 선을 넓게 읽어 번지게. 0이면 그대로), `linerLower`·`linerLowerThickness`(아래 눈꺼풀 라인, 기본 눈 너비 0.03, 눈꺼풀이 닫히면 사라짐). 칩을 고르면 모든 라인 필드를 덮어써 앞 칩의 값이 남지 않는다. **눈꺼풀 맞춤(10-29)**: 윗·아랫눈꺼풀 점을 눈마다 카메라 픽셀의 속눈썹 라인으로 옮긴다(`fitLidLine`). 눈 너비 단위 오프셋 d를 점마다 잰다(윗선은 법선 방향 어두운→밝은 가장 센 경계, 범위 −0.01~0.05, 아랫선은 밝은→어두운, −0.01~0.03). 경계가 약하면 사전값(윗 0.02, 아랫 0.005)과 이웃 평균으로 대신하고, One Euro로 거른다. 눈 너비 40px 미만·눈 감김(세로/가로 0.12 미만)·옆얼굴(눈 법선 z 0.35 미만)이면 읽지 않고 사전값으로 되돌린다. 얼굴을 놓치면 버린다. 영상은 페이지 안에서만 읽는다(1-4). 점 번호별 고정 보정표(`linerLiftY`)는 삭제. 색은 제품 셰이드 칩만(1-1) | `TUNING.lidFit`, `fitLidLine`, `fitLidSide`, `readEyeCrop`, `EYELINER_PRESET.lidWing`, `openSpline`, `isLidWing`, `lib/linerLooks.ts` |
| 아이브로우 | 화면 공간 눈 캔버스 G, 점은 그대로, 칠은 눈 쪽으로 고정 거리만 내림. 경계는 눈썹 높이 25% 반경으로 한 번 더 흐림(붓 자국처럼). **1층 펜슬·파우더**: 그 모양 안을 `powder()` 반투명 막(0.45, 앞머리 0.4·산 0.85·꼬리 0.9). **2층 브로우 마스카라**: 눈썹 밖 피부(아랫선 아래 3점·윗선 위 3점 중 밝은 쪽)보다 어두운 픽셀만, 카메라 밝기는 두고 색도(r:g:b 비)를 제품 쪽으로(배율 ≤1.5), 밝은 색은 털 밝기를 0.35만 들어 올림. 절차적 가닥·hue 교체·단색 칠 없음. hex 안 바꿈. GAN·세그 모델·스톡 털 맵 없음 | `EYEBROW_PRESET` powder 0.45, lift 0.35, softness 0.25 |
| 파운데이션 | **커버력 모델(10-29)**: UV 얼굴 윤곽 안쪽(입술·눈 구멍·눈썹 뺌)에, 진하기 = 커버력 막대(0~1). 커버력이 정하는 두 값: 얹는 세기 `foundCoverage` 0.3→0.85, 그중 불투명 안료 몫 `foundOpaque` 0.15→0.9. 안료 몫은 제품 색 × 카메라 명암(붉은 기·얼룩은 제품이 덮는 만큼만 가려짐, 원칙 1-3의 '보정'이 아니라 바른 양의 결과), 나머지는 피부가 비치는 필름. 별도 미화·밝히기·광택 없음, 카메라 하이라이트로 밝아지는 상한 1.2(`foundShadeMax`). 피부 평균보다 많이 어두운 픽셀(앞머리·눈썹 털, `foundHair` 0.3~0.55)은 칠하지 않음. 제품 제형(매트·시어)은 렌더에 쓰이지 않으며 파운데이션 탭에 제형 필터 없음. 조명값(색·노출·피부 밝기)은 0.6초에 걸쳐 따라가 0.5초 계단·급변이 얼굴 전체 밝기 깜빡임으로 보이지 않게(`lightDisplaySec`). 피부색 참고 추천: 페이지가 숫자(Lab·신뢰도)만 1.5초마다 보내고 앱이 탭의 셰이드와 CIE76로 비교(언더톤 판단 없음). YouCam `glowIntensity`는 0 |
| 마스카라 | 눈 캔버스 G. 속눈썹 가닥(뿌리 굵고 끝 가늘게, 3가닥씩 뭉침, 길이·각도는 가닥 번호로 고정 → 깜빡임 없음), 아래 속눈썹은 짧고 옅게, 눈꺼풀 선(뿌리) 진하게. **눈을 뜨면 위로, 감으면 아래로**(눈 뜬 정도). 정면에서는 짧아 보이므로 길이 짧게. 눈 구멍 삼각형을 따로 그려 눈 위로 넘어온 가닥도 보임 | `lashCount 32`, `lashLength 0.1`, `lashWidth 0.012`, `lowerLash 0.4` |
| 하이라이터 | UV 영역 2번 마스크 R: 광대 위(관자놀이 쪽으로 긴 타원), 콧등, 인중 위, 눈 앞머리. 제품 색 조금 + 그 제품의 윤기·쉬머(빛 방향·정면 광원) | `hlCoverage 0.5`, `hlFeatherPx 18` |
| 쉐딩 | UV 2번 마스크 G: 광대 아래 패인 곳(귀→입꼬리 쪽으로 가늘게), 턱선, 이마·관자놀이 가장자리, 콧볼 옆. 반투명 가루 | `contourCoverage 0.55`, `contourFeatherPx 28` |
| 얼굴 가장자리 | 쉐딩·하이라이터는 얼굴 윤곽 안쪽에서 0으로 사라짐(메시 가장자리가 배경·머리카락에 걸려 얼굴 둘레에 흰 테가 생겼음) | `faceEdgeFadePx 36` |
| 옆얼굴 | 먼 쪽 눈의 아이라인·마스카라는 눈의 법선 z로 옅게, 깊이 테스트로 코 뒤는 가려짐 | — |
| 카메라 흐림 맞추기 | 눈 캔버스는 측정한 흐림 폭으로 3×3 이항 흐림을 걸어 읽음(흐린 폰 화면에서 1px 속눈썹·칼 같은 라인이 붙여 넣은 듯 보이지 않게). σ 2.5px로 흐린 LaPa에서 확인 | `uEyeSoft = max(0.6, 0.9 × blur)` |

헤드리스 확인(10-25, LaPa 정면 2·좌·우·감은 눈 2): 립만 켠 렌더와 전부 끈 렌더는 추가 전과 픽셀 차이 0. 감은 눈에서 아이라인·속눈썹이 눈꺼풀을 따라 아래로, 뜬 눈에서 꼬리가 또렷하고 속눈썹은 짧게. 하이라이터·쉐딩 위치는 차이 지도로 확인.

**YouCam Makeup VTO 숫자만 (라이브 호출 없음).** 분석·리프트·트랜스퍼·룩 결과 이미지는 쓰지 않는다. 키는 `research/youcam/`·repo `.env`의 `YOUCAM_API_KEY`만. `colorIntensity` 0–100은 `ZoneSetting.intensity` 0–1. 립 `fullness`·`wrinkless` 0, 블러셔 `glowStrength` 0, 섀도 `shimmerIntensity` 50 → `sparkleLift` 0.5, 아이라인 쉬머·메탈 → `uLinerGloss`, 눈썹 색만, 파운데이션 `glowIntensity` 0. 정지 비교 페이로드는 `research/youcam/youcam_vto.py`.

**10-27 제형 발림 라벨 (연구, 사용자):** 유튜브 파일은 받지 않는다. `research/finish_labels/`가 영상 ID만 고르고 Gemini 영상 이해로 퍼짐(`wide`/`tight`/`unknown`)·윤기(`dull`/`wet`/`unknown`)·입자(`none`/`fine`/`chunky`/`unknown`)만 읽는다. 다수결(비 unknown 60%)이 지금 셰이더(`blushPow`, `uLinerGloss`, `flakeScaleShimmer`)와 다를 때만 `TUNING`을 바꾼다. 제품 hex·인물 이름·프레임은 저장하지 않는다. AR 런타임은 유튜브·Gemini를 호출하지 않는다. 레시피 추출 전체(M10)는 이 범위가 아니다.

**10-27 (사용자):** AR 시착은 립·블러셔·섀도·아이라인·아이브로우·파운데이션을 칠하고, 마스카라·하이라이터·쉐딩은 카메라와 부위 탭에서 뺀다. 룩 레시피·룩 상세 그림·룩 가이드 문구는 그대로 둔다. 구현: `AR_PAINT_ZONES`·`arPaintMakeup`, 렌더러에서 세 부위를 `null`.

#### 6-5-5. 룩 프리셋: 갸루 클래식 (10-26)

사용자 요청(룩을 누르면 갸루 AR로 입혀지게)과 팀 기획안(비슈 갸루 룩 기획안)을 따라 **기존 부위의 조합으로** 정의한다. 새 렌더링 경로는 없고, 룩은 데이터(`CelebLook.makeup`)일 뿐이다. 개발 모드에서만 `lib/devCatalog/demo.ts`의 데모 룩으로 제공하며(백엔드에 룩이 없거나 연결이 안 될 때 대체), 배포는 백엔드 시드의 룩을 쓴다.

| 부위 | 갸루 클래식 설정 | 구현 |
|---|---|---|
| 립 | 누디 베이지 `#D2A593`, 매트, 진하기 0.8 | 기존 립(층 쌓기). 이 룩은 오버립을 쓰지 않음(아래 레트로·세미 갸루는 씀) |
| 아이섀도 | 화이트 펄 `#F3E9DF` + 둘째 색 브라운 `#5A3A2C`, 쉬머, 0.85 | `ZoneSetting.hexTo`. 둘째 색은 눈꼬리 쐐기와 아래 속눈썹 선을 따라 번짐(UV 마스크 2의 B, 눈 랜드마크 기준) |
| 아이라이너 | 검정 리퀴드, 꼬리 길이 0.42·각도 12°·두께 0.075(기본 0.18·15°·0.09) | `geometry` |
| 마스카라 | 검정, 진하기 1, 길이 ×1.55·밀도 ×1.6 | `geometry.length`·`geometry.thickness`(마스카라는 배수) |
| 하이라이터 | 펄 핑크 `#F4D6D6`, 쉬머, 0.8 | 콧대·인중 위·광대·눈 앞머리에 **이마 중앙과 눈 아래**가 추가됨(모든 하이라이터 공통) |

**넣지 않은 것 (명세·원칙과 충돌, 팀 결정 필요)**
- **오버립(갸루 클래식):** 이 룩에는 쓰지 않는다. 오버립 기능은 6-5-6 레트로·세미 갸루 룩 요청으로 구현했다(아래).
- **얼굴 태닝 베이스:** 피부 전체를 어둡게 고르는 층이다. 10-27 파운데이션은 제품 색만 반투명하게 올리며 태닝·결 보정이 아니다. 화면 전체 태닝 필터는 계속 넣지 않는다.
- **화면 전체 태닝 필터, 3D 속눈썹 메시, 고정 UV 텍스처 맵, 흰색 덮기 하이라이터:** 기획안에서도 삭제·보류·수정된 항목.

#### 6-5-6. 룩 프리셋: 레트로 갸루 & 세미 갸루 (10-26)

팀 기획안(레트로·세미 갸루 룩 개발 기획안)에 따른다. 룩 ID `demo-look-semi-gyaru-retro`(개발 모드 데모, 태그 Y2K·festival·photoshoot·bold). **오버립을 이 요청으로 구현**한다(6-17·10장은 "후보, 구현하지 않음"이었으나 사용자가 기획안과 함께 요청했고, 1장의 원칙을 어기지 않는다: 실제 립 제품의 오버라인 기법이며 얼굴·피부는 바꾸지 않는다). 기획안의 `a1`(덮는 정도)은 앱의 `intensity`로 옮겼다(contour 0.35→0.6, 하이라이터 0.45→0.9, 섀도 0.4→0.5, 라이너 0.9→0.9, 마스카라 0.85→0.78, 크림 립 0.7→0.46).

| 부위 | 설정 | 구현 |
|---|---|---|
| 립 | 더스티 누드 `#C99A8A` 크림, 오버립 0.03·입술 산 0.02·중앙 밝기 0.15 | `geometry.overlip`·`peakOverdraw`·`centerHighlight` |
| 아이섀도 | 샴페인 베이지 `#E9D2C2` 쉬머, 눈꼬리·아래 속눈썹 선을 따라 브라운 `#6B4A3A`, 눈앞머리 화이트 펄(반지름 0.18, a1 0.6) | `hexTo`, `geometry.innerPoint` |
| 아이라이너 | 검정, 꼬리 길이 0.35·각도 12°·두께 0.072(기본의 1.6배) | `geometry`. 꼬리는 얼굴 가장자리까지 거리의 80%를 넘지 않음 |
| 마스카라 | 검정, 길이 ×1.5·밀도 ×1.4, 아래 속눈썹 포함 | `geometry.length`·`thickness`·`lower` |
| 하이라이터 | 아이보리 `#FFF4EC` 새틴, 이마·콧대·눈 아래만 | `geometry.areas`(이름 있는 영역만). 이름이 없으면 기본 영역 그대로 |
| 컨투어 | 웜브라운 `#8A5A44` 매트 | 기존 컨투어. **태닝 베이스는 base 존이 생길 때까지 미룬다**(기획안과 같음) |

**오버립 구현 (핵심)**
- 윤곽: 얼굴 점으로 만든 바깥 입술선을 입술 중심에서 바깥으로 `overlip × 입 너비`만큼 밀고(입꼬리 0 → 가운데 최대), 입술 산(랜드마크 37·267과 이웃)은 위로 `peakOverdraw`만큼 더 민다. 입을 벌릴수록 줄인다(`overlipOpenReduce 0.6`, 치아 위로 번지지 않음). 원래 윤곽은 윤곽 텍스처의 B 채널에 따로 둔다.
- 피부 기준: 원래 윤곽 밖의 띠(= 피부)는 **맨입술이 아니라 측정한 피부 평균(색·밝기)을 맨 바탕으로** 층 쌓기 공식에 넣는다. 입술 안은 그대로 맨입술 평균. 경계에서는 두 기준을 부드럽게 섞는다(`skinRefW`). 그 띠에서 보이는 밝은 곳은 입술 반사가 아니라 피부 광택으로 취급한다.
- 오버립 0이면 윤곽·결과가 변하지 않는다(헤드리스: 립 렌더 6장 중 4장 차이 0, 나머지는 UV 밴드를 5→12로 넓힌 가장자리 40여 픽셀뿐이며 밴드를 5로 되돌리면 정확히 0).
- 입술 중앙 밝기: 입 축을 따라 입술 중앙(랜드마크 0·17)에서 가우시안으로 **밝기만** 곱한다(색 유지, 흰색 덮기 아님, UV 위치 아님).

**기획안 대비 달라진 것**
- 하이라이터 `mode: 'brighten'`은 따로 만들지 않았다. 제품 색(아이보리)을 고정 영역에 얹고 그 제품의 윤기를 더하는 기존 방식이 같은 결과이며, 피부 밝기만 올리는 처리(1-3 금지)를 피한다.
- 타입은 기획안의 `ZoneShape` 대신 기존 `ZoneGeometry`를 확장했다(`overlip`·`peakOverdraw`·`centerHighlight`·`lower`·`innerPoint`·`areas`). 백엔드 스키마에도 선택 항목으로 반영(범위 검증 포함).
- 룩 프리셋은 `constants/looks.ts`가 아니라 기존 `CelebLook`(데모는 `lib/devCatalog/demo.ts`)으로 정의한다.

#### 6-5-7. 룩 프리셋: 소프트 피치 코랄 (10-26)

팀 기획안(소프트 피치 코랄 룩 개발 기획안)을 따른다. 룩 ID `demo-look-soft-peach-coral`(개발 모드 데모, 태그 spring·summer·date·selfie·natural). 기획안의 `a1`은 앱의 `intensity`로 옮겼다(시어 블러셔 0.30→0.5, 쉬머 섀도 0.35→0.44, 라이너 0.55→0.1, 마스카라 0.60→0.22, 하이라이터 0.25→0.7×`geometry.intensity` 0.6, 시어 립 0.55→0.56). 핵심은 **눈두덩이와 볼의 색 통일**이다.

| 부위 | 설정 | 구현 |
|---|---|---|
| 색 통일 | 섀도·블러셔가 `#F4A78A` 하나를 공유, 한쪽 제품을 바꾸면 다른 쪽이 같은 색으로 따라감 | `CelebLook.colorLinks`, 스토어 `colorLinks`·`applyShade`. 따라가는 존은 색만 바뀌고 제형·세기·`hexTo`는 유지, 제품 셰이드가 아니므로 장바구니 선택에서 빠짐 |
| 블러셔 | 시어, 애플, 크기 ×1.1, 번짐 0.85 | `geometry.blushPlacement`·`blushSize`·`blushSoftness`. 얼굴 UV에서 두 개의 기울어진 타원(눈동자 아래 광대 = 아래 눈꺼풀 점과 볼 아래 점의 가운데 + 바깥쪽 약간, 아래 눈꺼풀 아래로만 퍼짐). 모양을 지정하지 않으면 기존 마스크 그대로 |
| 섀도 | 피치 코랄 쉬머, 바깥 눈꼬리만 `#E38B6F`로 진하게, **입자 없는 펄** | `hexTo`, `geometry.pearl`(눈두덩이 중앙 밝기만 곱함, 메시 법선 기준이라 고개를 움직이면 밝은 곳이 이동), `geometry.sparkle: 0`(쉬머 입자 끔) |
| 아이라이너 | 얇은 브라운, 꼬리 거의 없음(길이 0.08·각도 5°·두께 0.036) | `geometry` |
| 마스카라 | 약간 길게(×1.1), 아래 속눈썹 생략 | `geometry.length`·`lower: false` |
| 하이라이터 | 콧대·눈 아래, 약하게 | `geometry.areas`, `geometry.intensity`(세기의 배수) |
| 립 | 시어 코랄 틴트 `#F2735B`, 풀립 | 기존 립. 시어 혼합 수정(6-5-3 층 쌓기 행) |

**붉은 맨입술 + 시어 코랄 (기획안 5-1)**: 이미 립스틱을 바른 얼굴 7장(LaPa)에 시어 코랄 `#F2735B`를 렌더. 수정 전 시어 혼합은 한 얼굴에서 입술 밝기가 L* 50.2 → 41.5(맨입술·제품 L* 63.1 모두보다 어두움)였고, 수정 후 50.2 → 49.1(−1.1)이다. 나머지는 L* +13.6·−2.2·+9.6·+5.6·−4.6·−10.2이며 L*이 내려간 얼굴은 맨입술이 제품(63.1)보다 밝아 제품 쪽으로 수렴한 경우다. 입술 색조는 모두 코랄(30~37°)로 간다. 누드·핑크·레드 × 제형 격자: 레드 시어의 제품 색 거리(a*b*) 30.6 → 9.6, 누드 시어 5.3 → 5.4, 핑크 시어 10.4 → 8.8.

**섀도·블러셔 색 통일 확인 (기획안 5-2)**: 렌더 영역 평균 색의 Lab 색상각 차이(블러셔 − 섀도, 6장): 0.6°, 0.5°, 1.7°, 3.1°, 5.4°, 9.3°(옆으로 크게 돌아가 먼 쪽 볼이 조명을 다르게 받은 얼굴). hex는 바꾸지 않았다. 바뀐 색(렌더 − 맨 얼굴)의 색상각은 흑백에 가까운 사진에서 불안정해 기준으로 쓰지 않는다. 팀 기준값은 아직 없다.

**기획안 대비 달라진 것**
- `gradient`(그라데이션 립)는 만들지 않았다. 이 룩은 값이 0(풀립)이고 "최종발표 범위"로 표시돼 있다. 바깥 입술선과 안쪽 입술선을 구분하는 거리 값이 필요해 따로 설계해야 한다.
- `mode: 'brighten'`은 6-5-6과 같은 이유로 두지 않았다(제품 색 + 윤기).
- 베이스는 base 존이 없어 렌더하지 않고, 래디언스는 하이라이터를 약하게 써서 표현했다(기획안과 같음).
- 블러셔 `apple` 위치: 기본 마스크의 중심은 눈의 세로줄보다 바깥·아래(볼 옆)라서, 기획안의 "광대 가장 높은 지점"에 맞게 눈동자 아래로 새로 잡았다. 그 대신 크기 기준을 기본의 0.8배(`appleScale`)로 줄였다.

#### 6-5-8. 룩 프리셋: 샤프 스네이크 아이 아이돌 (10-26)

유튜브 튜토리얼 검색(`/api/youtube/search`)으로 찾은 아이돌 커버 메이크업 영상 하나(YouTube `YTV9sDuOYv8`, 설명란에 제품·호수 목록이 있는 유일한 후보)를 참고했다. 영상 내용은 API로 받을 수 없어서, **설명란의 제품 목록**(어떤 부위에 어떤 계열을 쓰는지)과 **썸네일의 완성 얼굴**(색과 위치)을 사람이 읽고 값으로 옮겼다. 룩 ID `demo-look-snake-eye-idol`(개발 모드 데모). 원칙 1-6에 따라 룩 이름·설명·`tutorialQuery`에는 실존 인물 이름을 넣지 않았고(테스트로 확인), 참고 썸네일은 저장소에 넣지 않았다. 색은 실제 제품 측정값이 아니라 데모 값이다.

| 부위 | 영상(설명란 제품 계열 + 썸네일) | 설정 |
|---|---|---|
| 블러셔 | 쿨 핑크 파우더 블러셔, 눈 바로 밑부터 볼 전체로 넓게 | `#EC9DB0` 매트 0.85, `under_eye`, 크기 ×1.4, 번짐 0.9 |
| 섀도 | 모브 토프 팔레트로 세미 스모키, 바깥 눈꼬리와 아래 점막이 진함 | `#B08A8C` 매트 0.55, `hexTo` `#4E3B3D` |
| 아이라이너 | 블랙 리퀴드, 길고 위로 뺀 꼬리(뱀상) | 글로시 1.0, 길이 0.38·각도 18°·두께 0.05 |
| 마스카라 | 롱컬링 마스카라 + 아래 속눈썹 | 0.85, 길이 ×1.45·두께 ×1.3, `lower: true` |
| 하이라이터 | 로즈 골드 글로우, 이마·콧대 | `#F6D9CF` 쉬머 0.75, `forehead`·`nose_bridge` |
| 컨투어 | 쿨 컨투어 | `#7A6260` 매트 0.35 |
| 립 | 글로우 틴트 + 체리 레드 틴트, 유리알 광 | `#C9566A` 글로시 0.62 |

**렌더 확인**(LaPa 6장): 블러셔를 처음 0.55·×1.3으로 두었을 때 눈 밑 색 변화가 ΔE 3.1~3.7로 썸네일(블러셔 − 맨 피부 약 ΔE 9)보다 훨씬 약해서 0.85·×1.4로 올렸다(ΔE 5.0~6.0, 썸네일 피부가 더 밝아 같은 핑크가 더 잘 보인다).

**영상 대비 달라진 것**
- 입술 그라데이션(안쪽 진하고 바깥 흐림)은 그라데이션 립이 없어 풀립으로 칠했다(6-5-7과 같은 보류).
- 포슬린 베이스·컨실러는 base 존이 없어 렌더하지 않는다.
- 렌즈·앞머리·속눈썹 연장(인조 속눈썹)은 범위 밖이다.

#### 6-5-9. 룩 상세: 단계별 메이크업 그림 (10-27)

룩 상세 화면에 "이렇게 그려요" 구역을 추가했다. 룩이 쓰는 부위마다 한 단계씩(섀도 → 라인 → 마스카라 → 블러셔 → 쉐딩 → 하이라이터 → 립) 얼굴 그림 + 말풍선 설명 카드를 보여 준다. 사진이 아니라 **룩 데이터의 색·형상(`makeup`)으로 그린 일러스트(SVG)**라서 룩을 추가하면 그림이 저절로 생기고, 연예인·참고 사진·LaPa 이미지를 쓰지 않는다(1-6).

- 그림: `components/look/FaceChart.tsx`(react-native-svg, Expo Go 기본 포함), 카드: `components/look/HowToSteps.tsx`, 단계 구성: `lib/lookGuide.ts`(`buildGuideSteps`).
- 단계가 진행될수록 앞 단계의 색이 누적되고, 지금 단계의 부위에 점선 가이드와 확대 구도가 붙는다.
- 그림에 반영되는 값: 섀도 2색(`hexTo`), 라인 길이·각도·두께, 마스카라 길이·아래 속눈썹, 블러셔 위치·크기(렌더러처럼 아래 눈꺼풀 위로는 안 올라감), 하이라이터 영역, 쉐딩, 립 제형별 윤기.
- **순서는 룩마다 다르다**(10-27): `CelebLook.stepOrder`(백엔드 `step_order`). 빠진 부위는 기본 순서로 뒤에 붙는다. 데모 7개 룩은 모두 다른 순서다(예: Stage Red = 쉐딩 → 하이라이터 → 섀도 → 라인 → 마스카라 → 블러셔 → 립, Soft Peach = 블러셔 먼저). 카메라 가이드(6-5-11)도 눈썹 다음은 룩 순서를 따른다.
- **설명 문구도 룩 값에서 만든다**(10-27, `lib/lookGuide.ts`): 라인 = 길이(0.3 이상 길고 날카롭게 / 0.12 이하 거의 안 뺌)·각도·굵기(0.06 이상 두 번 덧그리기 / 0.04 이하 아주 얇게)·제형(글로시 = 리퀴드, 매트 = 펜슬), 마스카라 = 길이(1.4 이상 여러 번)·아래 속눈썹, 섀도 = 2색·눈앞머리 펄·중앙 펄·쉬머, 립 = 제형(매트·벨벳 / 글로시·시어)·오버립, 블러셔 = 위치·크기, 하이라이터 = 영역 이름, 블러셔·쉐딩·하이라이터 = 세기(0.35 이하 옅게 / 0.6 이상 한 번 더). 문구 조각은 `looks.guide.*`로 4개 언어에 있다. 룩별로 사람이 쓴 자유 팁(`howTo`)은 아직 없다.
- 그림은 표준 얼굴 모양이라 실제 AR 렌더와 똑같지 않다(참고용 도식).

#### 6-5-10. 룩 색을 못 찾을 때 (10-27)

룩이 칠하는 색(`makeup`)을 입은 제품이 매장(카탈로그)에 없으면 룩 상세에 "색을 못 찾은 제품" 구역이 나온다. 부위마다 아래 순서로 한 가지 결과를 보여 준다. 룩 제품이 그 색(ΔE ≤ 8)을 이미 입고 있으면 아무것도 안 나온다.

| 순서 | 조건 | 보여 주는 것 | 장바구니 |
|---|---|---|---|
| 1 | 같은 부위의 카탈로그 셰이드 중 가장 가까운 것이 ΔE ≤ 8 | 가장 비슷한 색(거의 같은 색) | 그 셰이드가 세트에 담김 |
| 2 | ΔE ≤ 28, 색상각 차이 ≤ 18°, 밝기(L*) 차이 ≥ 4 | 가장 비슷한 색 + **양 조절**: 룩 색이 더 진하면 "n번 겹쳐 바르기"(밝기 차 10 미만 2번, 이상 3번), 더 연하면 "얇게 한 번, 손가락으로 톡톡" | 그 셰이드가 세트에 담김 |
| 3 | 그 밖(가까운 셰이드 없음) | 네이버 쇼핑 판매처(`GET /api/offers/search?q=`, 상위 3개) + 네이버 쇼핑 검색 링크 | 담기지 않음 |
| 4 | 3번에서 서버가 네이버를 조회했는데 결과가 0개 | **품절**(눌리지 않음, 이유 표시) | 담기지 않음 |

- 3번에서 서버에 네이버 키가 없거나 조회가 실패하면(`configured: false`·오류) 품절로 단정하지 않고 네이버 쇼핑 검색 링크만 보여 준다. 네이버 쇼핑 API가 이 키로 막혀 있는 경우(SE05)도 같다.
- 검색어는 색 계열·부위·제형을 한국어로 조합한다(예: `레드 립 벨벳`, `블랙 마스카라`). UI 문구가 아니라 검색 키워드라서 언어와 상관없이 한국어다. 룩에 제품 이름이 없어도 만들 수 있다.
- 룩의 제품은 있는데 그 셰이드가 매장에서 사라진 경우(`shadeId`가 제품에 없음)도 색을 못 찾은 것으로 보고 세트 담기에서 뺀다.
- 구현: `lib/lookColors.ts`(판단), `hooks/useLookColorGaps.ts`(카탈로그 + 판매처 조회), `components/look/ColorGaps.tsx`(표시), 백엔드 `OfferService.search_offers`·`GET /api/offers/search`(분당 20회 제한, 6시간 캐시).
- 한계: 양 조절은 밝기·색상각만 본 규칙이며, 실제 제품 발색은 확인하지 않았다.

#### 6-5-11. 카메라 위 그리는 법 가이드 (10-27)

AR 화면의 "그리는 법" 버튼을 켜면 라이브 얼굴 위에 점선 가이드가 그려진다. 4단계(눈썹 → 섀도 → 아이라인 → 립)이고, 단계 바나 부위 탭으로 바꾼다. 전체 화면 흐름은 `docs/LOOK_FLOW_SPEC.md`.

| 단계 | 그리는 것 |
|---|---|
| 눈썹 | 코 옆에서 눈앞머리·눈동자·눈꼬리를 지나 눈썹 높이까지 올라가는 점선 3개(1 시작, 2 가장 높은 곳, 3 끝)와 세 점을 잇는 분홍 점선 |
| 섀도 | 흰 점선 = 눈두덩이 전체(윗눈꺼풀 선 ~ 접히는 선, 렌즈 모양), 주황 점선 = 눈꼬리 쪽 음영 영역 |
| 아이라인 | 룩의 `geometry.linerStyle`(없으면 각도·길이로 추정). **classic_winged**: 윗눈꺼풀 점선, 눈앞머리 → 눈꼬리 흰 화살표, 꼬리 주황 화살표(각도·길이, 기본 15°·0.18)와 각도 숫자. **puppy**: 같은 축에서 꼬리가 아래로(기본 −8°). **tightline**: 윗눈꺼풀 점(속눈썹 사이 근사) + 짧은 얇은 꼬리. 삼각으로 눈두덩을 채우지 않음 |
| 립 | 바깥 입술선·안쪽 입술선 점선, 바깥 → 안쪽 주황 화살표 |

- 구현: 페이지 안 `drawGuide`가 필터를 거친 얼굴 점으로 매 프레임 오버레이 2D 캔버스에 그린다(WebGL 캔버스와 같은 좌우 반전 좌표). 앱은 `{ type: 'guide', guide: { step, angle, length, style } }` 숫자·이름만 보낸다(1-4). 끄면 `guide: null`. Three.js·별도 아이라인 캔버스·`types/eyeliner.ts`는 쓰지 않는다.
- 가이드는 색을 바꾸지 않는다(1-1). 얼굴 영상·이미지는 어디에도 저장·전송하지 않고, 테스트가 가이드 코드에 네트워크·저장·`postMessage`가 없음을 확인한다.
- 눈썹에는 색 부위가 없어 가이드만 있다.
- 이름 주의: F8 "따라 바르기"(6-10)는 립에 실제 바른 색을 측정해 안내하는 별개 기능이다.

#### 6-5-12. 룩을 입은 뒤 조절하기 (10-27)

룩을 고르면 룩의 모든 부위가 **데이터로는** 입혀지고, 그중 **대표 부위(`CelebLook.heroZones`)**가 AR에서 칠하는 부위(립·블러셔·섀도·아이라인) 탭에 별 표시로 강조되며 AR이 그중 첫 탭에서 열린다. 마스카라·하이라이터·쉐딩은 룩에 남아 있어도 AR 얼굴에는 안 칠한다. 대표가 아닌 칠 가능 부위는 룩이 정한 대로 두되, 모두 룩 데이터에 있는 것만 입혀진다(룩에 없는 부위는 꺼짐).

| 사용자 동작 | 룩 | 부위 | 추천 |
|---|---|---|---|
| ~~진하기 슬라이더~~ | **제거(10-27)**. AR 패널에 농도 막대가 없음. 룩·제품 기본 `intensity`만 사용 | | |
| 색 칩(셰이드) 선택 | **유지, 배너가 "(수정됨)"** | 색·제형만 교체. **룩의 모양(윙 각도·길이, 2색 섀도 `hexTo`, 펄 등)은 유지**. 탭에 수정 표시 | 고른 제품이 그대로 추천 |
| 부위 끄기 | 유지, 수정됨 | 그 부위 꺼짐 | 세트에서 빠짐 |
| "룩 색으로 되돌리기" | 그 부위(색 통일로 묶인 부위 포함)가 룩의 색·제품으로 복귀. **사용자가 바꾼 진하기는 유지** | | |
| 룩에서 입었던 제품·셰이드를 다시 고름 | 수정 표시가 사라짐 | | |
| 다른 룩 선택 | 새 룩이 원래 값이 됨(수정 목록 초기화) | | |

- **같은 룩인지**는 제품·셰이드로 판단한다(룩이 제품을 정한 부위). 룩에 제품이 없는 부위는 색과 제형으로 판단한다.
- **제품 매칭**: 부위가 입은 색을 고른 제품이 없으면(룩 색이 매장에 없음, 색 통일로 따라온 부위) 그 부위 탭에 **"이 색에 가장 가까운 제품"** 카드가 뜬다. 가까운 셰이드와 양 조절(겹쳐 바르기·얇게, 6-5-10)을 보여 주고 "이 제품 입어보기"로 바로 입을 수 있다. 가까운 셰이드가 없으면 룩 화면에서 판매처를 찾으라고 안내한다. 가장 가까운 셰이드는 AR의 "세트 담기"에도 같이 담긴다.
- 진하기는 제품을 바꾸지 않는다(바르는 양이므로 카드의 양 조절 문구로만 반영).
- 색 칩은 **실제 제품 셰이드만** 쓴다(원칙 1-1, 1-8). 임의 hex로 제품을 매칭하는 자유 색 선택은 하지 않았다.
- 구현: `store/makeupStore.ts`(`heroZones`, `modified`, `lookOrigin`, `revertZone`), `app/(tabs)/ar.tsx`, `lib/lookColors.ts`. 백엔드 `CelebLook.heroZones`.

#### 6-5-13. AR 탐색 / 상품 고정 (10-27)

두 진입은 같은 AR 탭(`app/(tabs)/ar.tsx`)이다. 자유 Hex 팔레트와 추천 API는 쓰지 않는다. 색 칩은 카탈로그 셰이드이며, 고른 칩이 그 부위의 상품이다.

| 진입 | 얼굴 | 패널 |
|---|---|---|
| **탐색** (AR 탭) | 부위마다 고른 셰이드를 같이 칠함 | 부위 탭·색 칩. 고른 색의 상품 카드(브랜드·이름·호수·가격, 그 상품만 담기). 룩 색인데 고른 상품이 없을 때만 "가장 가까운 제품" 카드 |
| **상품 고정** (상품 상세 `AR로 입어보기`) | 그 상품 부위만 제품 색으로 칠함. 다른 부위는 들어가기 전 화장 그대로 | 칩·필터·끄기·룩 없음. 그 상품 정보와 장바구니, 상품으로 돌아가기 |

- 고정은 `startFit(product, shade)`가 `productId`·`shadeId`만 들고, 들어가기 전 메이크업을 메모리에 남긴다. Hex를 따로 넘기지 않는다.
- AR 탭을 벗어나면 `endFit`이 스냅샷을 되돌린다. 다음에 탭으로 들어오면 탐색이다.
- 립·블러셔·섀도·아이라인이 아니거나 셰이드가 없으면 체험 버튼을 숨긴다.

### 6-6. 조명 자동 추정 (F2) — 갤럭시·아이폰 공통

**원칙:** 사용자에게 흰 종이 같은 도구를 요구하지 않는다. **두 플랫폼에서 같은 방식**으로 동작해야 한다(같은 립이 갤럭시와 아이폰에서 다르게 보이지 않게). 모든 계산은 AR 페이지 안의 JavaScript·셰이더 코드로 하고, 네이티브 모듈을 쓰지 않는다(Expo Go 유지).

#### 6-6-1. 공통 방식 (MVP)

| 단계 | 방법 | 결과 | 두 폰 |
|---|---|---|---|
| ① 조명 색 (기본) | **배경 Gray World:** 분할 모델 background 클래스 픽셀의 선형 RGB 평균을 휘도 1로 정규화. 하얗게 날아간 픽셀(최댓값 > 0.92)과 너무 어두운 픽셀은 제외 | `lightRGBLinear`, `source: 'gray_world'` | ✅ 공통 |
| ② 빛 방향·세기 | **얼굴을 빛 탐지기로:** 얼굴 메시 면의 방향(법선)과 그 자리 피부 밝기를 비교해 주된 빛 방향·세기를 계산. 피부색과 섞이는 **색은 계산하지 않고 방향·세기만** 쓴다 | `lightDir`, `lightIntensity` → 광택 위치·명암에 반영 | ✅ 공통 |
| ③ 카메라 정보 (덤) | `track.getCapabilities()`에 `colorTemperature`·`whiteBalanceMode`가 있으면 값을 읽고, 가능하면 화이트밸런스를 고정(`manual`) 요청. 실패하면 그냥 건너뜀 | `cameraColorTempK`, `whiteBalanceLocked` | 지원 기기만 (Android Chromium 계열 가능성, iOS는 자료 없음 → 실기기 확인) |

- ①②는 0.5초마다 계산하고 이동 평균을 쓴다. 매 프레임 계산하지 않는다.
- ③이 되는 기기에서도 ①의 결과를 기본으로 쓰고, ③은 화이트밸런스가 저절로 바뀌는 것을 막는 데만 쓴다. 두 폰의 계산 경로를 같게 유지하기 위해서다.
- **신뢰도:** 배경 픽셀이 충분하고 색이 고르면 `confidence: 'high'`, 배경이 작거나 한 색에 치우치면(예: 빨간 벽) `'low'` + 화면에 "조명을 추정 중이에요. 색이 실제와 다를 수 있어요" 표시(i18n).
- 하이라이트가 날아간 영역이 얼굴의 일정 비율 이상이면 "조명이 너무 강해요" 안내.
- `lightChange`: 얼굴 피부 평균 Lab을 0.5초마다 `refSkinLab`과 비교해 ΔE2000이 임계값(초기 6, 설정값)을 넘으면 조명을 다시 추정한다(사용자 조작 없이).
- **부위별 피부 측정 (v2):** 이마, 왼볼, 오른볼, 턱, 입술(안쪽·바깥쪽)을 각각 측정해 `skinLabByRegion`으로 저장한다. 근거: arXiv 2512.21988에서 기기보다 얼굴 부위가 색 차이의 더 큰 원인이었고, 부위별 보정이 기기 간 일치도를 크게 높였다.
- **ITA 사용 범위:** ITA는 평가 집계(피부톤 구간 나누기)에만 쓰고 추천 로직에는 쓰지 않는다.
- 결과는 `calibration_result`로 호스트에 숫자만 보내고, 호스트가 `store/calibrationStore.ts`에 저장한다(6-0).
- 다른 라이선스의 화이트밸런스 모델(Deep White Balance, WB_sRGB, mixedillWB 등)은 앱에 넣지 않는다. 연구용·비상업 라이선스이고, Deep White Balance 방식은 삼성전자 특허(US12335667)가 있다. 비교는 숙제 실험(R2-6)에서만.

#### 6-6-2. 플랫폼 조명 추정 — 조건부 도입 후보 (MVP 아님, 구현하지 않음)

| 플랫폼 | 기능 | 주는 값 | 확인 상태 |
|---|---|---|---|
| iOS | ARKit `ARFaceTrackingConfiguration` + `isLightEstimationEnabled` (`ARDirectionalLightEstimate`) | 얼굴을 빛 탐지기로 쓴 방향·세기·구면 조화 계수 | iOS 14+, Neural Engine 기기. 실행 중 `isSupported` 확인 |
| Android | ARCore Augmented Faces(셀카 전용) + Lighting Estimation | Ambient Intensity(밝기·색 보정) 또는 Environmental HDR | **앞 카메라에서 조명 추정이 되는지 문서로 확인 못 함 → 갤럭시 실기기 확인 필요** |

- **왜 MVP에서 빼나:** 아직 구현해서 확인하지 않았다. ① 갤럭시에서 되는지, ② 공통 방식보다 정말 정확한지, ③ 카메라 충돌(플랫폼 AR 세션과 AR 페이지가 같은 앞 카메라를 동시에 쓰기 어려움)을 피할 수 있는지 모른다. 또 Expo Go를 버리고 development build로 가야 한다.
**진행 규칙 (모두 지킨다)**
1. **MVP에서는 구현하지 않는다.** 10장 범위 밖에도 "네이티브 조명 추정"으로 적어 둔다. 코딩 에이전트는 이 절을 근거로 네이티브 모듈을 추가하지 않는다.
2. **팀이 development build 전환을 합의한 뒤에만 진행한다**(저장소 `AGENTS.md` 규칙). 합의 전에는 Expo Go 구조를 유지한다.
3. **두 플랫폼 결과를 같은 형식으로 맞춘다.** ARKit·ARCore 값도 `LightCalibration`(`source: 'arkit' | 'arcore'`)으로 바꿔 넣고, 이후 색 계산(6-5 셰이더, 6-7, 6-9)은 공통 경로로 한다. 플랫폼별 계산 분기를 만들지 않는다.
4. **안 되는 기기는 공통 방식(6-6-1: Gray World + 얼굴 메시)으로 돌아간다.** 지원 여부는 실행 중에 확인하고(ARKit `isSupported`, ARCore 세션 설정 확인), 실패해도 AR이 멈추지 않아야 한다.
5. **ARCore는 앞 카메라 조명 추정이 되는지부터 갤럭시 실기기로 확인한다.** 안 되면 Android는 공통 방식만 쓰고, 그 경우 두 폰 결과 차이(트랙 B `b_device.py`)를 보고 iOS만 도입할지 다시 판단한다.

**도입 조건 (셋 다 만족할 때만):** ① 6-6-1 공통 방식의 트랙 B 색 오차가 목표에 못 미침, ② 갤럭시·아이폰 둘 다 동작 확인(또는 한쪽만일 때 기기 간 차이가 허용 범위), ③ 팀 합의(규칙 2).

**확인 순서**
```
MVP 완성 (공통 방식)
  → 숙제 01 사진으로 공통 방식 색 오차 측정
  → 충분하면 여기서 끝 (네이티브 안 씀)
  → 부족하면: ① 갤럭시에서 ARCore 앞 카메라 조명 추정 지원 확인 (규칙 5)
              ② iOS에서 "시작할 때 몇 초간 ARKit으로 조명을 잰 뒤 AR 페이지로 넘어가는" 작은 실험
  → 공통 방식 대비 ΔE2000 비교 → 11-2에 기록 → 팀 합의 후 다음 버전 범위에 포함
```

- 얼굴 추적을 쓰면 개인정보 처리방침에 얼굴 데이터 사용 목적을 적어야 한다(Apple 요구).

### 6-7. 진하기 슬라이더 ↔ 바르는 횟수 (F5)

**AR 패널의 농도 막대는 10-27에 전부 뺐고, 10-28에 블러셔 탭만 되돌렸다(사용자 요청).** 블러셔를 켠 뒤 연하게↔진하게(0.15~1)가 `blush.intensity`를 바꾼다. 덮는 양은 그대로 `intensity × blushCoverage`. 다른 부위는 룩 레시피와 `DEFAULT_INTENSITY`만 쓴다. 계산식은 렌더러가 그대로 쓴다.

```ts
// n번 바른 진하기
const intensityAfter = (a1: number, n: number) => 1 - Math.pow(1 - a1, n);
// 목표 진하기에 필요한 횟수 (1~5 제한, 결과에 "약" 표기)
const layersFor = (a1: number, target: number) =>
  Math.min(5, Math.max(1, Math.round(Math.log(1 - target) / Math.log(1 - a1))));
```

### 6-8. 보기 옵션 (F6) — v1의 체험/비교 모드 대체

미화·연출 모드는 없다(1-2). 보기 옵션은 모두 **현실 조건을 재현**하는 것이다.

| 보기 | 배경 | 조명 처리 | 용도 |
|---|---|---|---|
| **지금 조명** (기본) | 원본 | 제품 색 × `lightRGBLinear` × 명암 | 거울로 보는 것과 같은 모습 |
| **표준 조명** | 분할 모델 background → 중성 회색(sRGB 128) | 화면 전체를 `lightRGBLinear`로 나눠 중립화, 제품은 원래 색 | 제품의 실제 색 판단 |
| **갈 곳 조명** | 원본 | 갈 곳 프리셋(낮 외출 D65 / 사무실 약 4000K / 저녁 실내 약 2700K / 사진 찍는 날 약 3200K)의 조명 색으로 대체, 적응도 D 반영 | "그 장소에서는 이렇게 보여요" |

- 추천 화면에는 보기와 관계없이 **실측 사진, 가진 제품 비교, 정확도 배지**를 항상 표시한다.
- 세 보기 모두 1-1, 1-3 준수. 보기 전환은 조명 유니폼과 배경 패스만 바꾸고 **UV 텍스처의 제품 색은 동일**해야 한다(테스트로 보장).
- 링라이트·무대 연출, 배경 흐림, 분위기 배경은 넣지 않는다.

### 6-9. 제품 매칭 (F7)
- 입력: 목표 효과(`LookStep`) + 사용자 피부·입술 Lab + 갈 곳 조명.
- 각 제품 × 진하기 α∈{0.3, 0.4, …, 0.9}에 대해 예상 입술 색 계산(초기: 선형 혼합, 이후 발색 보정 모델로 교체 가능한 인터페이스).
- `score = ΔE2000(예상, 목표) + texturePenalty + (partner ? 0 : unavailablePenalty)`; 상위 3개.
- `measureMethod`가 placeholder/estimated면 결과에 표시.
- "가진 제품 비교" 문구: 두 Lab의 ΔL(밝기), Δh(색상각)로 규칙 기반 문장 생성("한 톤 진해요", "조금 더 붉어요").

### 6-9-2. 유사 제품 추천 (F7-2) — 지금 AR 색 기준

**기준 색**
- "지금 AR 색" = 지금 보고 있는 제품이 지금 진하기로 **내 입술 위에 표준 조명에서** 보일 예상 Lab(WebView가 `current_look.labStandard`로 보냄).
- 지금 조명을 기준으로 하면 방 조명 때문에 순위가 바뀌므로, 비교는 언제나 표준 조명에서 한다.
- 각 후보는 진하기 α∈{0.3, 0.4, …, 0.9}(6-9와 같음) 중 기준 색에 가장 가까운 값으로 계산하고, 화면에는 "약 N번 바르면 이 색"(6-7)으로 보여 준다.
- 지금 보고 있는 셰이드는 후보에서 뺀다. 같은 제품의 다른 셰이드는 후보에 넣는다.

**점수**
```ts
colorScore = ΔE2000(후보 예상 색, 지금 AR 색) + texturePenalty(기준 제형, 후보 제형)
rankScore  = colorScore + (partner ? 0 : unavailablePenalty)
```
- 묶음(아래 표)은 `colorScore`로 정하고, 같은 묶음 안의 순서는 `rankScore`로 정한다(1-14).
- `unavailablePenalty`는 6-9와 같은 설정값을 쓴다(초기값 2, `constants/similarity.ts`).

**제형 축과 벌점 (초기값, ΔE 단위, `constants/similarity.ts`. 트랙 B·E 결과로 조정)**

제형은 기존 7종을 그대로 쓴다. 광택 정도에 따라 한 줄로 세우고(`TEXTURE_AXIS`), 축에서 떨어진 칸 수만큼 벌점을 준다. 순서는 기존 AR 페이지 `TEXTURES`의 gloss 값(matte 0 · velvet 0 · cream 0.3 · satin 0.5 · sheer 0.6 · glossy 1)을 근거로 했다. `shimmer`(반짝이 입자)는 광택 축과 다른 성질이라 축 밖에 둔다.

```
TEXTURE_AXIS = matte → velvet → cream → satin → sheer → glossy     (shimmer는 축 밖)
penalty = min(6, 1.2 × 축에서 떨어진 칸 수),  shimmer ↔ 다른 제형 = 6,  같은 제형 = 0
```

| 기준 \ 후보 | matte | velvet | cream | satin | sheer | glossy | shimmer |
|---|---|---|---|---|---|---|---|
| matte | 0 | 1.2 | 2.4 | 3.6 | 4.8 | 6 | 6 |
| velvet | 1.2 | 0 | 1.2 | 2.4 | 3.6 | 4.8 | 6 |
| cream | 2.4 | 1.2 | 0 | 1.2 | 2.4 | 3.6 | 6 |
| satin | 3.6 | 2.4 | 1.2 | 0 | 1.2 | 2.4 | 6 |
| sheer | 4.8 | 3.6 | 2.4 | 1.2 | 0 | 1.2 | 6 |
| glossy | 6 | 4.8 | 3.6 | 2.4 | 1.2 | 0 | 6 |
| shimmer | 6 | 6 | 6 | 6 | 6 | 6 | 0 |

- 표는 수식으로 만들지 말고 `constants/similarity.ts`에 **표 그대로** 둔다. 나중에 칸 하나만 바꿀 수 있어야 한다(예: sheer는 투명도 차이 때문에 따로 올리기).
- `textureShift`: "더 매트한 걸로" → 축에서 matte 쪽으로 한 칸, "더 촉촉한/글로시한 걸로" → glossy 쪽으로 한 칸. 기준이 `shimmer`면 축 위치를 `satin`으로 보고 옮긴다. 축 끝이면 그대로 두고 reasonCode `NO_MORE_SHIFT`.

**묶음 (숫자 표시 금지, 1-9)**

| 묶음 | 조건 (초기값) |
|---|---|
| 거의 같아요 | ΔE2000 < 4 이고 같은 제형 (따라 바르기 기준 4와 맞춤, 6-10) |
| 비슷해요 | colorScore < 8 |
| 조금 달라요 | colorScore < 12 |
| (숨김) | colorScore ≥ 12 |

- 제품마다 차이를 한 줄로 붙인다(`reasonPhrases.ts`, ΔL·Δh·제형 규칙). 예: "한 톤 진해요", "조금 더 촉촉해요".
- 제휴 제품에는 "제휴" 표시를 붙인다.

**정렬 순서**
```
정렬 키 = (측정 그룹, 묶음, rankScore)
  측정 그룹 0: measured, user_verified
  측정 그룹 1: estimated → "측정 전" 표시 후 뒤로
  placeholder: DEV 플래그에서만 보임
```
- 측정 그룹 0이 비어 있으면 "아직 실제로 발라 보며 측정하지 않은 제품이에요" 안내를 붙인다.

**대화로 조건 바꾸기 (6-13과 같은 방식)**

| 발화 | LLM 출력 (Command) | 수식이 하는 일 |
|---|---|---|
| "이거랑 비슷한 거 있어?" | `find_similar{part: focusPart}` | 위 점수로 정렬 |
| "더 매트한 걸로" | `textureShift: "more_matte"` | 기준 제형을 축에서 한 칸 옮겨 벌점 재계산 |
| "벨벳으로" | `texture: "velvet"` | 기준 제형을 velvet으로 바꿔 벌점 재계산 |
| "반짝이는 건 빼줘" | `excludeShimmer: true` | shimmer 제외 |
| "만 원대로" | `priceMin: 10000, priceMax: 19999` | 가격으로 거르고 같은 수식으로 정렬 |
| "더 싼 거" | `priceDir: "cheaper"` | 지금 제품보다 싼 것만 |
| "조건 다 빼줘" | `reset: true` | `similarFilter` 초기화 |
| "두 번째 거 발라줘" | `select_candidate{index: 2}` | `candidateList[1]` 적용, 레시피 버전 +1 |

- 조건은 `similarFilter`에 쌓인다("만 원대로" → "더 매트한 걸로" = 두 조건 모두 적용).
- LLM 출력에 제품명·브랜드·색 코드가 있으면 거부한다. 금액 숫자는 사용자가 말했을 때만 허용하고 범위를 검사한다.
- `priceKRW`가 없는 제품은 가격 조건이 있을 때 제외하고, 조건이 없을 때는 "가격 확인 전"으로 표시한다.
- 결과가 비면 수식이 어느 조건을 풀면 결과가 생기는지 계산해 reasonCode로 넘기고, LLM은 그것만 문장으로 바꾼다. 예: "만 원대에서는 매트 제형이 없어요. 벨벳까지 볼까요?"
- reasonCodes: `SAME_TEXTURE`, `NEIGHBOR_TEXTURE`, `DEEPER`, `LIGHTER`, `REDDER`, `MORE_CORAL`, `NOT_MEASURED`, `PARTNER`, `NO_RESULT_PRICE`, `NO_RESULT_TEXTURE`, `NO_MORE_SHIFT`

**값 변경·제거 규칙**
- 벌점은 "얼마나 다른가"를 ΔE와 같은 단위로 더하는 값이다(작을수록 비슷함). 내부 계산 전용이며 화면에 표시하지 않는다(1-9).
- 모든 값은 `constants/similarity.ts`에 두고 코드에 직접 쓰지 않는다. 값을 0으로 바꾸면 그 항목은 계산에서 빠진 것과 같으므로 코드 수정 없이 끌 수 있어야 한다.

| 항목 | 값 변경 | 제거 | 제거 시 동작 |
|---|---|---|---|
| ΔE2000 (색 차이) | 공식 고정 | 불가 | 유사 추천의 기준이므로 항상 사용 |
| 제형 벌점 | 가능 | 가능 (표 전체 0) | 색만으로 정렬. `textureShift`·`texture`·`excludeShimmer` 대화 조건은 필터로 계속 동작 |
| 제휴 벌점 (`unavailablePenalty`) | 가능 | 가능 (0) | 색·제형만으로 순서 결정. "제휴" 표시는 유지 |
| 묶음 기준 (4 / 8 / 12) | 가능 | 묶음 이름은 유지 | 기준값만 바꾼다. 묶음이 없으면 비슷한 정도를 말로 보여 줄 수 없음(점수 표시 금지) |

- 테스트는 특정 숫자가 아니라 **동작**을 확인한다. 예: "제휴 벌점이 묶음을 바꾸지 않는다", "조명을 바꿔도 순서가 같다", "벌점을 0으로 두면 ΔE 순서와 같다". 값을 바꿔도 테스트가 깨지지 않아야 한다.
- 값을 바꿀 때는 `constants/similarity.ts`에 바꾼 날짜와 근거(예: "R4 NDCG@3 결과")를 `_changelog` 배열로 남긴다.

### 6-10. 따라 바르기 모드 (F8)
1. 시작 시 맨입술 Lab 측정(입술 마스크 중앙값, 하이라이트·그림자 제외), 조명 보정 유지.
2. 작은 창에 AR 목표, 본 화면은 거울(AR 꺼짐).
3. HandLandmarker로 손 21점 검출. 손 바운딩 박스가 입술 영역과 겹치면 측정 중지.
4. 손이 떨어지고 얼굴 정점 이동량이 임계값 이하로 **1초 이상** 유지되면 15프레임 평균으로 입술 Lab 측정.
5. 목표 대비 비교 → `guidance.ts` 규칙:
   - 진하기 부족 → "목표보다 연해요, 한 번 더 바르세요"
   - ΔE2000 < 임계값(초기 4) → "거의 같아요"
   - 색상각 차이 큼 → "다음엔 ○○ 제품이 더 가까워요"
6. 종료 시 `UserProductCalibration`을 호스트로 보내 `store/calibrationStore.ts`에 저장(AsyncStorage, 숫자만). 다음 렌더부터 `labOffset`, `a1User` 반영.
7. 점수·퍼센트 표시 금지(1-9).

### 6-11. 기기 성능 단계 (F9)
- 시작 3초 평균 FPS 측정 → 24fps 미만이면 한 단계 하향, 이후 10초마다 재평가.
- MediaPipe GPU 실행이 실패하면(WebView에서 생길 수 있음) CPU로 바꾸고 `low`에서 시작한다. 24fps 기준과 분할 주기는 M0-E·M9 실측 후 조정한다(11장).

| 단계 | 처리 |
|---|---|
| high | 전체 + 노이즈 맞추기 + (플래그 시) face-parsing |
| mid | 노이즈 맞추기 생략, 분할 모델 2프레임마다 |
| low | 처리 해상도 0.5배, 분할 모델 4프레임마다 |

- **색 계산 경로(6-5, 6-7, 6-9)는 모든 단계에서 동일.** 단계가 바꾸는 건 정밀도·질감뿐.

### 6-12. 레시피 추출 (F10, 서버)

**A. 유튜브 영상 (사전 작업, 룩마다 한 번)**
1. YouTube Data API로 룩마다 영상 약 10개 선정(영상 다운로드 금지, ID·제목·채널만 저장, 30일마다 갱신).
2. Gemini 영상 이해 + 구조화 출력: `RecipeStep` 스키마를 response schema로 강제. 부위·기법·색 계열은 **고정 선택지**에서만, 불확실하면 `"unknown"`.
3. `server/recipe/vote.ts`: 단계 등장 비율 60% 이상 필수, 30~60% 선택(`optional`), 30% 미만 제외. 색 계열은 다수결, HEX는 팀 팔레트에서 지정.
4. 결과 `Recipe`(`source: "youtube_vote"`)를 저장. 인물 이름은 내부 검색 키워드로만, `conceptName`에는 넣지 않는다.

**B. 사용자 참고 이미지 (요청 시)**
1. 클라이언트가 이미지를 서버로 전송(사용자 본인 얼굴 카메라 프레임은 금지, 1-4).
2. 서버는 메모리에서 VLM 호출 → `Recipe`(`source: "user_image"`) 반환 → **이미지 즉시 폐기, 로그에도 남기지 않음**(1-11).
3. 이미지 한 장이라 교차검증이 없으므로 `confidence`를 낮게 두고 UI에 "이미지 한 장 기준 추정 레시피"로 표시.
4. 화면에 원본 이미지를 다시 보여 주지 않는다.

**C. 공통**
- 레시피 추출 정확도는 트랙 C로 평가(8장).
- 클라이언트 `applyRecipe.ts`가 `Recipe`를 UV 텍스처 파라미터로 변환. 사용자 피부톤 반영(목표 효과 재계산)은 수식으로.

### 6-13. 대화형 조정 (F11, 서버 + 클라이언트)

**흐름**
```
사용자 발화(텍스트, 이후 음성)
  → 서버 `app/api/dialog+api.ts` → `server/dialog/toCommands.ts`: 발화 + DialogState 요약(현재 레시피, focusPart, 최근 3턴) → LLM 함수 호출
  → Command[] 반환 (5장 Command 타입만 허용, 스키마 검증 실패 시 되묻기)
  → 클라이언트 commands.ts: 명령을 수식으로 실행 → 새 레시피 버전 → AR 갱신
  → (선택) explain: 계산 모듈이 reasonCodes 생성 → LLM이 reasonCodes만으로 한두 문장
```

**규칙**
- LLM은 제품명, 색 코드, 숫자 진하기를 **직접 만들지 않는다.** `delta`/`dir` 같은 방향만 정하고 크기는 수식이 정한다(1-5). 예외: 사용자가 숫자를 말한 경우("반만 연하게")만 `value` 허용, 범위 검사.
- **참조 해석:** "아까보다" → `recipeHistory` 직전 버전 기준. "이거", "여기" → `focusPart`. "아까로 돌려줘" → `undo`.
- **"내 피부톤에 어울리게"** → `match_skin_tone`: 부위별 피부 Lab(6-6)과 목표 효과로 색을 수식 재계산.
- 해석이 애매하면 명령을 만들지 말고 되묻는다("아이라인을 말씀하신 건가요, 섀도인가요?").
- 서버에는 발화 텍스트와 레시피 숫자만 보낸다. 얼굴 데이터 없음.
- `server/llm/adapter.ts`로 API 모델을 교체 가능하게 한다. 로컬 모델(Qwen2.5-7B-Instruct)은 별도 실행 서비스가 필요하므로 11장 결정 후 어댑터에 붙인다.

**음성 (F12, 후순위):** Whisper를 기기에서 돌려 텍스트로 바꾼 뒤 같은 경로로 보낸다. WebView에서 속도가 부족하면 녹음(expo-audio)을 서버 Whisper로 보내는 방식을 검토한다. 이 경우 1-4에 "음성도 저장하지 않음"을 추가한다(11장 결정 사항).

### 6-14. 행동 이벤트 기록 (F15)
- 설정·동의 화면에서 사용자가 켰을 때만 기록한다. 기본값은 꺼짐.
- 5장 `AppEvent`만 기록한다. 숫자·ID·시각만 남기고 이미지, 얼굴 측정값, 발화 원문은 넣지 않는다.
- 저장은 기기 안(`lib/storage.ts`의 AsyncStorage, 키 `kb.events.v1`)에만 한다. 평가용으로는 디버그 메뉴의 "기록 내보내기(JSON)"로만 꺼낸다.
- **추천 계산에는 아직 쓰지 않는다.** 트랙 E 평가(클릭·선택률)와, 나중에 ML 랭킹으로 바꿀 때의 학습 데이터 후보로만 쓴다.
- "기록 지우기" 버튼으로 바로 전부 지울 수 있어야 한다.


### 6-15. 데이터 가져오기 (D)

어제 정리한 데이터 출처(「K-뷰티 AR 데이터 출처 검토와 DB 구성」)를 저장소로 가져오는 방법이다. **확인된 합법 출처만** 쓰고, 모르는 값은 비워 둔다.

**공통 규칙**
- 판매 플랫폼(예: 올리브영)에서 팀이 수집한 제품·셰이드·색 데이터는 **개발자 PC에서 가져오기 스크립트로** 카탈로그에 넣을 수 있다(`scripts/data/import_oliveyoung.py`). 색은 추정값(`measureMethod: 'estimated'`)으로 두고 출처 페이지와 수집 날짜를 남긴다. 가격처럼 시트에 없는 값은 지어내지 않는다(`priceKRW: 0`, `price-unchecked` 태그).
- 판매 플랫폼의 이미지 파일·이미지 주소와 리뷰 원문은 카탈로그에 넣지 않는다. 쓰는 것은 추출한 색 값과 제형 판정 결과뿐이다.
- 브랜드 공식몰 정보(셰이드 이름, 전성분, 참고 가격)는 **사람이 화면에서 확인해 직접 입력**한다(또는 브랜드 허락). 자동 대량 수집 금지. 공식몰 이미지는 가져오지 않는다.
- 가져온 값마다 출처 주소와 확인 날짜를 남긴다(`sourceUrl`, `checkedAt`).
- 없는 값은 지어내지 않는다. 빈칸은 `undefined`로 두고, 스크립트가 빈칸 목록을 보고한다.
- 전성분 **순서·함량**으로 발색·투명도(a1)·착색을 계산하지 않는다(1% 이하 성분과 착색제는 순서 무관 표시). 성분은 "들어 있다 / 없다"만 쓴다.
- 가져오기 스크립트는 **개발자 PC에서만** 실행한다. 앱이나 AR 페이지가 실행 중에 외부 데이터를 긁어 오지 않는다(기존 네이버·YouTube API 라우트는 예외, 6-0).
- 키는 `.env`(서버 전용)에 둔다. `EXPO_PUBLIC_` 금지. `.env.example`에 이름만 추가한다.

**출처별 가져오는 방법**

| 데이터 (어제 DB 이름) | 출처 | 가져오는 방법 | 저장 위치 | 앱에서 쓰는 곳 |
|---|---|---|---|---|
| 제품·셰이드 목록 (products, shade_catalog) | 브랜드 공식몰 (예: 힌스 무드인핸서 립 글로우 5종) | **수동 입력**. 제품명·한글명·카테고리·참고 가격·셰이드 이름·공식몰 hex. 제형은 제조사 표현을 `textureLabel`에 그대로 적고, 7종 중 하나를 사람이 골라 `texture`와 근거(`textureNote`)를 남김. 이름만으로 정하지 않음(예: "글로우"는 설명 확인 필요). `measureMethod: 'estimated'` | `data/catalog/products.ts` [기존] | 제품 목록, AR(측정 전 색), 유사 추천 |
| 판매처 가격·상품 이미지 (products) | 네이버 검색 API (쇼핑) | **기존 `server/naver.ts`가 실행 중에 조회**(`/api/products/[id]/offers`). 카탈로그로 대량 복사하지 않는다. 쇼핑 검색이 `SE05`를 반환하는 문제는 `docs/LAUNCH_CHECKLIST.md` 2번 | 서버 캐시 | 제품 상세 판매처, 가격 조건(참고 가격 우선) |
| ★ 셰이드 측정값 (shade_measurements) | 숙제 01 직접 측정 | CSV → `scripts/data/import_measurements.py` → JSON. **`server/catalog.ts`가 불러올 때 `Shade`에 합친다**(products.ts를 스크립트가 고쳐 쓰지 않음) | 원본 `research/data/measurements/*.csv` → `data/catalog/measurements.json` | AR 색, 진하기↔횟수, 유사 추천, 트랙 B |
| 성분 표준명 (ingredient_master) | 식약처 화장품 원료성분정보 API (공공데이터포털) | `scripts/data/import_mfds_ingredients.py` | `data/ingredients/master.json` (서버 전용) | 전성분 정규화 |
| 사용 제한 성분 (ingredient_restrictions) | 식약처 화장품 사용제한 원료정보 API | `scripts/data/import_mfds_restrictions.py` | `data/ingredients/restrictions.json` (서버 전용) | 제한 성분 표시 |
| 제품별 전성분 (product_ingredients) | 공식몰 상품정보제공고시 | **수동**: 화면의 전성분을 텍스트로 옮겨 적음 → `scripts/data/normalize_ingredients.py`가 표준명으로 맞춤, 못 맞춘 성분 목록 보고 | 원본 `data/ingredients/raw/<productId>.txt` → `data/ingredients/products.json` | 성분 플래그 |
| 성분 플래그 (ingredient_flags) | 위 두 데이터 | 코드로 판정(`server/ingredients/flags.ts`). 티타늄디옥사이드, 산화철, 타르색소(종류별), 멘톨, 변성알코올, 향료 | 계산 (저장 안 함) | 제품 상세 "멘톨이 들어 있어요" (사실만) |
| 피부톤 기준 (skin_tone_reference) | Google Monk Skin Tone | `scripts/data/import_monk.py` (10단계 HEX → Lab) | `scripts/eval/reference/monk.json` | **평가 집계에만**(8장). 추천에 안 씀 |
| 해외 셰이드 (global_shade_reference) | The Pudding makeup-shades, Makeup API | `scripts/data/import_reference.py` | `research/data/reference/` (저장소 제외) | 분석 참고만. AR·추천에 안 씀. 라이선스 표기 없음 → 내부 분석만 |
| 해외 제품·성분 (global_products_reference) | Open Beauty Facts 덤프, Kaggle(Sephora 리뷰·전체, 피부타입) | 직접 내려받아 `research/data/reference/`에 둠 (Kaggle은 로그인 필요) | `research/data/reference/` (저장소 제외) | 분석 참고만. OBF는 ODbL(DB)·CC-BY-SA(이미지), Kaggle은 라이선스 표기 없음 → 재배포 금지 |
| 조명 추정 비교용 정답 데이터 | [Cube++](https://zenodo.org/records/4153431) (CC BY 4.0, 4,890장, 정답 조명값), 간이판 SimpleCube++ 약 2GB | 직접 내려받음 | `research/data/reference/cubepp/` (저장소 제외) | R2-6 비교만. 출처 표시 |
| 사용자 보정 (user_calibration) | 따라 바르기 (F8) | 앱이 기기에 저장 | `store/calibrationStore.ts` (AsyncStorage) | 사용자별 발색 보정 |

#### 6-15-2. 색 추출과 제형 판정 (측정 전 제품)

직접 측정(`measured`)하기 전 제품의 색과 제형을 정하는 방법이다. 이렇게 정한 값은 모두 **추정값**이다: 색은 `measureMethod: 'estimated'`, 제형은 `textureConfidence`로 표시한다(1-8). 측정값이 생기면 항상 측정값이 우선한다.

**출처 조건 (먼저 확인)**
- 아래 방법 중 **리뷰 AI 요약, 리뷰 설문 통계, 판매 플랫폼의 컬러칩·색상비교 이미지**는 판매 플랫폼(예: 올리브영) 상품 페이지에 있는 정보다. 팀이 수집한 데이터를 6-15 공통 규칙대로 가져와 쓴다(추정값 표시, 이미지·리뷰 원문 미저장). 수집 데이터가 없는 제품은 각 단계의 **대안**을 쓴다.
- 브랜드 공식몰의 컬러칩·색상비교 이미지는 사람이 화면에서 보고 값을 뽑는 데만 쓴다. 이미지 파일은 저장하거나 앱에 넣지 않고, 뽑은 값과 출처 주소·날짜만 남긴다.
- 리뷰 원문은 저장하지 않는다. 쓰는 것은 집계 결과(비율)나 제형 판정 결과뿐이다.

**① 색 추출**

| 순위 | 방법 | 출처 | 신뢰도 | `colorSource` |
|---|---|---|---|---|
| 0 | **직접 측정** (숙제 01, 6-15 CSV) | 팀 | 가장 높음 | `measured` |
| 1 | **옵션 컬러칩 이미지** | 브랜드 공식몰, 판매 플랫폼 수집 데이터 | 중간 | `option_chip` |
| 2 | **색상비교 이미지** (발색 비교, 스와치 사진) | 위와 같음 | 낮음 | `color_compare` |
| 대안 | 공식몰에 적힌 HEX·색상명(텍스트) | 브랜드 공식몰 | 낮음 | `official_hex` |
| 대안 | 팀이 매장 테스터를 같은 측정 환경으로 촬영 | 팀 | 측정에 준함 | `measured` (`setupId` 기록) |

- **추출 방법 (1·2순위 공통, `scripts/data/extract_chip_color.py`):** 칩(또는 발색 부분) 안쪽 영역만 사람이 상자로 지정 → 가장자리·글자·그림자·하이라이트 픽셀 제외 → **중앙값** sRGB → 6-5와 같은 변환으로 Lab. 결과는 `Shade.hex`, `Shade.labEstimated`에 넣는다.
- 컬러칩은 사진이 아니라 브랜드가 만든 그래픽일 수 있어서 실제 발색과 다를 수 있다. 색상비교 이미지는 촬영 조명·보정 영향을 받는다. 그래서 둘 다 `estimated`이고, 화면에 "측정 전" 표시를 붙인다.
- 색상비교 이미지 한 장에 여러 셰이드가 있으면 **셰이드끼리 밝기·색상 순서**를 확인하는 데 쓴다(절대 색보다 상대 비교가 더 믿을 만함).
- 1순위와 2순위 값의 차이(ΔE2000)가 크면(초기 기준 10, 설정값) 둘 다 쓰지 않고 "측정 필요" 목록에 올린다.

**② 제형 판정 (7종: matte / velvet / cream / satin / sheer / glossy / shimmer)**

| 순위 | 방법 | 출처 | `textureSource` | 신뢰도 |
|---|---|---|---|---|
| 0 | **직접 측정·팀 판정**: `glossMeasured`(6-15 CSV) 또는 팀 패널(아래 대안) | 팀 | `measured` / `team_panel` | 높음 |
| 1 | **상품명 키워드** | 상품명 (공식몰, 네이버 쇼핑 API 상품명) | `name_keyword` | 중간 |
| 2 | **리뷰 AI 요약에 직접 정리된 제형** | 판매 플랫폼 수집 데이터 | `review_summary` | 중간 |
| 3 | **리뷰 설문 통계**: 수분감 촉촉/보통/매트 비율로 추정. 아이섀도는 펄감 비율 | 판매 플랫폼 수집 데이터 | `review_survey` | 낮음 |
| 대안 (2순위 대신) | **공식몰 상품 설명의 제형 표현** ("보송한 매트 피니시", "촉촉한 광택" 등) | 브랜드 공식몰 (수동) | `official_description` | 중간 |
| 대안 (3순위 대신) | **팀 패널 판정**: 팀원 3명 이상이 직접 발라 보고 7종 중 하나를 고름, 다수결 | 팀 | `team_panel` | 높음 |
| 대안 (마지막) | **측정 광택**: 같은 측정 환경에서 `glossMeasured`로 축 위치 결정 | 팀 | `measured` | 높음 |

**1순위: 상품명 키워드 사전 (`constants/textureKeywords.ts`, 한국어·영어)**

| 제형 | 확정 키워드 (예) |
|---|---|
| matte | 매트, matte, 블러, blur, 보송, 파우더리, powder |
| velvet | 벨벳, velvet |
| cream | 크림, 크리미, cream, creamy |
| satin | 새틴, satin, 세미매트 |
| sheer | 시어, sheer |
| glossy | 글로시, 글로스, glossy, gloss, 물광, 워터, water, 젤리, jelly |
| shimmer | 쉬머, shimmer, 펄, pearl, 글리터, glitter, 스파클, sparkle |

- **애매한 키워드는 판정하지 않고 다음 순위로 넘긴다:** 글로우(glow), 틴트(tint), 립밤, 오일(oil), 듀이(dewy), 촉촉 등. 예: "무드인핸서 립 **글로우**" → 1순위 판정 없음 → 2순위(또는 대안)로.
- 서로 다른 제형 키워드가 두 개 이상이면(예: "매트 글로스") 판정하지 않고 다음 순위로 넘긴다.
- 사전은 표 그대로 두고, 바꿀 때는 `_changelog`에 날짜와 근거를 남긴다.

**2순위: 리뷰 AI 요약**
- 요약 문장에 제형이 **직접** 적혀 있을 때만 쓴다(예: "매트하게 마무리돼요"). 1순위 키워드 사전으로 판정하고, 애매하면 다음 순위로 넘긴다.
- 요약 문장 자체는 저장하지 않고 판정 결과와 출처·날짜만 남긴다.

**3순위: 리뷰 설문 통계 — 초기 기준, `constants/textureRules.ts`에서 조정**

| 대상 | 조건 (응답 수 30개 이상일 때만) | 판정 |
|---|---|---|
| 립·베이스 (수분감) | 매트 ≥ 50% | matte |
| | 매트 30~50% 이고 촉촉 < 30% | velvet |
| | 보통이 가장 많음 | satin |
| | 촉촉 50~70% | cream |
| | 촉촉 ≥ 70% | glossy |
| 아이섀도 (펄감) | 펄 많음 + 펄 적당 ≥ 50% | shimmer |
| | 펄 없음 ≥ 50% | matte |
| | 그 외 | satin |

- `sheer`(투명한 발색)는 수분감 비율만으로 정할 수 없다. 3순위로는 sheer를 판정하지 않는다.
- 응답 수가 30개 미만이면 판정하지 않는다.

**판정 결과가 없을 때**
- 모든 순위에서 판정이 안 되면 `texture: 'satin'`(제형 축의 가운데, 다른 제형과의 벌점 최댓값이 가장 작음), `textureSource: 'default'`, `textureConfidence: 'low'`로 두고 "제형 추정" 표시를 붙인다. "측정 필요" 목록에도 올린다.

**우선순위 정리**
```
색:   measured > user_verified > option_chip > color_compare > official_hex > placeholder
제형: measured / team_panel > name_keyword > official_description ≈ review_summary > review_survey > default
```
- 높은 순위 값이 있으면 낮은 순위 값은 덮어쓰지 않는다. 순위끼리 결과가 다르면 높은 순위를 쓰고, 차이를 "검토 필요" 목록에 남긴다.
- 판정 정확도는 팀 패널·측정값을 정답으로 보고 트랙 E `e_texture.py`에서 순위별 일치율로 평가한다.

#### 6-15-3. 측정 CSV 형식 (`research/data/measurements/YYYY-MM-DD.csv`)

| 열 | 필수 | 설명 |
|---|---|---|
| `productId`, `shadeId` | ✅ | `data/catalog/products.ts`의 id와 같아야 함. 없는 id면 가져오지 않고 보고 |
| `paper_L`, `paper_a`, `paper_b` | ✅ | 같은 사진의 맨 종이 Lab (a1 계산용) |
| `x1_L`, `x1_a`, `x1_b` | ✅ | 1번 바른 색 |
| `x3_L`, `x3_a`, `x3_b` | 선택 | 3번 바른 색. 있으면 a1 계산 |
| `after30_L`, `after30_a`, `after30_b` | 선택 | 30분 뒤 색 (틴트) |
| `device`, `measuredAt`, `light` | ✅ | 기종, 날짜, 조명 메모 |
| `fixedSetup` | ✅ | 측정 환경(같은 장소·같은 조명·카메라 노출·화이트밸런스 고정)을 지켰으면 `yes`. `yes`일 때만 `measured`로 가져오고 `no`면 보고 |
| `setupId` | ✅ | 측정 환경 이름 (예: `room1-lamp5000k-galaxyS24`). 같은 `setupId`끼리만 직접 비교한다 |
| `gloss_highlight_ratio` | 선택 | 광택 측정: 고정 조명에서 입술(또는 발색 부분) 중 하이라이트 픽셀 비율. 스크립트가 0~1로 정규화해 `glossMeasured`로 넣음 |
| `note` | 선택 | 메모 |

- Lab은 고정 측정 환경에서 찍은 사진을 6-5와 같은 변환(D65)으로 바꾼 값이다. 흰 종이로 조명을 보정하지 않으므로, 서로 다른 `setupId`의 값을 섞어 평균 내지 않는다. 사진에서 Lab을 뽑는 방법은 트랙 B 스크립트와 같은 함수를 쓴다.
- **a1 계산:** 선형 RGB에서 종이 색 W, 1회 C1, 3회 C3를 두고 `|C1−W| / |C3−W| = a1 / (1−(1−a1)^3)`을 수치로 푼다. 3회 값이 없으면 a1을 비워 두고 앱은 "약 N번" 문구를 숨긴다(6-7).
- 같은 셰이드를 여러 번 잰 행은 평균하고 측정 횟수를 `measureCount`로 남긴다.

**데이터 크기와 노출**
- `data/ingredients/`는 `server/`에서만 import한다. 앱 번들에 들어가지 않는지 확인하는 테스트를 둔다(기존 README의 "빌드 결과물 검사"와 같은 방식).
- 앱에는 API 응답으로 해당 제품의 플래그만 보낸다.


### 6-16. 기초화장품 추천 (F16) — MVP 후순위 (M14)

**연결 근거 (멘토 피드백 ③):** AR로 바른 색조 제품이 아니라, **사용자가 직접 써 본 제품의 경험 + 성분 사실 + 사용자가 직접 답한 피부 타입**을 근거로 추천한다. 얼굴 사진으로 피부를 분석하지 않는다(1-4, 10장). AR 사용 기록(F15)도 추천 계산에 쓰지 않는다.

**들어오는 길 (둘 다)**
1. 룩 저장 직후 제안 (선택): "저장했어요. 피부 타입에 맞는 기초도 같이 볼까요?" — 거절하면 다시 묻지 않는다(설정에서 끌 수 있음).
2. 쇼핑 탭 → 기존 `app/ingredients.tsx` "좋았던 성분으로 스킨케어 찾기" 화면에 동작을 붙인다.

**① 피부 타입 질문 (`app/skin-profile.tsx`, 질문은 `constants/skinQuestions.ts`)**
- 1단계: 건성 / 지성 / 복합성 / 중성 / 잘 모르겠어요 (버튼).
- 2단계: 답에 따라 최대 2~3개. 예) 건성 → "세안 후 바로 당기나요?", 지성 → "얼굴 전체가 번들거려요, T존만 그래요?"(복합성 재확인), 모르겠어요 → 짧은 질문 2개 후 결과에 "추정" 표시.
- 공통: "따갑거나 붉어진 적이 있는 제품이 있나요?" → 있으면 ③으로.
- 질문은 정해진 목록에서만 나간다. MVP는 버튼으로 답한다. 자유 입력(대화)은 M11 이후 LLM이 답을 정해진 선택지로 바꾸는 일만 한다(1-5).
- 결과 문구는 "직접 알려 주신 피부 타입: 건성"처럼 사용자가 말한 것임을 드러낸다. "진단", "분석 결과" 같은 말을 쓰지 않는다.

**② 써 본 제품 등록**
- 카탈로그에서 써 본 기초 제품을 고르고 "좋았어요 / 안 맞았어요"를 표시한다(선택 사항, 없어도 추천 가능).

**③ 피하고 싶은 성분**
- 사용자가 직접 고른 성분(예: 향료, 변성알코올, 멘톨 — `IngredientFlag`).
- "안 맞았어요" 제품에만 있고 "좋았어요" 제품에는 없는 성분을 **후보로 보여 주고, 사용자가 확인한 것만** 피하고 싶은 성분에 넣는다. 자동으로 단정하지 않는다.

**④ 계산 (`lib/reco/skincare.ts` + `app/api/skincare/recommend+api.ts`, 수식, AI 불필요)**
```
후보 = category ∈ {skincare, suncare}, 같은 세부 종류(subCategory)면 우선
제외 = 피하고 싶은 성분이 들어 있는 제품
피부 타입 = product.skinTypes에 사용자 타입 또는 'all'이 있으면 통과
            표기가 없으면 통과하되 "제조사 피부 타입 표기 없음" 표시
정렬 = 좋았던 제품이 있으면 성분 겹침 비율(공통 성분 수 ÷ 합친 성분 수) 높은 순
       없으면 피부 타입 일치 → 피하고 싶은 성분 없음 → 참고 가격 순
```
- 전성분 **순서·함량**으로 판단하지 않는다(6-15 공통 규칙).
- 성분 데이터는 서버 전용(`data/ingredients/`)이라 계산은 API 라우트에서 한다. 앱은 제품 id·피부 타입·피하고 싶은 성분 목록만 보내고, 서버는 저장·로그를 남기지 않는다.

**⑤ 근거 문장 — 세 유형만 허용 (i18n 네 언어)**

| 유형 | 예 |
|---|---|
| 제조사 표기 | "제조사가 건성 피부용으로 안내한 제품이에요" |
| 성분 겹침 | "좋았던 크림과 성분 15개 중 11개가 같아요" (개수는 사실이므로 표시 가능, 점수·퍼센트는 표시 안 함) |
| 피하고 싶은 성분 | "향료가 들어 있지 않아요" |

- **금지:** 효능·느낌을 단정하는 말 — "건성에 좋아요", "촉촉하게 유지", "트러블을 줄여요", "자극 없음", "같은 효과". 성분이 비슷하다고 효과가 같다고 말하지 않는다.
- "건성이면 ○○ 성분" 같은 성분↔피부 타입 규칙을 만들지 않는다. 필요하면 공신력 있는 출처가 있는 규칙만 별도 표로 만들고 문장에 출처를 함께 보여 준다(팀 결정, 11-1).

**⑥ 대화 (M11 이후 선택)**
- `Command`에 `{ op: 'find_skincare'; subCategory?: SkincareType; priceMax?: number; avoid?: IngredientFlag[] }`를 추가할 수 있다. LLM은 조건만, 정렬은 ④ 수식.

**⑦ 저장과 개인정보**
- 피부 타입·써 본 제품·피하고 싶은 성분은 `store/skinProfileStore.ts`(AsyncStorage, 키 `kb.skin.v1`)에 **기기 안에만** 저장한다. 처음 쓸 때 동의를 받고, 마이 탭에서 바로 지울 수 있어야 한다.
- 사용 기록(F15, 동의 시): `skincare_shown`, `skincare_selected` 이벤트만 숫자·ID로 남긴다. 피부 타입 값은 이벤트에 넣지 않는다.

**⑧ 데이터 (6-15에 추가)**
- `Product.subCategory`(토너·세럼·크림 등), `Product.skinTypeLabel`(제조사 원래 표현), `Product.skinTypes`(사람이 매핑, 근거는 `skinTypeNote`) — 공식몰에서 **수동 확인**. 립 셰이드를 확인할 때 같이 적는다.
- 제품별 전성분은 6-15의 `data/ingredients/raw/` 방식 그대로.


### 6-17. 추가 기능 (F17~F23) — MVP 다음 단계

MVP(7-1의 단계 1~4)가 끝난 뒤 진행한다. 모두 Realism 원칙(1장)을 그대로 따른다.

**F17. 30분 뒤 색 보기 (틴트 착색)**
- AR 화면에 "바른 직후 / 30분 뒤" 전환. 30분 뒤 색은 `Shade.labAfter30min`(측정값)만 쓴다.
- 측정값이 없는 셰이드는 전환 버튼을 숨긴다. 시간 변화를 추정해 지어내지 않는다.

**F18. 겹쳐 바르기 (레이어링)**
- 아래 층(예: 틴트)과 위 층(예: 글로스) 두 셰이드를 고른다. 아래 층 결과 색 위에 위 층을 위 층의 a1·진하기로 섞는다(6-7 공식, 선형 RGB).
- 광택·반짝이는 **위 층 제형**을 따른다. 두 셰이드 중 하나라도 측정 전이면 "추정" 표시.
- 고르는 곳: 내 립 서랍(F20) + 추천 목록.

**F19. 반반 비교**
- 입술을 좌우(얼굴 메시 중심선 기준)로 나눠 두 셰이드를 동시에 보여 준다. 기존 "누르고 비교"는 유지한다.
- 두 쪽은 같은 조명·같은 처리로 그린다. 한쪽만 보정하거나 다르게 그리지 않는다.
- **퍼스널컬러 진단은 하지 않는다.** 웜톤 색과 쿨톤 색을 반반 비교로 **직접 보게** 하는 것으로 대신한다(진단·판정 문구 금지).

**F20. 내 립 서랍 + 바로 담기**
- 가진 립을 카탈로그에서 골라 등록(기기 안 저장, `store/drawerStore.ts`, 키 `kb.drawer.v1`).
- 추천 목록에서 서랍의 립과 **ΔE2000 < 4이고 같은 제형**이면 "비슷한 색이 이미 있어요(제품명)" 표시. 순위는 바꾸지 않는다.
- AR 화면과 유사 추천 목록에서 **바로 담기**: 저장소의 `store/cartStore.ts`와 쇼핑 리스트(`checkout.tsx`, `lists/`)에 연결한다. 이 화면들의 기존 동작은 바꾸지 않고 진입만 추가한다.

**F21. 가격 기능**
- **듀프 가격 차이:** 유사 추천(F7-2)에서 "비슷한 색이에요. ○○원 더 저렴해요"(참고 가격 `priceKRW` 기준, 사실만). 가격 확인 날짜(`priceCheckedAt`)가 없으면 표시하지 않는다.
- **판매처 가격 비교:** 기존 `/api/products/[id]/offers`(네이버)를 제품 상세에 표시. 네이버 쇼핑 검색 `SE05` 오류가 해결된 뒤에만(11-1).
- **후보 (조건 충족 전 구현하지 않음):** 가격 알림(서버 정기 조회·알림 동의 필요), 택스리펀드 예상액(공식 기준을 확인한 뒤).

**F22. 여행 쇼핑 플래너**
- 쇼핑 리스트 총액 + 매장 선택·지도(저장소 기존 기능)를 한 화면 흐름으로 묶는다. 외국인 관광객 대상 문구는 i18n 네 언어.
- 택스리펀드 표시는 F21 후보 조건과 같다.

**F23. 구매 후 확인 + 지표 이벤트**
- 담은 제품에 대해 "실제로 발라 보셨나요? 따라 바르기로 확인해 볼까요?"를 앱 안에서 제안(푸시 알림은 동의 시에만).
- 따라 바르기 결과 화면에서 "AR에서 본 것과 비슷했나요?"(1~5)를 묻는다. 점수는 사용자 답이며 앱이 매긴 점수가 아니다(1-9와 충돌 없음).
- 이벤트(동의 시, 숫자·ID만): `added_to_cart`, `list_created`, `expectation_rating`, `drawer_added`, `layer_tried`, `split_compared`.

**후보로만 두는 것 (구현하지 않음, 오버립은 10-26에 룩 요청으로 구현 → 6-5-6):** 바르는 방법 비교(풀립·그라데이션·오버립 — 레시피 기법과 렌더링 난도가 커서 F13 이후 검토)


---

## 7. 마일스톤과 완료 기준

### 7-1. 진행 순서표 (0-A 절차가 이 순서를 따른다)

| 순서 | 마일스톤 | 단계 | 선행 | 사람이 준비할 것 |
|---|---|---|---|---|
| 1 | **S0** 명세서 연결 (0-B) | 0. 준비 | — | 이슈 번호, `docs/AR_SPEC.md` 복사 |
| 2 | M0 저장소 확인 | 1. 기반 (10/31 목표) | S0 | 이슈 번호 |
| 3 | M0-E Expo Go 연결 확인 | 1 | M0 | **아이폰·갤럭시 실기기** |
| 4 | M1 색 유틸 | 1 | M0 | — |
| 5 | M2 얼굴 추적 | 1 | M0-E | 실기기 FPS 확인 |
| 6 | M3 메시 + UV 렌더링 | 1 | M2 | 정면·30°·45° 확인 |
| 7 | M4 끊김 대응 | 2. AR 완성 | M3 | 실기기 확인 |
| 8 | M5 조명 자동 추정 | 2 | M3, M1 | 노란 조명 환경 |
| 9 | M6 진하기·보기 옵션 | 2 | M5 | — |
| 10 | M1-D 데이터 가져오기 (샘플) | 2 | M1 | — (가짜 샘플로 동작 확인) |
| 11 | M7 제품 매칭 | 3. 추천 | M6, M1-D | 공식몰 제품·셰이드 입력(힌스 5종 등) |
| 12 | M7-2 유사 제품 추천 | 3 | M7 | — |
| 13 | M7-3 사용 기록 | 3 | M7-2 | — |
| 14 | M8 따라 바르기 | 4. 부가 | M6 | 실제 립 바르기 확인 |
| 15 | M9 성능 단계 | 4 | M5 | 저사양 기기 |
| 16 | M10 레시피 추출 | 5. AI (키 필요) | M6 | **Gemini API 키**, YouTube 키 |
| 17 | M11 대화형 조정 | 5 | M7-2, M10 | **LLM API 키**, 대화 시나리오 20~30개 |
| 18 | M14 기초화장품 추천 | 6. 후순위 | M1-D(실데이터) | 기초 제품·전성분 입력, 공공데이터포털 키 |
| 19 | M12 아이라인 | 6 | M3 | — |
| 20 | M13 평가 | 6 | M7-2 | 숙제 01 사진·측정 CSV |
| 21 | M15 30분 뒤 색 (F17) | 7. MVP 다음 | M6 | `after30` 측정값 |
| 22 | M16 겹쳐 바르기 (F18) | 7 | M6 | — |
| 23 | M17 반반 비교 (F19) | 7 | M6 | — |
| 24 | M18 내 립 서랍 + 바로 담기 (F20) | 7 | M7-2 | — |
| 25 | M19 가격 기능 (F21) | 7 | M7-2 | 네이버 `SE05` 해결 (판매처 가격) |
| 26 | M20 여행 쇼핑 플래너 (F22) | 7 | M18 | 매장 데이터 검수 |
| 27 | M21 구매 후 확인 + 지표 (F23) | 7 | M8, M18 | — |

- **숙제 실험(R2·R4)과 M1-D 실데이터**는 앱 순서와 별개로, 사람이 데이터를 준비하고 `R2-1 진행`처럼 직접 요청할 때만 진행한다(8-A).
- 사람이 준비할 것이 없으면 그 마일스톤은 `보류`로 두고 다음으로 넘어간다. 예: 키가 없으면 M10·M11은 보류, M14·M12로.
- 단계 7(MVP 다음)은 단계 1~6이 끝나거나, 사람이 `Mx 진행`으로 직접 요청할 때 시작한다.

### 7-2. 완료 기준

| # | 내용 | 완료 기준 |
|---|---|---|
| **S0** | 명세서 연결 (0-B) | 이슈 브랜치에서 `docs/AR_SPEC.md` 추가, `AGENTS.md`에 안내 두 줄 추가(0-B 문구 그대로), `docs/AR_PROGRESS.md`를 0-A 형식으로 생성(7-1 전체 행, S0 `완료`), 코드 변경 없음, 커밋 두~세 개로 분리 |
| **M0** | 저장소 확인 | `develop` 최신에서 작업 브랜치 생성(`AGENTS.md` 규칙), `npm install` → `npx expo start`로 Expo Go 57 실행, 웹(`w`) 실행, `npm run check` 통과, 현재 AR 페이지 동작 확인. 기존 구조와 이 명세서가 다른 곳 목록 보고 |
| **M0-E** | Expo Go 연결 확인 (6-0) | iOS·Android 각각 아래 표 결과 + 기기 이름·OS 버전·FPS. 실패 항목은 원인. `bridgeProtocol.ts` 검증 추가. 평가용 렌더 저장 방법 제안(6-0) |
| **M1** | 색 유틸 | sRGB↔선형↔Lab 왕복 오차 < 1e-4, CIEDE2000이 Sharma(2005) 공개 테스트 쌍과 소수 4자리 일치, `layersFor` 단위 테스트 |
| **M1-D** | 데이터 가져오기 (6-15) | 컬러칩 색 추출(상자 지정·중앙값)과 제형 판정(키워드 사전, 애매·충돌 키워드는 다음 순위로, 판정 없음이면 default) 단위 테스트, 우선순위가 높은 값을 덮어쓰지 않는 테스트, 샘플 CSV로 `measurements.json` 생성(빈칸 그대로, 없는 id·보정 안 한 행 보고), a1 계산 단위 테스트, 식약처 키가 없으면 스크립트가 안내만 하고 종료, 키가 있으면 건수·날짜와 함께 JSON 생성, 전성분 정규화 실패 목록, 성분 플래그 단위 테스트, `data/ingredients`가 앱 번들에 없음 확인 |
| **M2** | 카메라 + 얼굴 추적 | 30fps 목표(노트북 기준), 랜드마크 디버그 오버레이, One Euro 적용 전후 흔들림 비교 수치 출력 |
| **M3** | 메시 + UV 렌더링 | 표준 모델 UV 생성 스크립트, 립 텍스처가 정면·30°·45°에서 입술에 붙어 표시, 입을 벌려도 치아에 칠해지지 않음(스크린샷 첨부) |
| **M4** | 끊김 대응 | 손으로 얼굴 가렸다 뗄 때 상태 전이 로그, 복귀 시 튐 없음(전후 프레임 위치 차 수치), 45° 초과 시 안내 |
| **M5** | 조명 자동 추정 + 셰이더 (6-6-1) | 배경 Gray World·얼굴 메시 빛 방향·카메라 색온도 읽기(지원 시) 동작, 노란 조명에서 보정 on/off 비교 스크린샷, 신뢰도 낮음 안내, 조명 변화 시 자동 재추정, **갤럭시·아이폰 같은 계산 경로** 테스트. 네이티브 모듈 없음 |
| **M6** | 진하기·보기 옵션 | 슬라이더↔횟수 문구, 지금/표준/갈 곳 조명 전환, **보기 전환 시 UV 텍스처 제품 색 불변 테스트** 통과, 부위별 피부 측정값 출력 |
| **M7** | 제품 매칭 | `data/catalog/products.ts`(measureMethod 표시 포함) 기준 상위 3개 추천, 실측 사진 표시 자리, 가진 제품 비교 문구 |
| **M7-2** | 유사 제품 추천 (6-9-2) | placeholder 10개 이상으로 묶음별 목록, 측정 완료 제품이 앞. 지금 조명을 바꿔도 순위 동일(테스트). 제휴 벌점이 묶음을 바꾸지 않고 같은 묶음 안 순서만 바꾸는 테스트. 대화 시나리오 8개 이상(6-9-2 표 + 조건 누적 + 결과 없음) 통과. 제품명이 든 LLM 출력 거부. 화면에 점수 숫자 없음. 제형·제휴 벌점을 0으로 바꿔도 테스트 통과(벌점 0이면 ΔE 순서와 같음) |
| **M7-3** | 행동 이벤트 기록 (6-14) | 동의 꺼짐이면 기록 0건(테스트), 내보내기 JSON에 이미지·측정값·발화 원문 없음, 기록 지우기 동작 |
| **M8** | 따라 바르기 | 손 가림 시 측정 중지, 1초 안정 후 측정, 안내 문장, 보정값 저장 후 AR 색 변화 확인 |
| **M9** | 성능 단계 | FPS 기반 단계 전환 로그, 단계별 색 계산 결과 동일 테스트 |
| **M10** | 레시피 추출 (서버) | 영상 3개로 투표 결과 `Recipe` 생성, 스키마 검증 통과, 참고 이미지 처리 후 **이미지가 디스크·로그에 남지 않음** 확인 |
| **M11** | 대화형 조정 (텍스트) | 시나리오 10개("아이라인 조금 연하게", "아까보다 더", "반짝이 빼줘", "아까로 돌려줘", "내 피부톤에 맞게" 등) 통과, LLM이 숫자·제품명을 만들면 거부되는 테스트 |
| **M12** | 아이라인 렌더링 (F13 일부) | 화면 공간 눈 캔버스(UV 메시는 얇은 선을 삼각형마다 휘게 해서 쓰지 않음), `set_geometry` 명령으로 길이·두께 변화 |
| **M13** | 평가 | `scripts/eval` 트랙 A~E 실행 결과를 트랙별로 분리한 보고서 |
| **M14** | 기초화장품 추천 (6-16) — **후순위**: M7-2와 M1-D(성분 데이터) 이후 | 피부 타입 질문(1·2단계) 동작, 써 본 제품·피하고 싶은 성분 저장·삭제, 성분 겹침 정렬 단위 테스트, 피하고 싶은 성분 제외 테스트, 근거 문장이 세 유형만 나오는지 테스트, **효능 표현 금지어 검사 테스트**(네 언어 사전), 서버가 요청 내용을 저장·로그하지 않음 확인, `ingredients.tsx` 연결 |
| **M15** | 30분 뒤 색 (F17) | `labAfter30min` 있는 셰이드만 전환 버튼 표시, 없는 셰이드는 숨김(테스트), 전환 시 UV 텍스처 색만 바뀌고 조명·명암 처리는 동일 |
| **M16** | 겹쳐 바르기 (F18) | 두 층 합성이 6-7 공식과 일치(단위 테스트), 위 층 제형으로 광택 결정, 측정 전 셰이드 포함 시 "추정" 표시 |
| **M17** | 반반 비교 (F19) | 중심선 기준 좌우 분할이 고개를 돌려도 유지, 두 쪽 처리 동일(테스트), 진단·판정 문구 없음 |
| **M18** | 내 립 서랍 + 바로 담기 (F20) | 서랍 저장·삭제, "비슷한 색이 이미 있어요" 조건(ΔE<4, 같은 제형) 테스트, 순위 불변 테스트, 장바구니·쇼핑 리스트 진입 동작(기존 화면 동작 불변) |
| **M19** | 가격 기능 (F21) | 듀프 가격 차이 문장(가격 확인 날짜 없으면 숨김), 판매처 가격 표시는 `SE05` 해결 시에만, 가격 알림·택스리펀드는 구현하지 않음 |
| **M20** | 여행 쇼핑 플래너 (F22) | 쇼핑 리스트 총액 + 매장 선택 흐름, 네 언어 문구 |
| **M21** | 구매 후 확인 + 지표 (F23) | 앱 안 제안, 기대 일치도(1~5) 저장, 이벤트 6종이 동의 꺼짐이면 0건(테스트) |

**M0-E 확인표 (iOS·Android 각각)**

| 확인 항목 | iOS | Android |
|---|---|---|
| 카메라 권한 창이 한 번만 뜸 | ☐ | ☐ |
| WebView 안에 전면 카메라 영상 표시 | ☐ | ☐ |
| FaceLandmarker GPU 실행 여부 (실패 시 CPU 전환 확인) | ☐ | ☐ |
| WebGL2 사용 가능 | ☐ | ☐ |
| 화면 FPS 표시 (디버그) | ☐ | ☐ |
| 앱 재시작 후 보정값 유지 (AsyncStorage → `calibration` 메시지로 페이지에 복원) | ☐ | ☐ |
| 앱 ↔ WebView `postMessage` 왕복, 숫자만 오가는지 로그 확인 | ☐ | ☐ |
| 8KB 넘는 메시지·이미지 데이터가 차단되는지 테스트 | ☐ | ☐ |
| 카메라가 `colorTemperature`·`whiteBalanceMode`를 알려 주는지, 화이트밸런스 고정이 되는지 (6-6-1 ③) | ☐ | ☐ |

숙제 실험 마일스톤(R2, R4)은 8-A에 따로 둔다.

---

## 8. 평가 스크립트 (`scripts/eval/`)

**트랙은 섞지 않는다(1-12).** 스크립트와 데이터 폴더를 트랙별로 나눈다.

| 트랙 | 질문 | 스크립트 | 입력 | 출력 |
|---|---|---|---|---|
| **A. 시뮬레이션 현실감** | 내 얼굴에 자연스럽게 붙어 보이는가 | `a_angle.py` | 정면·30°·45°·60° 영상 | 각도별 표시 프레임 비율, 입술 경계 오차 (2D vs UV) |
| | | `a_tracking.py` | 손 가림·빠른 움직임 영상 | 떨림, 끊김 후 복귀 시간·튐 |
| | | `a_human.py` | AR 렌더 + 실제 사진 섞은 세트 | 사람 평가: 자연스러움 1~5점, 진짜/가짜 판별 정답률, LPIPS |
| | | `a_texture.py` | 맨입술 프레임 + 같은 프레임 AR 결과 | 입술 영역 밝기 SSIM (입술 결·명암 유지, 8-B-2) |
| | | `a_skin_unchanged.py` | 원본 프레임 + AR 결과 | 입술 밖 피부 SSIM·평균 ΔE2000 (미화 검사, 8-B-2) |
| **B. 실물 발색 정확도** | 실제로 바르면 이 색이 나오는가 | `b_color_texture.py` | DB `labOnPaper` + AR 텍스처 색 | ① DB 색 = AR이 칠하는 색인가 (ΔE ≈ 0, 8-B-1) |
| | | `b_color_mixing.py` | DB 측정값 + 맨입술 Lab + 실제 바른 사진 | ② 혼합 공식 예상 색 vs 실제 입술 색 ΔE2000 |
| | | `b_color_render.py` | 실제 바른 사진 + 같은 조건 AR + 입술 마스크 | ③ 조명별 ΔE2000, **보정 전 대비 감소율** |
| | | `b_region.py` | 부위별 피부 측정 | 부위별 측정 일관성 |
| | | `b_followalong.py` | 따라 바르기 전후 기록 | 보정 전 AR vs 보정 후 AR의 ΔE2000 |
| | | `b_device.py` | 기기별 앱 내 렌더 저장 이미지 | 기기 간 ΔE2000 |
| | | `b_expectation.py` | 샘플 수령 후 설문 | 기대 일치도 ("AR에서 본 것과 비슷했나요?" 1~5점) |
| **C. 레시피 추출** | AI가 화장 과정을 맞게 뽑았는가 | `c_recipe.py` | 사람이 정답을 단 영상·이미지 20~30개 | 단계·부위·색 계열·기법 일치율 |
| **D. 대화형 조정** | 말한 대로 바뀌는가 | `d_dialog.py` | 대화 시나리오 20~30개 (여러 턴) | 지시 반영률, 참조 표현 처리율, 되묻기 비율, 응답 시간 |
| **E. 상품 추천** | 추천이 맞고 납득되는가 | `e_reco.py` | 프로토타입 사용 기록 (F15 내보내기) | 추천 근거 제시율, 사용자 선호 평가, 클릭률 |
| | | `e_texture.py` | 팀 패널·측정 제형(정답) + 판정 결과 | 제형 판정 순위별(키워드·공식 설명·리뷰 요약·설문) 일치율, 컬러칩 추정 색 vs 측정 색 ΔE2000 |
| | | `e_skincare.py` | 프로토타입 사용 기록 (F15) + 짧은 설문 | 기초 추천 수락률·저장률, 근거 문장 신뢰도(1~5), 피부 타입 질문만 vs 질문 + 써 본 제품 비교 |
| | | `e_similar.py` | 숙제 01 실측 Lab + AR 예측 Lab | **유사 추천 NDCG@3**: 실측 기준 "실제로 비슷한 순서"를 정답으로, AR 예측 순위 비교. 사람이 고른 "비슷하다" 판단과 묶음 일치율 |
| **기여도 비교** | 기능이 실제로 도움이 되는가 | `ablation.py` | 같은 데이터 | 기능 켜기·끄기 비교: 조명 보정 on/off(B), 2D vs UV 렌더(A), ΔE만 vs ΔE+제형 벌점(E), 제휴 벌점 on/off(E) |

- 모든 트랙 결과는 **Monk 피부톤 구간별로도 분해**한다.
- 기여도 비교도 트랙별로 따로 적는다(1-12). 제휴 벌점 on/off 비교는 "제휴 벌점 때문에 사용자가 덜 비슷한 제품을 고르게 되는지" 확인용이다.

### 8-B. 평가 도구별 적용 방법

세 도구는 같은 사진에 대해 서로 다른 질문에 답한다. **CIEDE2000 = 색이 같은가, SSIM = 결과 모양이 그대로인가, VLM = 사람 눈에 자연스러운가.** 한 도구로 다른 도구의 질문에 답하지 않는다.

#### 8-B-1. CIEDE2000 (ΔE2000): 색 차이

- **무엇:** 두 색이 사람 눈에 얼마나 다르게 보이는지를 잰 값. 0이면 같고 클수록 다르다. 대략적인 감각은 1 이하면 구분이 어렵고, 2~3이면 나란히 볼 때 보이며, 5 이상이면 한눈에 다르다.
- **계산 규칙:** 6-5의 색 유틸(정식 sRGB EOTF → 선형 → XYZ D65 → Lab → CIEDE2000)만 쓴다. Python 평가 스크립트도 같은 변환(colour-science)을 쓰고, 두 구현이 같은 결과를 내는지 테스트로 맞춘다(M1의 Sharma 2005 테스트 쌍).
- **입술 색 대표값:** 입술 마스크 안 픽셀에서 하이라이트·그림자를 뺀 **중앙값 Lab**을 쓴다(6-10과 같은 방식). 평균은 반사광에 끌려가므로 쓰지 않는다.
- **조명:** 실제 사진은 같은 고정 측정 환경(`setupId`)에서 찍은 것끼리 비교한다. AR 쪽은 6-6-1로 추정한 조명을 반영한 **표준 조명 값**을 쓴다.

**적용 위치**

| 위치 | 비교 | 기준 |
|---|---|---|
| 트랙 B ① `b_color_texture.py` | DB `labOnPaper` vs AR UV 텍스처 제품 색 (표준 조명) | ΔE < 0.5. 넘으면 코드 버그 (원칙 1-1) |
| 트랙 B ② `b_color_mixing.py` | (DB 색 + 맨입술 Lab + a1로 계산한 예상 색) vs 실제로 바른 사진 입술 색 | 결과를 보고 판단. 오차가 크면 회귀 보정 모델 도입 근거(11-2) |
| 트랙 B ③ `b_color_render.py` | AR 렌더 입술 색 vs 실제로 바른 사진 입술 색 (같은 조명·같은 사람) | 보정 전 대비 감소율 (트랙 B 목표) |
| 유사 추천 (F7-2) | 지금 AR 색 vs 후보 제품 예상 색 | 6-9-2 묶음 기준 |
| 따라 바르기 (F8) | 목표 색 vs 실제 바른 입술 색 | 4 미만이면 "거의 같아요" |
| 조명 변화 감지 (F2) | 현재 피부 평균 vs 기준 피부 | 6 이상이면 재보정 안내 |

- **단계별로 원인을 가른다.** ①이 틀리면 코드 버그, ①은 맞고 ②가 틀리면 혼합 공식 문제, ②는 맞고 ③이 틀리면 렌더링·조명 문제. 보고서에 세 단계 ΔE2000을 따로 적는다.
- **채도 차이:** 트랙 B ②③은 ΔE2000과 함께 ΔC\*ab = C\*(AR 또는 예상 색) − C\*(실제 사진)를 평균·부호로 적는다. ΔE2000은 방향을 알려 주지 않으므로, 가상 쪽이 더 선명해지는 치우침은 ΔC로 확인한다(6-5-3).
- **DB 사용 규칙:**
  - `measureMethod: "measured"`인 셰이드만 평가에 쓴다. placeholder·estimated로 정확도를 재지 않는다.
  - DB 측정(종이 발색 사진)과 평가용 사진(입술에 바른 사진)은 **따로 찍은 것**을 쓴다. 같은 사진으로 값을 만들고 평가하지 않는다.
  - 측정 조건(`measuredAt`, 기종, 조명)이 없는 값은 평가에서 뺀다.

#### 8-B-2. SSIM: 구조·결 유지

- **무엇:** 두 이미지의 밝기·대비·구조(무늬·결)가 얼마나 같은지를 잰 값. 1에 가까울수록 원본 구조가 남아 있다. 색에는 둔하므로 색 판단에는 쓰지 않는다.
- **계산 규칙:** 밝기 성분(Lab의 L 또는 선형 휘도)만 쓴다. 비교 영역은 마스크로 자르고, 마스크 경계 바깥 몇 px는 빼서 경계 페더링 영향을 줄인다. 구현은 scikit-image `structural_similarity`(BSD)를 쓰고 창 크기를 보고서에 적는다.
- **같은 프레임끼리 비교한다.** 맨입술 원본 프레임과 그 프레임에 AR을 입힌 결과(앱 내부 렌더 저장)를 쓴다. 다른 시점에 찍은 사진끼리는 위치가 어긋나서 SSIM이 의미가 없다.

**적용 위치**

| 위치 | 비교 | 의미 |
|---|---|---|
| 트랙 A `a_texture.py` | 입술 영역: 원본 밝기 vs AR 결과 밝기 | 높으면 입술 주름·명암이 살아 있음. 낮으면 페인트처럼 덮음 → 셰이더 명암 유지(6-5) 점검 |
| 트랙 A `a_skin_unchanged.py` | 입술 **밖** 피부: 원본 vs AR 결과 (SSIM + 평균 ΔE2000) | 거의 같아야 함. 바뀌었으면 피부를 건드린 것(원칙 1-2, 1-3 위반) |
| 기여도 비교 | 노이즈 맞추기·경계 페더링 on/off | 결 유지에 주는 영향 |

- 기준값은 첫 측정 후 정한다(11-2). 단 `a_skin_unchanged.py`는 우리 AR에서 입술 밖 피부가 바뀌면 안 되므로, 입술 밖 평균 ΔE2000 < 0.5를 **회귀 테스트 기준**으로 바로 둔다.
- SSIM이 높아도 자연스러워 보인다는 뜻은 아니다. 자연스러움은 8-B-3(사람·VLM)이 맡는다.

#### 8-B-3. VLM: 사람 눈 기준의 자연스러움

- **무엇:** 이미지와 글을 함께 받아 글로 답하는 AI. 숫자를 재는 측정기가 아니라 사진을 보고 의견을 내는 심사위원 역할.
- **쓰는 곳 두 가지:**
  1. **레시피 추출 (F10, 앱 기능):** 영상·참고 이미지 → 화장 단계 구조화. 6-12를 따른다.
  2. **평가자 (숙제 04, 연구용):** 사람 평가와 같은 질문으로 자연스러움을 판단. 사람 평가와 일치하면 개발 중 반복 평가 도구로 쓴다.
- **평가자로 쓸 때 규칙:** 8-A-3의 VLM 후보와 실험 설계를 따른다.
  - 질문·사진·순서·출력 스키마를 사람 평가와 같게 한다.
  - 순서를 바꿔 한 번 더, 같은 질문 3회 반복한다.
  - 외부 API는 `ALLOW_EXTERNAL_JUDGE=true` + 동의한 팀원 사진만 쓴다.
- **VLM에게 묻지 않는 것:** 색이 맞는지(ΔE2000이 정확함, 원칙 1-10), 피부가 바뀌었는지(SSIM·ΔE2000이 정확함). VLM은 숫자로 잡히지 않는 경계 번짐, 떠 보임, 어색함만 판단한다.
- **R4 결과에 따라 쓰임이 정해진다.**
  - 대체 가능: 버전 비교·기여도 비교에 사람 평가 대신 사용
  - 보조만: 명백히 어색한 결과를 미리 거르는 데만 쓰고 최종 평가는 사람
  - 쓰지 않음: 사람 평가만 사용

#### 8-B-4. 세 도구를 함께 읽는 방법

숙제 01 사진 한 세트(맨입술 / 실제로 바른 사진 / 같은 프레임 AR 결과)로 세 도구를 한 번에 돌리고 결과를 함께 본다.

| ΔE2000 (색) | SSIM (결) | 자연스러움 (사람·VLM) | 해석 | 손볼 곳 |
|---|---|---|---|---|
| 낮음 | 높음 | 높음 | 잘 되고 있음 | — |
| 낮음 | 낮음 | — | 색은 맞는데 페인트처럼 덮음 | 셰이더 명암 유지(6-5) |
| 높음 | 높음 | — | 결은 살아 있는데 색이 틀림 | 8-B-1 단계 ①②③으로 원인 확인 |
| 낮음 | 높음 | 낮음 | 숫자로 안 잡히는 문제 (경계, 떨림, 떠 보임) | 경계 페더링, 추적(6-2~6-4) |

- 보고서에는 세 결과를 한 표로 묶되, 트랙 A(SSIM·자연스러움)와 트랙 B(ΔE2000) 칸을 나눠 적는다(1-12).
- 화면 캡처가 아니라 **앱 내부 렌더 결과 저장 기능**(디버그 메뉴, 개발 모드 전용)으로 이미지를 뽑는다. AR 페이지는 `toDataURL`·저장을 쓸 수 없으므로(6-0) 방법은 M0-E에서 제안하고 팀이 정한다(11-1).
- 트랙 B의 목표는 절대값(예: ΔE < 2)이 아니라 **보정 전 대비 감소율**로 잡는다. 근거: arXiv 2512.21988에서 보정 후에도 스마트폰 카메라 중앙값이 ΔE 2를 넘었다.

---

## 8-A. 숙제 02·04 실험 (`research/`)

**공통 규칙**
- 숙제 작업은 앱 개발을 막지 않는다. 앱 마일스톤과 따로, 단계마다 정한 시간 안에서만 진행한다.
- 비상업 모델·외부 평가 API는 `research/`에서만 쓴다(1-13). 앱 코드에서 import하지 않는지 검사 스크립트(`research/check_imports.py`)로 확인한다.
- 평가용 얼굴 사진은 동의한 팀원 것만, `research/data/`(저장소 제외)에만 둔다.
- 외부 VLM에 사진을 보내는 실험은 `ALLOW_EXTERNAL_JUDGE=true`일 때만, 동의한 사진만 쓴다. 앱 기능으로는 넣지 않는다.
- 라이선스·원리를 확인하지 못한 내용은 "확인 안 됨"으로 적고, 지어내지 않는다. 모든 수치 옆에 출처 데이터 경로를 적는다.

### 8-A-1. 공통 입력: 숙제 01 촬영 규칙

| 항목 | 규칙 |
|---|---|
| 사람 | 피부톤·성별이 다른 팀원 3명 이상 (동의서) |
| 조명 | 주광(창가), 실내 노란 조명 두 가지. 조명마다 장소·조명 기구를 고정하고 `setupId`로 기록 |
| 조건 고정 | 같은 조명 조건 안에서는 장소·조명·카메라 위치를 바꾸지 않음. 흰 종이는 쓰지 않음 |
| 각도 | 정면 / 30° / 45° |
| 단계 | 맨입술 → 1번 바름 → 3번 바름 |
| 제품 | shade_catalog 셰이드 (힌스 무드인핸서 립 글로우 5종부터) |
| 카메라 | 기종 기록, 노출·화이트밸런스 고정(프로 모드 등). 고정이 안 되는 기종은 메모에 적음 |
| 파일 이름 | `{사람}_{조명}_{각도}_{제품}_{횟수}.jpg` (예: `p1_day_00_hince-dearrose_1.jpg`) |
| 정답 마스크 | 정면 사진마다 입술 영역을 사람이 직접 칠함 (`research/data/hw01_masks/`) |
| 메타데이터 | `research/data/hw01_raw/meta.csv`: 기종, 시각, 조명, 메모 |

- 같은 사진으로 PPT 시뮬레이션(`research/data/hw01_ppt/`)과 우리 AR 렌더(앱 내부 저장)를 만들어 세 가지를 같은 조건끼리 묶는다.

### 8-A-2. 숙제 02: CV 모델 비교 (`research/hw02_cv_compare/`)

**질문**
1. 입술·얼굴 영역을 가장 정확하고 안정적으로 찾는 모델은?
2. 휴대폰 WebView에서 실시간(목표 24fps)으로 도는가?

**비교 대상**

| 그룹 | 후보 | 라이선스 | 역할 |
|---|---|---|---|
| 랜드마크 | MediaPipe Face Landmarker (478점) | Apache 2.0 | 기본안 |
| 분할 | MediaPipe Selfie Multiclass | Apache 2.0 | 피부·배경 분리 |
| 얼굴 부위 분할 | face-parsing (SegFormer) | 비상업 | 입술 경계 비교용, 앱에서 사용 안 함 |
| 정지 시착 벤치마크 | Perfect Corp YouCam Makeup VTO | 상용 API | 셀카 한 장 비교만(`research/youcam/`). 얼굴 영상을 보내지 않음(1-4). 피부 보정·입술 볼륨·주름 제거 파라미터는 0 |

후보를 추가할 때는 이름·버전·라이선스·출처를 먼저 보고한다.

**측정 항목**

| 항목 | 방법 | 대상 |
|---|---|---|
| 입술 영역 정확도 | 정답 마스크 대비 **IoU, Dice**, 경계 오차(px) | 랜드마크, 분할 |
| 강건성 | 각도(정면·30°·45°)·조명별 검출 성공률, 경계 오차 | 랜드마크, 분할 |
| 일관성 | 위 결과를 Monk 피부톤 구간별로 분해 | 전부 |
| 떨림 | 정지 영상 10초 동안 입술 점 이동량 | 랜드마크 |
| 속도 | 노트북 브라우저 FPS, Expo Go WebView FPS (M0-E 재사용) | 랜드마크, 분할 |
| 비용 | 모델 크기, GPU 필요 여부, 처리 시간 | 전부 |

**결과물:** `research/reports/hw02_cv_compare.md`. 측정표, 모델별 원리 요약 반 쪽(입력·출력·작동 방식·한계, 출처 필수), 앱에 쓸 모델과 이유, 쓰지 않는 모델과 이유, 실패 사례 목록.

| # | 완료 기준 |
|---|---|
| **R2-1** | 랜드마크·분할 후보의 IoU·Dice·경계 오차·각도별 성공률 표 |
| **R2-2** | 노트북 FPS와 WebView FPS |
| **R2-4** | 보고서 모든 수치에 출처 데이터 경로. 비상업 모델이 `research/` 밖에서 import되지 않음 |
| **R2-6** (선택) | **화이트밸런스·조명 추정 방법 비교:** 배경 Gray World(우리 방식) vs OpenCV xphoto `LearningBasedWB`(Apache 2.0) vs 연구용 Deep White Balance·WB_sRGB(연구·비상업, `research/`에서만). ① Cube++(CC BY 4.0, 정답 조명값 있음)의 SimpleCube++로 조명 추정 각도 오차, ② 숙제 01 사진으로 AR 입술 색 ΔE2000 차이. 결과는 "앱에 넣을 만한 차이가 있는가" 판단 근거로만 쓰고, 연구용 모델은 앱에 넣지 않는다(특허·라이선스) |
| **R2-5** (선택) | 얼굴 이미지 피부 분석 모델 **문헌 조사만**: 데이터셋·가중치 라이선스, 기기 안 실행 가능 여부, 피부톤별 성능 보고 여부. 실험·구현 안 함 |

### 8-A-3. 숙제 04: 평가 방법론 (`research/hw04_eval_methods/`)

**질문**
1. 수치 평가(ΔE, IoU, LPIPS)와 결과물 평가(사람이 보는 자연스러움)는 무엇이 다르고 얼마나 일치하는가?
2. VLM에게 평가를 맡기는 방식(LLM-as-a-Judge로 추정, 멘토에게 용어 확인)은 사람 평가를 대신할 수 있는가?
3. 트랙 A~E에 어떤 지표 조합을 확정할 것인가?

**평가 방법 후보**

| 종류 | 방법 | 보는 것 | 우리 프로젝트 적합성 |
|---|---|---|---|
| 색 정확도 | ΔE2000 (입술 마스크 안) | 실물 발색 (트랙 B) | 핵심 |
| 영역 정확도 | IoU, Dice, 경계 오차 | 제자리에 붙었는가 (트랙 A) | 핵심 |
| 순위 평가 | NDCG@3, Precision@3 | 유사 추천 순서가 맞는가 (트랙 E) | 핵심 |
| 지각 유사도 | LPIPS (BSD) | 사람 눈에 비슷한가 | 보조 |
| 구조 유사도 | SSIM | 질감·명암 유지 | 보조 |
| 분포 비교 | FID | 생성 모델 전체 품질 | 표본이 적어 맞지 않음. 쓰지 않는 이유만 적음 |
| 무참조 화질 | NIQE, BRISQUE 등 (IQA-PyTorch) | 사진 자체 화질 | 가중치 비상업이면 `research/`에서만 |
| 사람 평가 | 자연스러움 1~5점, 진짜/가짜 맞히기 | 실제 사용자 느낌 | 핵심 (기준값) |
| VLM 평가 | 사람과 같은 질문·사진·순서 | 사람 평가 대체 가능성 | 실험 대상 |

**실험 설계**
- `human_eval/`: 무작위 순서 웹 폼, 실제 사진 여부 숨김. 질문 2개("자연스러워 보이나요? 1~5", "실제로 바른 사진일까요? 예/아니오"). 평가자 인원 목표는 두지 않고, 참여한 인원을 보고서에 적는다. 팀원이 평가할 때는 **본인 사진은 평가하지 않는다**. 결과는 CSV, 평가자 이름은 남기지 않음.
- `llm_judge/`: 사람 평가와 같은 질문·사진·순서. 같은 쌍을 순서만 바꿔 한 번 더(위치 편향), 같은 질문 3회 반복(일관성). 출력은 JSON 스키마(점수, 한 줄 이유)로 강제. VLM은 어댑터로 교체 가능하게(기본: 레시피 추출과 같은 Gemini).
- **VLM 후보 (평가자 모델)**

| 역할 | 모델 | 제공 | 비고 |
|---|---|---|---|
| 기본 평가자 | Gemini | Google (API) | 레시피 추출(F10)과 같은 키로 사용. 처음에는 이것 하나로 시작 |
| 교차 확인 1 | GPT-4o | OpenAI (API) | 기본 평가자 결과가 애매할 때 추가. 한 모델의 버릇인지 확인 |
| 교차 확인 2 | Claude | Anthropic (API) | 같은 목적. 셋 중 둘만 써도 됨 |
| 로컬 대안 (선택) | 이미지 입력을 받는 공개 모델 (예: Qwen2.5-VL 계열) | 직접 실행 | 사진을 외부로 보내지 않아도 됨. **가중치 라이선스·크기별 조건 확인 후** 추가. GPU 필요 |

  - `llm_judge/judge_adapter.py`로 모델을 교체할 수 있게 하고, 모든 모델에 **같은 질문·사진·순서·출력 스키마**를 쓴다.
  - 모델 이름과 버전은 계속 바뀌므로 코드에 고정하지 않고 설정(`research/hw04_eval_methods/judges.json`)에서 읽는다. 보고서에는 실제로 쓴 **정확한 모델 ID와 실행 날짜**를 적는다.
  - 외부 API 모델은 `ALLOW_EXTERNAL_JUDGE=true`일 때만, 동의한 팀원 사진만 보낸다(1-13). 로컬 모델은 이 플래그와 상관없이 실행할 수 있다.
  - 모델을 2개 이상 쓰면 `analyze.py`에 **모델끼리 일치율**(같은 사진에 비슷한 점수를 줬는지)을 추가한다. 모델끼리는 맞는데 사람과 다르면 "AI 공통 버릇"으로, 모델끼리도 다르면 "평가자로 불안정"으로 보고서에 적는다.
  - 비용·속도도 같이 기록한다(사진 1장당 응답 시간, 호출 비용).
- `analyze.py`: 사람↔VLM 스피어만 상관·일치율, 사람↔수치 지표(ΔE, LPIPS, SSIM) 상관, VLM 순서 바꿈·반복 일관성. Monk 구간별 분해.
- PPT 시뮬레이션과 우리 AR을 비교해 차이가 커지는 조건(조명, 각도, 피부톤)을 적는다(멘토 피드백 ②).

**결과물:** `research/reports/hw04_eval_methods.md`. 방법별 원리 요약(출처 필수), 위 표, 상관표, 트랙별 확정 지표와 8장 수정 제안, VLM 평가 신뢰 수준(대체 가능 / 보조만 / 쓰지 않음)과 근거. 결론에서 "측정으로 확인한 효과"와 "아직 검증하지 않은 사용자 행동"을 나눠 적는다.

| # | 완료 기준 |
|---|---|
| **R4-1** | 평가 세트 묶음표(실제·PPT·AR), 빠진 조합 목록 |
| **R4-2** | 사람 평가 폼 동작, 결과 CSV 저장 |
| **R4-3** | `ALLOW_EXTERNAL_JUDGE=true`일 때만 외부 VLM 실행(테스트), 순서 바꿈·3회 반복 결과. 모델을 2개 이상 쓰면 모델끼리 일치율. 보고서에 모델 ID·실행 날짜·응답 시간·비용 |
| **R4-4** | 상관표와 결론이 담긴 보고서. 트랙 A·B 데이터 분리 |

### 8-A-4. 일정 배치 (10/31 오프라인 멘토링 기준)

| 순서 | 작업 | 필요한 것 | 10/31까지 |
|---|---|---|---|
| 1 | 촬영 규칙 + 숙제 01 촬영 | 팀원, 제품, 고정 조명 | 필수 |
| 2 | R2-1·R2-2 | 01 사진, 정답 마스크, M0-E 결과 | 목표 |
| 3 | R4-1·R4-2 | 01 사진, PPT 결과 | 목표 |
| 4 | R4-3·R4-4 | 사람 평가 결과, API 키 | 여유 있으면 |
| 5 | R2-5 | 조사 시간 | 여유 있으면 |

앱 쪽은 M0 → M0-E → M1 순서로 따로 진행한다.

---

## 9. 명령 예시 (그대로 복사해서 사용)

**처음 시작 (이것만 쓰면 됨)**
> `docs/AR_SPEC.md`를 읽고 0-A 절차대로 시작해줘.

**계속하기**
> 다음

**상태 보기**
> 상태

**전체 시작 (자세한 버전)**
> `AGENTS.md`와 `docs/AR_SPEC.md`를 읽고 1장 절대 원칙과 저장소 규칙을 요약해 확인한 다음, M0을 진행해줘. 브랜치는 이슈 #<번호>로 `AGENTS.md` 규칙대로 만들어줘. 끝나면 완료 기준별 결과, 기존 코드와 명세서가 다른 곳, 추가한 의존성의 라이선스를 보고해줘.

**마일스톤 진행**
> M3(메시 + UV 렌더링)을 진행해줘. 6-4 명세를 따르고, 정면·30°·45° 스크린샷과 입 벌린 상태 스크린샷을 남겨줘. 원칙과 충돌하는 부분이 있으면 구현 전에 먼저 말해줘.

**수정 지시**
> M4 상태기계에서 COASTING 시간을 300ms → 200ms로 바꾸고, 바꾼 뒤 손 가림 테스트 로그를 다시 보여줘.

**검증 지시**
> 지금 조명 / 표준 조명 / 갈 곳 조명에서 같은 제품의 UV 텍스처 RGB 값이 동일한지 확인하는 테스트를 추가하고 결과를 보여줘.

**평가 실행**
> 트랙 A의 `a_angle.py`를 `research/data/track_a/angles/` 영상으로 돌려서 2D 방식과 UV 방식의 각도별 유지율 표를 만들어줘. 트랙 B 데이터와 섞지 마.

**레시피 추출**
> M10을 진행해줘. 6-12를 따르고, 참고 이미지가 처리 후 디스크와 로그에 남지 않는다는 걸 테스트로 보여줘.

**대화형 조정**
> M11을 진행해줘. 6-13 규칙대로 LLM은 방향만 정하고 크기는 수식이 정하게 해줘. 시나리오 10개 결과를 표로 보여주고, 실패한 시나리오는 원인을 적어줘.

**제품 데이터 추가**
> `research/data/measurements/2026-10-25.csv`의 측정값을 `data/catalog/products.ts`의 해당 `Shade`에 `measureMethod: 'measured'`로 추가해줘. CSV에 없는 값은 지어내지 말고 빈칸으로 두고 목록으로 보고해줘.

**Expo Go 연결**
> M0-E를 진행해줘. 기존 `components/ar/ArFaceView.tsx`·`faceTrackerHtml.ts` 구조는 유지하고, `components/ar/bridgeProtocol.ts`에 5장 `HostToPage`/`PageToHost` 검증과 8KB 상한을 추가해줘. 기존 메시지(`makeup`, `compare`, `hello`, `status`)는 바꾸지 마. `__tests__/faceTracker.test.ts`는 완화하지 말고, 7장 M0-E 확인표를 iOS·Android 각각 채워줘. 평가용 렌더 저장 방법은 구현하지 말고 방법만 제안해줘. 끝나면 `npm run check` 결과를 보여줘.

**유사 제품 추천**
> M7-2를 진행해줘. 6-9-2대로 벌점표·묶음 기준·`unavailablePenalty`는 `constants/similarity.ts`에서 읽고, 묶음은 colorScore로, 같은 묶음 안 순서만 rankScore로 정해줘. LLM은 조건만 내게 하고, 시나리오 결과를 표로 보여줘. 화면에 점수 숫자가 나오는 곳이 없는지도 확인해줘.

**데이터 가져오기**
> M1-D를 진행해줘. 6-15대로 `scripts/data/`에 가져오기 스크립트를 만들고, `research/data/measurements/sample.csv`(가짜 값, `placeholder` 표시)로 `data/catalog/measurements.json`을 만들어 `server/catalog.ts`가 Shade에 합치게 해줘. 빈칸은 지어내지 말고 그대로 두고, 없는 id·보정 안 한 행은 목록으로 보고해줘. 식약처 키가 없으면 안내만 출력하고 끝내줘.

**공식몰 데이터 입력**
> 내가 적어 준 힌스 무드인핸서 립 글로우 5종 정보(제품명, 셰이드 이름, 공식몰 hex, 참고 가격, 제형, 확인 주소·날짜)를 `data/catalog/products.ts`에 `measureMethod: 'estimated'`로 넣어줘. 내가 주지 않은 값은 비워 두고 목록으로 알려줘.

**기초화장품 추천**
> M14를 진행해줘. 6-16대로 피부 타입 질문은 `constants/skinQuestions.ts`의 목록에서만 내고, 근거 문장은 세 유형만 쓰게 해줘. 효능 표현 금지어 검사 테스트를 네 언어 사전에 대해 추가하고, 피부 정보는 기기 안에만 저장되는지 보여줘. 얼굴 사진은 쓰지 마.

**숙제 01 촬영 준비**
> `research/protocol/`에 8-A-1 촬영 규칙을 체크리스트 md로 만들고, 파일 이름 규칙을 검사하는 `check_names.py`를 만들어줘. 규칙에 맞지 않는 파일은 목록으로 보여줘.

**숙제 02**
> R2-1을 진행해줘. `research/data/hw01_raw`의 정면·30°·45° 사진과 `research/data/hw01_masks` 정답으로 MediaPipe Face Landmarker와 face-parsing의 입술 IoU·Dice·경계 오차를 비교하는 표를 만들어줘. face-parsing은 `research/`에서만 쓰고, `check_imports.py`로 앱 코드에서 import하지 않는지 확인해줘.

**숙제 04**
> R4-3을 진행해줘. `human_eval` 결과와 같은 사진·질문·순서로 VLM 평가를 돌리고, 순서를 바꾼 결과와 3회 반복 결과를 함께 저장해줘. `ALLOW_EXTERNAL_JUDGE`가 꺼져 있으면 실행되지 않는 테스트도 추가해줘.

---

## 10. 범위 밖 (이번 설계서에서 구현하지 않음)
- 로그인, 결제, 제휴 링크 추적 (서버는 레시피 추출·대화형 조정만)
- **날씨 API** — MVP에서 제외
- 얼굴 사진으로 피부를 분석하는 기능 — 기초 추천(F16)은 직접 응답과 성분만 쓴다
- 퍼스널컬러 진단 — 반반 비교(F19)로 직접 보게 하는 것으로 대신한다
- 가격 알림, 택스리펀드 예상 — 조건 충족 전까지 후보(6-17 F21)
- 바르는 방법 비교(풀립·그라데이션·오버립) — 후보(6-17)
- 결제(PG) — 저장소 기획상 범위 밖. 구매는 쇼핑 리스트와 외부 판매처 링크로
- SNS 공유 카드, 어디서든 AR(크롬 확장), 장바구니
- 얼굴 이미지 피부 분석(여드름·주름·붉은 기 등) — 1-4와 충돌, 진단처럼 보이는 표현 문제, 모델·데이터 라이선스 미확인. 문헌 조사(R2-5)만
- 미화·연출 기능 전부 (피부 보정, 얼굴형 필터, 배경 흐림, 링라이트·무대 연출) — 1-2, 1-3에 따라 영구 제외
- **생성형 메이크업 모델 (영구 제외)** — 이 앱의 AR은 "내 얼굴에서 실제로 보일 모습 그대로" 사실적으로 보여 주는 것이 목적이다. 생성형 모델은 화장한 얼굴을 새로 그려 내는 방식이라 제품 색을 "그럴듯한 색"으로 바꾸거나 피부·얼굴형을 건드릴 수 있고, 같은 입력에도 결과가 달라 현실성이 떨어진다. 그래서 앱에도 숙제 02 비교 실험에도 넣지 않는다. 숙제 02 보고서에는 제외 이유만 적는다
- 커스텀 네이티브 모듈(development build가 필요한 것) — Expo Go 범위 밖
- **네이티브 조명 추정(ARKit·ARCore)** — 조건부 도입 후보(6-6-2). MVP에서 구현하지 않는다
- 흰 종이·컬러 카드 등 사용자에게 보정 도구를 요구하는 기능
- 연구용·비상업 화이트밸런스 모델(Deep White Balance, WB_sRGB, mixedillWB, LSMI)을 앱에 넣는 것
- **YouCam / Perfect Corp Makeup VTO를 라이브 AR에 넣는 것** — 셀카를 서버로 보내는 정지 사진 API라 1-4와 충돌하고 Expo Go 매 프레임(16~24fps)에 맞지 않음. 비교는 `research/youcam/`만. 피부 보정·입술 볼륨·주름 제거는 1-2·1-3. 피츠패트릭·얼굴형·메이크업 트랜스퍼 결과 이미지는 쓰지 않음. 부위별 대응은 6-5-4(색·세기만)
- 옷 가상 착용

## 11. 남은 확인 사항

### 11-1. 구현 전에 정할 것 (지금은 아래 기본값으로 진행)

| # | 항목 | 기본값 |
|---|---|---|
| 1 | 참고 이미지 입력의 권리 정책 (받는 이미지 범위, 이용 약관 문구) | 미정. M10 전에 확정 |
| 2 | 대화 시나리오 20~30개 작성 (숙제 05와 연결) | M11 전에 작성 |
| 3 | VLM 평가에 쓸 모델 | Gemini 하나로 시작, 결과가 애매하면 GPT-4o·Claude로 교차 확인. 로컬 공개 모델은 라이선스 확인 후 선택 (8-A-3) |
| 4 | AR 페이지 코드 관리 방식 | 기존 한 파일(`faceTrackerHtml.ts`) 유지. 커지면 원본 분리 + 빌드 생성 방식을 팀이 정함 (6-0) |
| 5 | 제형 | 기존 `Texture` 7종을 그대로 사용(4종으로 묶지 않음). 축 순서와 7×7 벌점은 6-9-2, 조정 가능 |
| 6 | 서버 언어 | 기존 구조대로 TypeScript API 라우트(`app/api/`, `server/`). Python은 평가·숙제 스크립트에만 |
| 7 | 평가용 렌더 결과 저장 방법 | AR 페이지는 저장·`toDataURL` 금지(기존 테스트). M0-E에서 개발 모드 전용 방법을 제안받아 결정 |
| 8 | 룩 데이터의 `tutorialQuery` 노출 | 원칙 1-6은 검색 키워드를 클라이언트에 넣지 않는 것인데, 지금 `CelebLook.tutorialQuery`가 API 응답으로 앱에 전달된다. 서버에서만 쓰도록 바꿀지 팀이 결정 (기본: 지금 그대로 두고 보고) |
| 9 | 화면 언어 | 저장소는 외국인 대상(영어 기본, 4개 언어). 대화형 조정(F11) 시나리오는 ko·en 두 언어로 시작 |
| 10 | `data/catalog/products.ts`가 비어 있음 | 측정 전에는 `measureMethod: 'estimated'`(공식몰 hex) 또는 `'placeholder'`(테스트)로만 채운다. 제품 목록 확정은 `docs/LAUNCH_CHECKLIST.md`와 함께 |
| 11 | 데이터 API 키 | 공공데이터포털(식약처 원료성분·사용제한) 인증키 `DATA_GO_KR_SERVICE_KEY`, 네이버 쇼핑 검색 `SE05` 해결(`docs/LAUNCH_CHECKLIST.md`). 없으면 해당 데이터 없이 진행 |
| 12 | 성분↔피부 타입 규칙 | 만들지 않음(기본). 넣는다면 공신력 있는 출처가 있는 규칙만, 문장에 출처 표시 (6-16 ⑤) |

### 11-2. 구현 후 결과를 보고 정할 것

| 결정할 것 | 판단 근거 | 시점 |
|---|---|---|
| WebView 유지 vs development build 전환 | M0-E 실기기 FPS(목표 24fps), GPU 실행 여부 | M0-E 후 |
| 기기 성능 단계 기준 (24fps, 분할 주기) | M0-E·M9 FPS 로그 | M9 후 |
| 발색 계산: 선형 혼합 유지 vs 회귀 보정 모델 | 트랙 B ΔE2000 (실측 대비) | 숙제 01 + M6 후 |
| 트랙 B 목표값 (보정 전 대비 ΔE ○% 감소) | 첫 측정의 보정 전후 ΔE | 숙제 01 후 |
| 유사 추천 벌점표·묶음 기준·제휴 벌점 값 | NDCG@3, 사람 판단과 묶음 일치율, 제휴 벌점 on/off 비교 | M7-2 + R4 후 |
| 대화 LLM: API vs 로컬 Qwen2.5-7B | 트랙 D 지시 반영률, 응답 시간, 비용 | M11 후 |
| 음성: 기기 안 Whisper vs 서버 Whisper | WebView Whisper 속도, 발열 | F12 착수 시 |
| VLM 평가 신뢰 수준 | 사람 평가와 상관, 순서 바꿈·반복 일관성 | R4-3 후 |
| 피부 분석 기능 도입 여부 | R2-5 조사 + 멘토 답변 | 10/31 멘토링 후 |
| 플랫폼 조명 추정(ARKit·ARCore) 도입 여부 | 6-6-1 공통 방식의 트랙 B 색 오차, iOS ARKit 작은 실험, 갤럭시 ARCore 앞 카메라 지원 확인, 팀의 development build 합의 (6-6-2 조건 셋 다) | 숙제 01 측정 + M5 후 |
| OpenCV `LearningBasedWB` 앱 도입 여부 | R2-6 비교에서 Gray World보다 확실히 나은지, AR 페이지에서 돌릴 수 있는지 | R2-6 후 |
| 행동 데이터를 추천에 넣을지 | 쌓인 이벤트 양, 넣었을 때 기여도 비교 | 출시 후 |
| 규칙 추천 → ML 랭킹 전환 | 사용자-상품 반응 데이터 양 | 출시 후 |

### 11-3. 10/31 멘토링에서 물어볼 것
1. 숙제 04에서 말씀하신 평가 기법이 "LLM-as-a-Judge"가 맞는지
2. 기초 추천을 "직접 응답한 피부 타입 + 써 본 제품 성분"으로 연결했는데(6-16), 이 연결이 충분한지, 피부 분석까지 필요한지
3. AR 체험 행동이 기초 추천에 쓸모 있는 정보가 될 수 있는지, 피부 분석과 결합해도 되는지, 추천 성능 개선을 어떤 방법으로 검증하는 게 맞는지
4. 정기 온라인 멘토링 시간 (월요일 10시, 오전/오후)

---

## 참고 자료
- arXiv 2512.21988, Region-Specific Calibration Achieves Excellent Inter-Device Reliability for Smartphone Dermatology (한국인 얼굴 피부, 기기 간 색 보정): https://arxiv.org/html/2512.21988
- Yun & Seo (2026), AI Virtual Try-On Effects on Fashion Purchases and Product Returns: https://accesson.kr/kjft/v.2/1/13/59807
- Gemini API 영상 이해: https://ai.google.dev/gemini-api/docs/video-understanding
- YouTube API 개발자 정책: https://developers.google.com/youtube/terms/developer-policies
- MediaPipe Face Mesh 문서 (표준 얼굴 모델, UV, 페이스 페인팅, 깊이 가림): https://github.com/google-ai-edge/mediapipe/blob/master/docs/solutions/face_mesh.md
- MediaPipe Face Mesh V2 모델 카드 (80° 한계, 추적·재탐지 오차, 공정성): https://storage.googleapis.com/mediapipe-assets/Model%20Card%20MediaPipe%20Face%20Mesh%20V2.pdf
- MediaPipe Face Landmarker 웹 가이드: https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/web_js
- MediaPipe Hand Landmarker 웹 가이드: https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker/web_js
- MediaPipe Multiclass Segmentation 모델 카드: https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Multiclass%20Segmentation.pdf
- Codrops: MediaPipe + Three.js 실시간 3D 얼굴 마스크 (2026): https://tympanus.net/codrops/2026/09/06/building-a-real-time-3d-face-mask-with-mediapipe-threlte-and-three-js/
- Transformers.js 문서 (device, dtype): https://huggingface.co/docs/transformers.js/en/index
- Oliver (1980) 기대 일치 이론 요약: https://open.ncl.ac.uk/theories/14/expectation-confirmation-theory/
- Expo WebView 문서 (Expo Go 포함): https://docs.expo.dev/versions/latest/sdk/webview/
- Expo 커스텀 네이티브 코드와 development build: https://docs.expo.dev/workflow/customizing/
- react-native-webview 가이드: https://github.com/react-native-webview/react-native-webview/blob/master/docs/Guide.md
- WebView 안 카메라 웹 SDK 연동 사례 (HTTPS, mediaCapturePermissionGrantType, expo-camera 권한): https://docs.liqa.haut.ai/webview-integration/react-native/
- 저장소 규칙 문서: 저장소 `AGENTS.md`, `CONTRIBUTING.md`, `docs/LAUNCH_CHECKLIST.md`
- MediaPipe 표준 얼굴 모델 (UV 포함): https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/modules/face_geometry/data/canonical_face_model.obj
- W3C Image Capture 구현 현황 (colorTemperature, whiteBalanceMode): https://github.com/w3c/mediacapture-image/blob/main/implementation-status.md
- OpenCV xphoto (GrayworldWB, LearningBasedWB): https://docs.opencv.org/4.x/de/daa/group__xphoto.html
- Cube++ 조명 추정 데이터셋 (CC BY 4.0): https://zenodo.org/records/4153431
- Deep White Balance (연구용): https://github.com/mahmoudnafifi/Deep_White_Balance · 삼성전자 특허 US12335667: https://patents.google.com/patent/US12335667
- WB_sRGB (연구용): https://github.com/mahmoudnafifi/WB_sRGB
- ARKit ARFaceTrackingConfiguration: https://developer.apple.com/documentation/arkit/arfacetrackingconfiguration
- ARKit ARDirectionalLightEstimate: https://developer.apple.com/documentation/arkit/ardirectionallightestimate
- ARCore Lighting Estimation: https://developers.google.com/ar/develop/c/lighting-estimation/developer-guide · AugmentedFace: https://developers.google.com/ar/reference/java/com/google/ar/core/AugmentedFace
- 식약처 화장품 원료성분정보 API: https://www.data.go.kr/data/15111774/openapi.do · 사용제한 원료정보 API: https://www.data.go.kr/data/15111772/openapi.do
- 네이버 검색 API (쇼핑): https://developers.naver.com/docs/serviceapi/search/shopping/shopping.md
- Google Monk Skin Tone: https://skintone.google/get-started
- Gemini API 키: https://ai.google.dev/gemini-api/docs/api-key
- Perfect Corp YouCam Makeup VTO (연구 비교만): https://docs.perfectcorp.com/reference/makeup_vto
