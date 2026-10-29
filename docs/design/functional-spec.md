# 기능 명세

## 0. 판정과 범위

작성 기준: 저장소 코드 정적 조사. **PARTIAL**은 코드가 있으나 전체 요구사항 미완성 또는 실행 미검증, **PLANNED**는 요구사항만 있는 경우, **PROPOSED**는 본 문서의 제안, **UNKNOWN**은 확인하지 못한 경우다. IMPLEMENTED는 실제 동작 검증이 필요하므로 이번 정적 조사에서 사용하지 않는다. 아래 수용 기준은 목표이며 통과 결과가 아니다. 경로는 저장소 루트 기준이다. [아키텍처](architecture.md), [AI/CV](ai-cv-architecture.md), [데이터 파이프라인](data-pipeline.md)과 함께 읽는다.

## 1. 기능별 명세

| ID·기능 | 시나리오, 입력 → 출력 / 주요 처리 | 예외 및 의존성 | 현재 상태·근거 | 목표 수용 기준 |
|---|---|---|---|---|
| F01 실시간 AR | 사용자 동의·카메라 허용 → 전면 카메라 영상에 선택한 메이크업 표시; 포커스와 앱 활성 상태를 확인 | 권한 거부, 모델 로딩 실패, 추적 불가 시 상태/색상 견본; F02·F03·카메라 | PARTIAL: `app/(tabs)/ar.tsx`, `components/ar/ArFaceView.tsx`, `components/ar/faceTrackerHtml.ts` | 지원 기기에서 시작·중단·복귀와 권한 거부, 얼굴 이탈 시 대체 화면을 검증 |
| F02 얼굴 랜드마크 | 프레임 → Face Landmarker 좌표 → 필터링된 얼굴 좌표 | CDN/WASM/모델 로드, GPU 실패 시 CPU, 얼굴 없음; F01 | PARTIAL: `components/ar/faceTrackerHtml.ts` | 조명·피부색·움직임·기기별 검출/추적률과 실패 처리를 측정 |
| F03 색상 적용 | 제품·셰이드·강도 → 입술/볼/아이섀도 마스크와 합성, 비교 화면 | 셰이드 없음·WebGL 실패 시 2D fallback; F02 | PARTIAL: `store/makeupStore.ts`, `components/ar/faceTrackerHtml.ts` | 각 부위·강도·텍스처·비교 모드가 실제 선택과 일치하고 렌더링 오류 시 복구 |
| F04 K-Beauty 콘텐츠 | 룩 선택 → 룩 정보 및 연결 제품 표시, YouTube 검색 | 빈 결과·네트워크·외부 API 키 미설정; F05/F06 | PARTIAL: `app/(tabs)/celeb.tsx`, `app/look/[id].tsx`, `app/idol-look/[id].tsx`, `lib/queries.ts` | 콘텐츠와 출처, 제품 매핑 상태를 표시하고 빈 결과를 처리 |
| F05 영상 제품 추출 | 영상 후보 수집·정규화·검토를 거쳐 룩 제품 정보 관리 | 수동 검토·공식 API 키 및 출처 필요 | PARTIAL: `backend/api/app/jobs/collect_youtube_playlist.py`, `backend/api/app/jobs/normalize_youtube_candidates.py`; 영상 전체에서 모든 제품을 자동 인식하는 기능은 확인되지 않음 | 제품명·옵션·출처를 확인 가능한 근거와 함께 등록하고 미확인 항목은 미검증으로 표시 |
| F06 상품 매핑 | 검토된 룩 제품 관계 → 카탈로그 연결 | 후보와 동일 상품 혼동 가능; F05, 카탈로그 | PARTIAL: `backend/api/app/models/idol_look.py`, `backend/api/app/schemas/idol_look.py`; 올리브영 자동 매칭 및 정확도는 확인되지 않음 | 브랜드·제품·옵션 일치와 출처를 검증하고 미검증 후보는 확정 관계로 표시하지 않음 |
| F07 메이크업 따라 하기 | 룩·제품 선택 → 관련 셰이드로 AR 열기 | 제품/셰이드 매핑 누락, 지원하지 않는 부위; F03·F06 | PARTIAL: `app/look/[id].tsx`, `app/idol-look/[id].tsx`, `hooks/useArRouteSelection.ts` | 확인된 매핑만 전달하고 부재 시 사용자에게 알림 |
| F08 피부 상태 분석 | 동의·촬영 → 실험적 지표·설문 결과 저장 | 카메라/모델/인증 오류, 실행 환경·자산 필요. **현재 기본 서버 모드 JPEG 전송은 얼굴 이미지 전송 금지 지침과 충돌** | PARTIAL: `hooks/useSkinAnalysis.ts`, `lib/skinAnalysis.ts`, `lib/skinServer.ts`, `modules/skin-analysis/web/runtime.mjs` | 정책을 먼저 충족한 기기 내 경로만 허용하고 성능·편향·오류율과 삭제를 검증; 의료 진단으로 표시하지 않음 |
| F09 기초 화장품 추천 | 피부 결과와 설문 → 추천 관심사 제안, 사용자가 선택 → 제품 조회 | 저장 결과 없음 시 수동 선택; F08 | PARTIAL: `lib/skinFilters.ts`, `app/skin-recommendations.tsx`, `lib/queries.ts` | 이미지·원 점수 전송 없이 사용자가 확인한 관심사로 일치하는 제품과 근거를 제공 |
| F10 퍼스널 컬러 | 사용자 톤 특성 → 셰이드 추천 | 측정 품질/톤 정보 부재; 제품 데이터 품질 | PARTIAL: `backend/api/app/services/shade_service.py`, `backend/api/app/routers/shades.py`; 톤 입력부터 결과까지 전체 사용 흐름과 정확도는 미검증 | 톤 추정과 추천의 한계·근거를 보이고 실제 제품/셰이드 ID와 연결 |
| F11 AI 챗봇 | 사용자의 메시지·언어 → `POST /api/chat` → 응답 | 인증 또는 익명 식별, 카탈로그·LLM 장애; F04·제품 API | PARTIAL: `hooks/useChat.ts`, `backend/chatbot/app/routers/`, `backend/chatbot/app/services/` | 없는 상품이나 가격을 확정하지 않고 오류·빈 응답을 처리; 검색 근거를 평가 |
| F12 STT 음성 제어 | 음성 → 텍스트 → 의도 검증 → 메이크업 상태 변경 | 음성 권한·인식·의도 모호성; F03 | PLANNED: 현재 음성 인식 경로 확인되지 않음. `app.json`은 Android 오디오 권한 차단 | 사용자 확인 가능한 명령만 적용하고 잘못 인식하면 상태 유지 |
| F13 선크림 도포 보조 | 카메라 기반 도포 가이드 | RGB만으로 UV 보호막이나 실제 차단율 측정 불가 | PLANNED: 실측/가이드 경로 확인되지 않음 | 시각적 안내임을 표시하고 실제 보호율 측정 또는 보장 주장 금지 |
| F14 상품 구매 연결 | 상품 확인 → 장바구니/외부 판매처 또는 결제 진입 | 재고·가격·결제 실패·인증; 제품/오퍼 API | PARTIAL: `app/product/[id].tsx`, `app/cart.tsx`, `app/checkout.tsx`, `backend/api/app/services/payment_service.py` | 가격·옵션을 서버에서 재검증하고 성공·취소·실패 및 중복 처리를 검증 |
| F15 개인화·구독 | 로그인, 로컬 상태/피부 정보·멤버십 화면 | 인증·저장 실패, 구독 실결제 미연결 | PARTIAL: `lib/auth/`, `store/`, `app/membership.tsx`; 가입 버튼은 빈 핸들러 | 로그인 및 개인 데이터 삭제/보관 정책 검증, 구독 결제는 별도 구현 후 활성화 |
| F16 B2B API | 외부 사업자가 AR 기술 이용 | 계약·테넌트 격리·과금·SDK 필요 | PLANNED: 공개 B2B SDK/테넌트 계약 확인되지 않음 | 접근 제어·쿼터·버전·보안 계약과 실제 지원 환경 검증 |

## 2. 공통 정책 및 검증

- F08의 서버 모드는 기능 플래그 `EXPO_PUBLIC_ENABLE_SKIN_ANALYSIS=1`과 실행 조건을 만족할 때만 노출될 수 있다. `EXPO_PUBLIC_SKIN_ANALYSIS_MODE=on-device`를 명시하지 않으면 서버 모드로 선택된다. 전송을 승인했다는 주석과 앱의 고지는 **현재 프로젝트의 얼굴 이미지 서버 전송 금지**를 대체하지 않는다. 해당 경로를 정책과 일치시키기 전 운영에 사용하지 않는 것이 P0 제안이다.
- 로그인·상품·카메라·결제·실기기 성능 및 외부 시스템의 실제 구성은 이 문서의 코드 확인만으로 동작이 입증되지 않았다. 구현 의도와 운영 동작을 구분한다.
- 제안된 수용 기준은 재현 가능한 입력, 예상 출력, 오류·취소, 개인정보 경계, 기기 및 접근성 확인을 포함하는 테스트 케이스로 구체화한다. 성능 수치는 실제 측정 전 목표 또는 UNKNOWN으로만 기술한다.
