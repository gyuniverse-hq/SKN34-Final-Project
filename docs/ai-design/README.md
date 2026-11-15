# VISHUE 대화형 AI — 설계 기준 및 진행 현황

> 기준일: 2026-11-15 (KST)  
> 설계 출발점: develop d1cf4868f74d2ff6db188bf2c7646146f3ec72ad (2026-11-14 22:19 KST)  
> 문서 상태: **1단계 사용자 경험 확정 / 2·3단계 논리 설계 검토 종료 / 4단계 L2 논리 평가 설계 검토 종료 / 현재 5단계 G1 착수 준비**. 실제 구현·평가/Gold·팀 승인·병합은 별도 상태.
> 승인 범위: 사용자와의 설계 대화에서 채택된 원칙. **팀 승인·코드 구현·운영 검증을 의미하지 않는다.**

## 문서의 목적과 권위

VISHUE를 **K-뷰티 중심 자유 대화형 AI**로 설계한다. 사용자가 상품·성분·스타일·AR·피부 분석·이미지·영상·음성을 자연스럽게 넘나들도록 하되, 사실 확정과 실제 실행은 검증된 도구 및 권한 계약을 따른다.

- [01 사용자 경험·능력·시나리오](01-user-experience.md): **사용자 승인된 목표 경험 기준선**.
- [02 목표 시스템·멀티모달·Agent 책임](02-architecture.md): **2단계 목표 구조 + 2-7 C01~C14/S01~S12 실현 경로·적합성 평가**. 목표 기능의 현재 구현 완료로 해석하지 않는다.
- [03 실행 계약·상태·복구·협력](03-execution-contracts.md): 2-2~2-4 State·작업 계약 + 2-6 Handoff + **2-7 일반 LLM 수직 순차 PR·공유 코드 소유권·검증 게이트**. 기술·팀 승인 전.
- [DECISIONS 결정 로그](DECISIONS.md): 채택한 원칙, 대안, 확인 날짜, 추후 변경 사항.
- [04 기존 문서 대조·구현 공백](04-gap-analysis-and-2-5.md): 기존 ADR/코드와 목표 설계의 차이, G-01~37, **2-7 통합 위험·3~5단계 선결 조건**.
- [05 Tool·근거·데이터 접근 설계](05-tool-evidence-data-contract.md): 2-5 개념·원칙 설계안.
- [06 Tool 구현 계약 상세](06-tool-implementation-contracts.md): **2-5 설계 검토 종료, 기술 계약 PROPOSED**. 실제 API 매핑·Pydantic 입출력·검증·오류·권한·TC.
- [07 한국어 우선·다국어 확장·평가](07-ko-first-language-and-evaluation.md): **1차 `ko` 사용자 확정**, 그 외 언어 지원 시점 OPEN.
- [08 옵션 복합 검색·근거 검증·DB 동기화](08-option-search-evidence-and-sync.md): **2-5 설계 검토 종료, 구현 PROPOSED**. 현행 코드/옵션 스키마/Neo4j 색인 차이와 개발안.

이 폴더는 기존 [시스템 아키텍처](../ARCHITECTURE.md), [기술 ADR](../adr/README.md), [AI 평가 원본](../ai-alignment/README_FIRST.md), [AR 명세](../AR_SPEC.md), [성분 상담 계약](../INGREDIENT_CONSULTATION.md)을 대체하지 않는다. 기존 규칙을 변경해야 할 때는 해당 담당자·팀의 결정과 별도 ADR이 선행되어야 한다.

## 상태 표기 규칙

| 표기 | 의미 | 증빙 |
| --- | --- | --- |
| **ACCEPTED-USER** | 이 대화에서 사용자가 채택한 목표·정책 | [DECISIONS](DECISIONS.md) |
| **PROPOSED** | 기술 선택 및 계약 초안. 미승인 | 설계 근거·대안·검토 항목 |
| **EXISTING-CODE** | develop에서 정적 확인 가능한 구현 | 파일·커밋 경로 |
| **TESTED** | 특정 환경·버전·데이터를 밝힌 실행 검사 통과 | 재현 가능한 실행 로그 |
| **VERIFIED-E2E** | 실제 LLM·데이터·앱·기기 등 명시된 범위의 실측 | 각 환경별 관측 기록 |
| **BLOCKED / UNKNOWN** | 데이터 권리·검수·서비스 연동 등 미해결 | 차단 사유와 해제 조건 |

**사용자 채택 결정(ACCEPTED-USER)과 설계 검토 결과(REVIEW-CONCLUSION)를 구분한다.** 검토 결과는 평가자의 승인 가능 판단일 뿐 사용자의 개별 동의·팀 승인·실제 구현을 대체하지 않는다. **VAI-D-013: 1차 구현·평가 언어 `ko` 확정**. **OPEN-LANG-01 부분 해소:** 기존 3개 언어 기획/4개 로케일 코드 차이를 보존하며, 영어·일본어·중국어의 AI·STT·TTS·AR 음성 지원 시점은 미결정이다. [07 언어·평가 문서](07-ko-first-language-and-evaluation.md) 참조.

**설계 확정과 개발 완료를 혼동하지 않는다.** 기존 합성 E2E와 실제 LLM E2E, 코드 존재와 운영 서비스 준비를 명확히 구분한다.

## 0~7단계 전체 진행표

| 단계 | 목표 | 2026-11-15 상태 |
| --- | --- | --- |
| 0 | develop 기준 기존 자산 및 #227~#232 재사용 분석 | 1차 분석, 파일별 통합·마이그레이션 검증 미완 |
| 1 | 사용자 경험·대표 시나리오 | **ACCEPTED-USER: 14개 능력, 12개 시나리오** |
| 2 | LangGraph·Agent·Tool·실행 계약 | **2-7까지 논리 아키텍처 설계 검토 종료(2026-11-15)**. 팀 기술 승인·최종 운영 기술/공통 API 합의 및 실제 구현·실기기 검증은 **미완** |
| 3 | 상품·성분·스타일·미디어·RAG 데이터 설계 | **2026-11-15 논리 설계 검토 종료**; 실행/팀 승인 미완 |
| **4** | **평가·완료 기준 설계** | **2026-11-15 L2 논리 설계 검토 종료**, 평가기/실측/Gold/팀 승인 미완료 |
| **5** | **GitHub Issues·PR·협업 설계** | **현재 G1 착수 준비 중**: 실제 Catalog HTTP/DB·공통 코드 담당·앱 카드·실 LLM·회귀 합의 필요 |
| 6 | 구현·지속 통합 | 새 목표 아키텍처 기준 미착수 |
| 7 | 실제 E2E·사용자 평가 | 새 목표 아키텍처 기준 미착수 |

2-5는 [설계 검토 종료 기준](05-tool-evidence-data-contract.md)·[구현 계약](06-tool-implementation-contracts.md)·[가격/색인 불변조건](08-option-search-evidence-and-sync.md)으로 **논리 설계 검토를 마무리**했다. `ELIGIBLE/REFERENCE_ONLY/EXCLUDED`, 가격 basis/observedAt, 권리·철회·동기화 및 2-6/2-7/3단계 인계를 명시했다. 2-6은 **일반 LLM·AR·AR AI의 책임과 최소 Handoff·복귀 상태·ACK 및 오류 인계를 포함해 논리 설계 검토를 마무리**했다([03](03-execution-contracts.md), [02](02-architecture.md)). 2-7에서는 [목표 구조의 14개 능력·12개 시나리오 커버리지](02-architecture.md), [수직 기능 PR 의존성/공용 API 변경 게이트](03-execution-contracts.md), [실제 공백과 3~5단계 선결](04-gap-analysis-and-2-5.md)을 검토해 **논리 설계 검토를 종료**했다. **팀 기술 승인과 실제 구현·자동 테스트·실환경 연동·기기 E2E·develop 병합은 별도 상태로 남는다.** **2-4는 설계안을 문서화했다. 2단계의 논리 설계 검토는 종료했으며 팀 기술 승인과 실제 구현은 미완료 상태다.**

## 변경·승인 흐름

1. 사용자 경험의 채택 원칙과 설계안의 제안을 따로 표기한다.
2. 새로운 기술적 선택은 대안·근거·영향을 정리한 뒤 필요시 [docs/adr/](../adr/)에 별도 ADR을 남긴다.
3. API·DB·AR 실행 계약은 담당자와 합의한 후에만 구현 기준으로 확정한다.
4. Issue는 기능·계약·완료 조건 단위, PR은 리뷰 가능한 변경·검증 단위로 나눈다.
5. 구현·테스트 증거는 실제 PR/커밋/환경에 연결한다. 구형 PR #227~#232는 **닫힌 미병합 자료**로만 참조한다.

## 문서 유지 원칙

- GitHub가 기술 계약의 기준이다. Notion은 결정·현황·링크를 연결하는 탐색 허브이며 상세 기술 내용을 중복 복제하지 않는다.
- 사용자 제공 영상·사진·피부 정보, AIHub 원문 및 무단 재배포 데이터는 설계 문서·PR에 추가하지 않는다.
- 고정된 예문은 행동 검증의 사례일 뿐 사용자가 할 수 있는 질문의 한계가 아니다.
- 2026-11-15 이후 develop 변동은 자동 반영되지 않으며, 새 비교 기준 커밋을 명시해 재검토한다.

## 문서 변경 기록

| 기록일 | 변경 | 영향 |
| --- | --- | --- |
| 2026-11-15 | 2-4 설계안 작성과 2-5 진행 상태 동기화, 06 구현 계약 연결 | 진행 상태만 정정. 구현/팀 승인 주장 없음 |
| 2026-11-15 | 사용자 결정 vs 설계 검토 판단 상태 분리, 3개 기존 언어 목표/4개 로케일의 지원 범위 미결정 연결 | [01](01-user-experience.md) 및 [DECISIONS](DECISIONS.md)에서 세부 근거 확인 |

## 2026-11-15 추가 변경 기록

| 날짜 | 변경 | 영향 |
| --- | --- | --- |
| 2026-11-15 | VAI-D-013: 1차 한국어(`ko`) AI 구현·평가 확정, 다국어 확장 보존 | 07 언어 정책·S10/C12 유지·TC-22 후속 분리; 그 외 `en/ja/zh` AI 지원 시점 미결정 |
| 2026-11-15 | 08 옵션 복합 검색·근거 검증·Neo4j/Vector 동기화 계약 추가 | 2-5 PROPOSED, 현재 API·DB 변경/실제 데이터 검증 없음 |

## 2026-11-15 2-5 단계 종료 기록

| 구분 | 상태·근거 |
| --- | --- |
| **2-5 논리 설계 검토** | **REVIEW-CONCLUSION: 종료 판단**. [05 종료 기준](05-tool-evidence-data-contract.md), [06 Tool 세부 검증](06-tool-implementation-contracts.md), [08 가격·색인·근거 규칙](08-option-search-evidence-and-sync.md) |
| 사용자 채택 제품 정책 | **ACCEPTED-USER VAI-D-001~013** 유지, 추가 사용자 선택 없이 계약 검토만 진행 |
| 신규 문서 운영 결정 | [DECISIONS: VAI-D-014](DECISIONS.md) 설계·문서화 분리, 세부 단계 종료 시 일괄 GitHub 반영 |
| 새 API·DB·검색 엔진 | **PROPOSED / OPEN**: 구현 방식·실제 데이터·성능·색인·운영 환경에 대한 팀 결정과 평가 필요 |
| 코드·테스트·실기기 | **NOT IMPLEMENTED/NOT TESTED**: 이번 단계 문서 검토가 실제 성공을 뜻하지 않음 |
| 다음 | **2-6** 앱·AR·음성 및 상태 표시. 2-7·3단계 선택 사항은 [05](05-tool-evidence-data-contract.md)에 인계 |
| Notion | 전체 2단계 종료 또는 팀 공유 필요 시 갱신. 이번 2-5 문서 반영에서는 미수정 |

**변경 이력:** 2026-11-15 2-5 논리 계약 검토 마무리 후 기존 05·06·08·README·결정 로그에 한 번에 반영. `develop` 및 기존 기능 코드 수정 없음.

## 2026-11-15 2-6 단계 종료 기록

| 구분 | 상태·근거 |
| --- | --- |
| 2-6 전체 논리 설계 검토 | **REVIEW-CONCLUSION: 종료 판단**. [02 책임·배치](02-architecture.md), [03 Handoff/실행 계약](03-execution-contracts.md), [06 앱 카드](06-tool-implementation-contracts.md), [07 한국어 음성](07-ko-first-language-and-evaluation.md), [04 기존 공유 코드 차이](04-gap-analysis-and-2-5.md) |
| 직접 구현 책임 | **ACCEPTED-USER VAI-D-015**: 일반 LLM / AR / AR 내부 AI·STT/TTS 분리, 공동 인터페이스 |
| 개발 운영 | **ACCEPTED-USER VAI-D-016**: 일반 LLM 수직 기능 순차 구현·독립 브랜치·PR 병합. AR/AR AI 독립 진행, 공유 변경은 계약 선행 |
| STT | **ACCEPTED-USER VAI-D-017**: 기기/서버 교체 가능한 구조, 1차 한 경로만 담당자가 선택. 서버 STT 후보, 미확정 |
| 기존 서비스 배치 | **PROPOSED**: 현재 `backend/chatbot` 유지·논리 모듈 분리 우선. 물리적 서비스 분리 **OPEN** |
| 공동 인계 | **PROPOSED**: 현재 `arHref(productId,shadeId)` 호환, 별도 인계 식별·소유 확인·실제 AR 상태 이벤트로 복귀. 권한·중복·오래된 이벤트·ACK 누락 예외 명세 |
| 현재 코드·검증 | 기존 일부 코드 **EXISTING-CODE**; 새 Handoff 이벤트·영속 ACK·일반 복귀 E2E·실기기 성공 **NOT IMPLEMENTED/NOT TESTED** |
| 2-7 인계 | 공유 `/api/chat`·`ChatService`·스키마·AR 명령·앱 라우트/카드의 PR·리뷰 소유권, 팀 서비스 배치·통합 E2E·종료 조건 |
| Notion | 전체 2단계 완료 또는 팀 공유 시 갱신. **이번 단계 갱신하지 않음** |

**문서 변경 이력:** 2026-11-15 2-6 논리 설계 검토 종료 후 기존 02·03·04·06·07·README·결정 로그에 일괄 반영. 새 문서 생성·기존 AR/LLM 기능 코드 변경·`develop` 병합·실기기 검증 없음.

## 2026-11-15 2-7 최종 검토 및 2단계 설계 종료 기록

| 구분 | 당시 판정 | 증거·당시 인계 |
| --- | --- | --- |
| **2-7 목표 아키텍처 검토** | **REVIEW-CONCLUSION: 설계 검토 종료** | [02 C01~C14/S01~S12](02-architecture.md), [03 PR·Handoff·책임/검증](03-execution-contracts.md), [04 구현 공백](04-gap-analysis-and-2-5.md) |
| 14개 능력·12개 시나리오 | 논리 구성요소·연동·평가 관문 모두 매핑 | **실제 전체 기능 구현/운영 검증 PASS 아님** |
| 사용자 정책 | **ACCEPTED-USER VAI-D-001~017 유지** | 이전 대화에서 확정한 범위·언어·역할·일반 LLM 순차 PR·AR 독립 개발 |
| 팀 기술 승인 | **PENDING** | AR/AR AI/API/프론트/보안 담당 공동 인터페이스·공용 코드 오너·배포/영속성 ADR 필요 |
| 코드 구현/자동 테스트/실제 DB·LLM/기기 | **NOT DONE / NOT TESTED FOR NEW DESIGN** | 과거 코드 일부 존재, 새 LangGraph·RAG·Handoff 구현과 실환경 결과는 별도 |
| 3단계 | **NEXT** | 실제 옵션·전성분/레시피·권리, 한국어 임베딩·RAG·Graph/Vector 색인 품질, 데이터 소유·서빙 계약 |
| 4단계 | 당시 예정 | 한국어 평가셋·G1~G9별 실모델/DB/앱/기기 검증·완료 임계치 |
| 5단계 | 당시 예정 | 일반 LLM G1~G9 기능별 최신 develop 분기→자동/실제 검증→필수 리뷰→병합, AR 팀 독립 PR과 공유 계약의 공동 E2E |
| Notion | **전체 2단계 설계 종료 현황판 갱신 대상** | 기술 상세의 기준은 GitHub, Notion은 결정·진행·링크 요약 |

**중요:** 2단계 **논리 설계 검토 종료**는 2단계 **팀 기술 승인**이나 **최종 설계의 운영 적합성 실증**을 의미하지 않는다. 특정 저장소·벡터 DB·AR 전용 서비스 분리·STT 엔진·옵션 복합 API는 **사용자/팀 결정 및 실측 전 OPEN**으로 유지한다.

**변경 이력:** 2026-11-15 2-7 검토 종료 후 기존 02·03·04·README·DECISIONS 중심으로 일괄 반영. 새 문서 작성·기존 기능 코드/ADR 수정·구형 PR 재병합·실제 E2E 실행 없음.


## 2026-11-15 3단계 최종 반영 및 4단계 시작

- **3단계 데이터·RAG·스타일 논리 설계 검토 종료(REVIEW-CONCLUSION)**. 실제 임베딩/벡터 색인/서비스 RAG/LLM 실행·검수·팀 승인·기기 E2E와 다른 상태다.
- **D3-01 사용자 변경:** AIHub 71961 로컬 RAG 구축·검색·평가를 적극 개발 대상으로 포함. 단, 개별 이용조건·문서별 Purpose/Cautions 확인, 원문 외부 LLM 전송·공용 서비스 배포 승인, 팀 데이터 운영 결정은 **독립 승인 게이트**. 미승인 원문을 공용 색인·PR·외부 LLM으로 보내지 않는다.
- **기존 2-5 계약 유지:** 성분 MATCH/NOT_MATCH는 includes/excludes 조건의 충족 여부. G1은 실제 Tool→Catalog→앱 첫 상품 상담·확인/미확인 조건, G4는 옵션별 복합 교집합·가격 근거와 세 후보 그룹.
- **State 및 순서:** G1 공통 VishueState → G2 멀티턴 → G7 Checkpointer/동의 기억으로 확장; G8은 복합 Agent. G1~G9는 데이터·팀 API 준비에 따른 권장 의존성이지 승인된 일정이 아니다.
- **환경별 근거:** 아래 데이터 수량은 2026-11-15 연결된 단일 Supabase 스냅샷/기존 GitHub develop/AIHub 로컬 적재 보고를 구분한다. 다른 팀원 로컬·공용 dev·운영 DB와 수량 일치 확인 아님.
- 실제 데이터, 청킹·검색, 스타일 레시피, 철회, G1~G9의 설계는 [08 3단계 기록](08-option-search-evidence-and-sync.md), 결정 변경 전후는 [DECISIONS](DECISIONS.md) 참조.
- **당시 4단계 인계:** 4-1 평가 환경·증빙 데이터 정의부터 시작하고, 4-2 G1 평가셋과 4-3~4-6 기준은 논의·검토 후 일괄 반영하기로 했다. Notion은 단계 완료 또는 팀 공유 시점에 갱신할 계획이었다.

## 2026-11-15 4단계 L2 논리 평가 설계 종료 및 5단계 G1 착수 준비

- **ACCEPTED-USER: 4단계 L2 논리 평가 설계 검토 종료**. G1 **47개 사례·70개 predicate 명세**, G2~G9a~c **38개 최소 대표 계약**을 연결하여 C01~C14 / S01~S12의 **논리 평가 커버리지**를 확보했다. 테스트 85건 완료·Gold 승인·실제 제품 전 능력 검증이라는 의미가 아니다.
- **진행 상태를 분리:** `DESIGN_L2_REVIEWED=완료` / `EVALUATOR_IMPLEMENTED=미완료` / `RUNTIME_EVALUATED=미실행` / `GOLD_APPROVED=증빙 없음` / `TEAM_APPROVED=미완료` / `G1_TO_G9_MERGED=신규 순차 PR 미착수`. G1 predicate 70개는 정의만 있고 실행 함수 0개로 관리.
- **후속 38건 사람 평가 분리(권장):** 기존 31개 인간 평가 필수 플래그를 모든 PR 전수 실행으로 해석하지 않는다. 해당 G 기능의 P0 핵심 의미 **18**, G5 평가 분할/색인 변경 시 독립 감사 **1**, P1 품질 표본 **12**, 자동 중심/선택 사람 검토 **7**로 운영. 인간 품질만으로 P0를 대체하거나 필수 핵심 의미 평가를 생략하지 않는다.
- **G2-E01**은 부모 계약 1건을 유지하고 실제 평가기는 **403 타인 유효 세션, 410 자기 만료 세션, 409 자기 미만료 오래된 버전**의 별도 세 실행을 요구한다.
- **G5-B02**는 학습·few-shot·QA 답변 lookup을 통한 평가 질문/답변 누출을 막되, **독립 Gold의 정답 근거 문서를 정상 검색하는 동작은 Recall@k·MRR 성공**으로 처리한다.
- **환경:** 각 사례 `required/conditional/notApplicable`을 분리. 필수 실패·미연결·권리 미확인·미실행은 `NOT_RUN/BLOCKED_DATA/BLOCKED_RIGHTS/BLOCKED_DEPENDENCY`로 관리하고 `PASS/NOT_APPLICABLE`로 변환 금지.
- **보존:** S06 보유 제품 소유·조회 API 확인, S10/C12 한국어 음성 공동 검증/후속 `en/ja/zh` 평가, G7 영속 기억/G8 복합 Agent/G9a~c 공동 E2E 포함. 일반 LLM의 순차 PR·AR/AR AI 독립 구현 원칙 유지.
- **5단계 G1 착수 조건:** 최신 `develop`·실 Catalog HTTP/데이터·공통 `/api/chat`/`ChatService` 및 AR ACK 오너·프론트 카드/가격 표현·실제 LLM 설정·E0/E1/E3/E5 및 AR 회귀 증빙을 확인한 후 G1 착수. 기술/데이터 미확정 사항은 협의 항목이지 기존 14개 능력 축소 근거가 아니다.
- **문서 기준:** [07 전체 평가 L2](07-ko-first-language-and-evaluation.md), [03 5단계 G1 착수](03-execution-contracts.md), [DECISIONS](DECISIONS.md). 기존 0~3단계의 과거 기록은 당시 판단으로 유지한다. Notion은 팀 공유 시점의 링크·진행 요약만 갱신.


## 현재 상태와 상세 평가 원본 (2026-11-15 최종 대조)

> **현재 유효 상태:** 0단계 실사 1차 / 1단계 14개 능력·12개 시나리오 사용자 확정 / 2·3단계 논리 설계 검토 종료 / **4단계 L2 평가 설계 검토 종료 / 5단계 G1 착수 준비**. 과거의 ‘다음 3단계’, ‘4단계 예정’, ‘AIHub 개발 보류’ 등 문구는 **각 당시 단계의 기록**이며 현재 결정을 덮어쓰지 않는다. 결정 변경 내역은 [DECISIONS](DECISIONS.md)의 D3-01 및 VAI-D-018을 따른다.

**상세 평가 원본 저장 위치:** `docs/ai-alignment/04_llm_stage4_evaluation/`. 설계 문서와 함께 보존한 평가 원본 8개는 아래 상대 링크에서 확인한다.

- [4-1 평가 환경·Test Case/Test Run·증빙 계약](../ai-alignment/04_llm_stage4_evaluation/4-1_평가환경_데이터계약.md): E0~E7의 환경별 실제/Mock·권리·실행 증빙과 미실행/차단 판정.
- [G1 47개 최종 사례 JSONL](../ai-alignment/04_llm_stage4_evaluation/g1_cases_PROPOSED.jsonl) · [70개 predicate 명세](../ai-alignment/04_llm_stage4_evaluation/g1_predicate_registry_PROPOSED.json) · [fixture/버전 manifest](../ai-alignment/04_llm_stage4_evaluation/g1_manifest_PROPOSED.json).
- [G1 상세 정답·합격 기준](../ai-alignment/04_llm_stage4_evaluation/G1_4-2_평가_정답_합격기준_검토안.md) · [사람 평가 CSV](../ai-alignment/04_llm_stage4_evaluation/g1_human_review_TEMPLATE.csv) · [정적 구조 전용 검사기](../ai-alignment/04_llm_stage4_evaluation/validate_cases_STRUCTURE_ONLY.py).
- [G2~G9a~c 대표 계약 38개 JSONL](../ai-alignment/04_llm_stage4_evaluation/g2_g9_38_cases_L2_CLOSED_NOT_RUN.jsonl) — 해당 G단계 착수 전 실데이터 fixture·Gold·임계치 확정.

**원본의 상태:** G1 CAT-09/CAT-14는 `revision=1`, `caseRevision=2`; G1 47개/70 predicate(구현 0), G2~G9 38개 L2 설계 계약. 신규 실제 평가/Gold/팀 승인/자동 실행 준비 완료로 표기 금지. 프로젝트 고정 연결 식별자를 평가 manifest에서 `${CATALOG_OBSERVED_ENV_REF}`로 정제했으며 실제 접속 문자열·키·토큰·AIHub 원문을 포함하지 않는다.
