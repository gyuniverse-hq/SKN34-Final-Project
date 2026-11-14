# VISHUE AI — Tool·근거 검증·데이터 접근 상세 설계 (2-5 설계 검토 기준)

> 상태: **REVIEW-CONCLUSION — 2-5 설계 범위 검토 종료 / 기술 계약 PROPOSED** (2026-11-15). 실제 구현·팀 승인·E2E 검증을 주장하지 않음.  
> 전제: [1단계 승인](01-user-experience.md), [2단계 목표 구조](02-architecture.md), [2-4 실행 계약](03-execution-contracts.md), [기존 문서 충돌](04-gap-analysis-and-2-5.md), [결정 로그](DECISIONS.md).  
> 목표: **대화는 자유롭게, 실제 사실은 근거로, 외부 행동은 권한과 실행 결과로 확정**.

## 1. Tool의 책임 경계

Tool은 Agent의 언어 계획을 실행 가능한 검증된 업무 계약으로 변환한다. 전문 Agent는 목표를 해석하고 다음 작업을 제안하지만, 실제 상품 존재·판매 옵션·전성분·레시피·AR 완료 여부를 임의로 만들어내지 않는다.

**권장 분리:** `Agent → Tool Registry → 권한/입력 검증 → 실행 어댑터 → 결과·근거 검증 → 구조화된 ToolResult → Agent/Supervisor`. 입력/출력 검증은 단순한 JSON 문법 검사뿐 아니라 요청 소유자, 선택 제품·호수 관계, 데이터 최신성, 이용권한과 적용 가능성을 포함한다.

## 2. 공통 Tool 계약 (개념)

```json
{
  "toolRequest": {
    "schemaVersion": "v1-proposed",
    "threadId": "example-thread",
    "turnId": "example-turn",
    "requestId": "example-request",
    "planId": "example-plan",
    "planVersion": 2,
    "taskId": "example-task",
    "toolName": "get_ingredients",
    "input": {"productId": "example-product", "optionId": "example-option"},
    "userScopeRef": "opaque-authorized-scope",
    "deadlineAt": "2026-11-15T00:00:00Z",
    "sourceRequirements": {"requireVerified": true}
  }
}
```

필수 반환 계약은 요청의 `taskId`와 버전을 보존하고 다음을 포함한다.

| 필드 | 의미 |
| --- | --- |
| `status` | `SUCCESS / PARTIAL / CLARIFICATION / UNKNOWN / UNAVAILABLE / ERROR / BLOCKED` 등 공통 상태 |
| `data` | 검색/검증이 수행된 구조화된 값 (가격·ID·옵션·색상 등) |
| `evidenceRefs` | 주장·상품·옵션·소스 ID, 발행/권리·검수 상태·sourceVersion |
| `coverage` | 검사 범위, 누락·중단 사유, 검색 시각, 데이터 스냅샷 |
| `toolExecution` | 지연/재시도/오류 분류/멱등성 키/실행 상태 |
| `proposedNextAction` | 추가 질문·재조회·타 도구 활용 후보. 확정 변경 아님 |

상태값과 스키마는 목표 설계 제안이며 기존 API의 상태 코드를 무단 변경하지 않는다. Tool별 HTTP 코드·Pydantic 스키마·오류 매핑·성능 요구는 2-5 추가 검토에서 확정한다.

## 3. 도구 그룹과 허용 권한

| 그룹 | 주요 Tool | 데이터/실행 경계 |
| --- | --- | --- |
| Product | `search_products`, `get_product_detail`, `compare_products` | Catalog API의 실제 상품·옵션·가격 유형·기준 시각·유효 범위 |
| Ingredient | `get_option_ingredients`, `check_ingredient_condition`, `get_ingredient_knowledge` | 전성분 귀속·원문 완전성·MFDS 표준명·판정 근거; 부재는 충분한 검수 자료가 있을 때만 |
| Style | `search_looks`, `get_style_recipe`, `find_style_alternatives` | 검수된 룩 태그/단계/기법·사용 제품·영상 구간 정보; 메타만으로 실제 영상 행동 확정 금지 |
| AR | `get_ar_state`, `propose_ar_action`, `request_ar_apply`, `get_ar_action_result`, `request_ar_undo` | 서버는 제안·상태/권한 조정; 기기 렌더러만 적용 확정, 동일 actionId 멱등성/ACK 필요 |
| Knowledge | `search_knowledge`, `lookup_source_evidence` | 이용권한·발행·철회가 확인된 문서만 검색 가능, 검색 전부터 접근 차단 |
| Visual | `analyze_reference_image`, `analyze_reference_video` | 명시적 업로드·모델 전달 동의 및 영상 구간/프레임·전사 관찰 범위 |
| Skin | `get_consented_skin_profile` | 동의 범위 내 구조화 데이터, experimental_unvalidated 모델 결과·자기보고 구별 |
| Conversation | `retrieve_previous_conversation`, `save_memory`, `delete_memory` | 과거 대화는 명시적 사용자 요청 B, 장기 저장은 동의/변경/삭제·소유권 확인 |
| STT/TTS | `transcribe_audio`, `synthesize_speech` | 모델·언어·재생 중단·발화 취소/보관 정책. 실제 음성 경로는 2-6과 공동 확정 |

명칭은 **목표 논리 도구 이름**이며 현재 저장소의 실제 엔드포인트·함수 이름과 일치한다고 주장하지 않는다. AR·메모리 삭제·업로드 같은 실제 변경 도구는 일반 읽기 Tool과 다른 실행 권한을 가진다.

## 4. 근거 검증 4단계

1. **실행 전 허용 범위**: Tool 사용 권한, 신원, 사용자 동의, 자료/문서 라이선스, 행동 범위, 대상 식별자 검증.
2. **조회 중 필터**: 권리 미확정·발행 전·철회된 자료를 검색 결과 후보에서 제외; 텍스트/벡터/관계 인덱스에 정책 일관 적용.
3. **결과 검증**: 실제 Catalog 현재 상품·옵션·가격 기준, 성분 완전성, 발행 출처·주장 연결·sourceVersion, 영상/이미지 관찰 범위 대조.
4. **응답·행동 확정**: 검증 가능한 카드·사실·조건 판정만 최종 답변으로 확정. 실제 AR/저장은 actionId·장치 결과·ACK를 별도 확인.

예: "향료 없는 립" 요청에서 데이터의 성분 이름에 `향료`가 없다고 무조건 `NOT_MATCH` (향료 없음)로 결정하지 않는다. 전성분 검수·옵션 귀속과 관련 판정 정책이 없으면 `UNKNOWN`을 반환하고 사용자가 추가 대안을 선택할 수 있게 한다.

**근거의 출처와 응답의 설명을 분리**한다. `ToolResult`에 있는 원본 사실과 `EvidenceRef`가 사용자 카드·필터·반환 순서를 결정하고, LLM은 이 범위 안에서 자연어 설명을 구성한다.

## 5. PostgreSQL / Neo4j / VectorDB 책임과 조회 정책

| 데이터 계층 | 주된 책임 | LLM/Agent 접근 |
| --- | --- | --- |
| Catalog PostgreSQL | 상품·실제 옵션·가격/성분·룩·검수 상태 원본 | 챗봇은 `backend/api` HTTP API 경유. 직접 DB 접근 금지(기존 ADR-0002) |
| 챗봇 전용 영속 PostgreSQL (제안) | 대화 이력/Checkpointer·동의 선호·Action Ledger | 별도 소유/권한 스키마/접속 자격, 팀 ADR 결정 전 미구현 |
| Neo4j | 검수된 상품/성분/룩 관계를 빠르게 탐색하는 파생 사본 | Graph Tool 경유. 관계 버전과 원본 검증 없으면 사실 확정 불가 |
| Vector Search | 사용이 승인된 문장형 지식·메이크업 기법을 의미 검색 | 검색 결과의 source/evidence/version/rights 검증, 원문을 무조건 LLM에 전달하지 않음 |
| Redis | 일시 후보·결과 집합 ID·세션·캐시·보조 멱등성 | 영속 복구·권한/실제 행동의 유일한 정본으로 사용 금지 |

`pgvector` 사용 vs 독립 VectorDB는 데이터 규모·사용권한 메타데이터·검색 품질·동기화·운영비를 3단계에서 비교한다. 벡터 색인은 데이터 그 자체의 검증을 대체하지 못한다.

### 검색 패턴별 근거 경로

| 사용자 질문 | 우선 검색 | 근거 확정 |
| --- | --- | --- |
| "이 제품 가격과 호수?" | Catalog 상품·옵션 Tool | 상품·옵션 ID 및 가격 유형/수집 시각 |
| "이 호수에 글리세린이 있어?" | 옵션 전성분 Tool | 완전성/매핑/검수·현재 sourceVersion |
| "이 룩과 비슷한 스타일?" | 검수된 룩 태그·관계 검색 | 실제 룩 ID, 승인 속성 및 해당 출처 |
| "그라데이션 립 방법?" | 승인된 기법 문서 검색·필요시 의미 검색 | 검수된 조언·근거·적용 범위 |
| "이 영상에서 실제 사용한 제품?" | 영상-제품 연결 검수 서비스 | 실제 사용 확인과 단순 언급·후보를 구분 |
| "아까 추천한 립?" | 현재 thread 결과집합/명시적 과거대화 검색 | 당시 참조를 찾은 뒤 현재 Catalog 재조회 |

## 6. 권리·검수 상태 차단 정책

AIHub 71961은 원본 QA 9,031건을 구조화한 기록이 있으나 이전 확인에서 **서비스용 승인·발행 자료 0건**이고 개별 이용조건이 미확정이다. [AIHub 이용권한 결정](../AIHUB_DATA_RIGHTS.md)에 따라 현재 **공용 배포, 원문 발췌 서비스 RAG 색인, 외부 LLM 원문 전달을 보류**한다. 이 사용권한 제한은 로컬 임베딩이나 LLM 요약만으로 해결되지 않는다.

문서/QA/주장·성분 매핑의 **권리, 검수, 발행은 서로 다른 상태 축**이다. `ingested` 또는 `source_matched`를 `approved`로 자동 승격하지 않는다. 다른 출처라도 개별 이용권한과 근거 검수 조건을 만족해야 한다.

## 7. 에러·실행 신뢰성 계약

| 오류 분류 | 처리 |
| --- | --- |
| `UNAUTHORIZED/FORBIDDEN` | 다른 사용자/스레드·미동의 미디어·도구 실행 차단 |
| `INVALID_ARGUMENT` | 스키마 검사, 수정 가능한 경우 재해석, 아니면 사용자에게 질문 |
| `NOT_FOUND` | 상품·룩·영상 참조를 재확인하고 대안 제시 |
| `EVIDENCE_PENDING / RIGHTS_BLOCKED` | 확정 주장을 금지, 허용된 다른 자료 조회 |
| `UNKNOWN_DATA` | 미확인으로 안내, 사용자 요청에 따라 다른 후보 탐색 |
| `TIMEOUT / UPSTREAM_ERROR` | 허용된 읽기 작업만 제한 재시도, 범위와 부분 결과 명시 |
| `STATE_CONFLICT` | 새 stateVersion/planVersion과 비교, 오래된 요청 결과를 최신 상태에 적용 금지 |
| `ACTION_UNKNOWN / ACK_MISSING` | 기존 actionId/commandId 결과를 조회하고 동일 행동 중복 실행 금지 |

외부 검색 결과·영상 설명·문서 내용은 **신뢰할 수 없는 데이터 입력**이다. 그 안의 문장을 새로운 시스템 명령이나 사용자 동의로 받아들이지 않는다. Tool 계층은 임의 SQL과 권한 우회 명령을 실행할 수 없다.

## 8. 2-5 세부 확정 전 남은 결정·검증

- Tool별 실제 입력/출력·Pydantic/HTTP 계약, 실제 API 호환성·권한 매트릭스.
- 상품 옵션·shade 식별 정합성, 수집가·현재가·재고·전성분 완전성 표시 계약.
- 자료별 권리·발행 API, sourceVersion/색인 버전, 관계/벡터 갱신/철회 전파 정책.
- Neo4j+Vector 검색 병합/재순위화 품질 검증과 실사용 데이터 커버리지.
- 사용자 미디어의 보존·삭제·외부 모델 전달/추적 원문 최소화.
- AR Action과 영속 Outbox는 2-6, 전체 비용·지연·실제 통합 검증은 2-7·4단계로 연결.

**2-5 설계 검토는 아래 10절의 경계를 기준으로 종료 판단한다.** Tool별 최종 endpoint·자료 권리·검색 엔진·테스트 통과 여부는 팀 승인/구현·3단계 검증 전에 확정했다고 보지 않는다. 시나리오 12개를 질문 화이트리스트로 만들지 않는다.

## 9. 한국어 우선·언어 독립성 및 상세 설계 연결 (2026-11-15)

**VAI-D-013 (ACCEPTED-USER):** 한국어(`ko`)가 첫 AI 개발·평가 언어다. 상품·전성분·스타일·AR 결과/근거 ID·원본 버전과 Tool 내부 오류/상태 코드의 의미는 언어와 독립적이며, 상품명·메이크업 용어의 한국어 검색 품질을 먼저 확인한다. 다른 `en/ja/zh` UI/Chat 로케일 코드는 삭제하지 않는다.

- **[07 언어·평가 계약](07-ko-first-language-and-evaluation.md):** 미지원 AI 기능의 언어별 안내/한국어 전환은 제안 상태, STT/TTS 가능 여부는 2-6에서 검토. 네 언어 동시 평가 TC-22는 후속으로 분리.
- **[06 Tool 구현 계약](06-tool-implementation-contracts.md):** 기존 API 경로·Pydantic 입력·응답·오류·권한 및 언어 독립 검증.
- **[08 옵션 복합 검색·근거·동기화](08-option-search-evidence-and-sync.md):** 현재 Raw option·가격 관측·성분 매핑·Neo4j 전체 교체의 한계, 읽기 전용 복합 검색 제안, 권리/버전 연계, 한국어 우선 Vector 검색/색인 확장성.

### 변경 이력

- 2026-11-15: 2-5 목표·검증 정책은 유지하면서 한국어 우선 및 새 상세 자료 링크만 추가. 내부 API·DB·코드는 미변경.

## 10. 2-5 설계 검토 종료: 범위·불변조건·인계

> **REVIEW-CONCLUSION (2026-11-15)**: 2-5가 책임지는 논리 계약(입출력·검증 기준·실패/권한 의미·저장소 접근 불변조건)은 구현 준비를 위한 **설계 검토 종료 기준에 충분**하다. 단, **ACCEPTED-USER인 1단계 범위와 다르게 기술 세부 선택은 PROPOSED**이며, 코드 구현·DB 적재·실제 E2E는 수행되지 않았다.

| 세부 범위 | 검토 판정 | 근거 문서 |
| --- | --- | --- |
| 2-5-1 Tool→기존 API 매핑 | **설계 검토 완료**: 현행/어댑터/신규 필요 구분 | [06 1절](06-tool-implementation-contracts.md) |
| 2-5-2 공통/전문 입출력·에러 | **설계 검토 완료**: 서버 주입 문맥, 모델, 오류 코드·후처리 경계 | [06 2~7·12절](06-tool-implementation-contracts.md) |
| 2-5-3 복합 검색·가격·상품 묶음 | **설계 검토 완료**: 가격 basis·observedAt 엄격 MATCH, 세 후보 그룹 | [08 2·8절](08-option-search-evidence-and-sync.md) |
| 2-5-4 근거·UNKNOWN/ERROR 판정 | **설계 검토 완료**: 옵션별 검수/원본/성분 연산자·사용권한 | [06 4·12절](06-tool-implementation-contracts.md) |
| 2-5-5 PG/Neo4j/Vector 접근 | **설계 검토 완료**: 원본-파생색인 소유권·원본 재확인·버전 불변조건 | [08 4절](08-option-search-evidence-and-sync.md) |
| 2-5-6 권한·철회·복구 | **설계 검토 완료**: 접근 전/응답 전 권한, 철회 시 fail-closed, 캐시/색인 갱신 | [06 12절](06-tool-implementation-contracts.md), [08 3~4절](08-option-search-evidence-and-sync.md) |
| 2-5-7 교차 계약 정합성·종료 판단 | **설계 검토 완료**: 미확정 기술 선택 인계, 필수 불변조건/시험 계획 정의 | 아래 책임 경계와 [06 12-3절](06-tool-implementation-contracts.md) |

### 10-1. 2-5에서 닫는 계약(설계상 필수)

- 사용자 요청과 Tool의 **입력·출력 스키마/ID·옵션 귀속·상태·근거·권한**의 의미.
- 가격의 `MATCH`는 **요청한 가격 종류·관측 시점·근거·옵션/조건**에만 유효. 검증하지 않은 현재가를 과거 수집가/참고가로 대체하지 않음.
- 필수 조건 전부 검증된 `MATCH`만 `ELIGIBLE`; 일부 `UNKNOWN/ERROR`는 `REFERENCE_ONLY`; 확정 `NOT_MATCH`가 있으면 `EXCLUDED`. `REFERENCE_ONLY`는 조건 충족 추천으로 가장하지 않음.
- 검증한 실제 상품·옵션/성분·권리/발행/버전·조회 범위만 확정. `keyIngredients`/Neo4j/Vector 결과는 완전한 전성분 또는 정본 판정 아님.
- 상품 Catalog PostgreSQL은 API 소유(ADR-0002). Graph/Vector는 파생 인덱스. 색인 버전·철회 상태 불확실하면 민감 지식 사용 중단, 별도 허용된 Catalog 조회는 계속 가능.
- `UNKNOWN`(근거 부족), `ERROR`(실행 실패), `FORBIDDEN`(권한 없음)을 구분하고 실제 외부 행동의 결과는 앱·Action Controller로 확인.

### 10-2. 다음 단계로 인계(이번 설계를 다시 늘리지 않음)

| 인계 단계 | 그 단계에서 확정할 내용 | 2-5의 현재 결정 상태 |
| --- | --- | --- |
| **2-6** | 앱 UI의 ELIGIBLE/REFERENCE_ONLY 표시·오류 안내; AR actionId/ACK/Undo·실기기 상태; 미디어 권한 UI·한국어 STT/TTS | 논리 결과 계약만 작성. UX 동작·AR/음성 구현 미확정 |
| **2-7** | 전체 시스템 장애 복구 시퀀스, 성능·호출 비용·보안·운영 배포, Agent/Tool 통합 승인·실측 | 계약 설계만 완료, 통합 검증 미실행 |
| **3단계** | 실제 원본 데이터·권리, 한국어 임베딩 모델·청크·벡터 엔진, Graph/Vector 인덱스/전체vs증분 동기화 방식·정량 검색 품질 | 인터페이스 불변조건만 작성, DB·검색 기술 선택 OPEN |
| **4단계** | 테스트셋·골든셋·합격 임계치·한국어 필수 평가, 후속 다국어 | 검증 사례 정의, 실행·수치 승인 미완료 |
| **5~6단계** | Tool endpoint 최종 경로, 카탈로그 복합 검색 구현 방식·담당·마이그레이션·테스트 PR | A/B 대안 남김, 실제 개발 단계에서 담당자 합의 후 확정 |

**2-5의 미해결 선택이 모두 지금 확정돼야 설계를 마칠 수 있는 것은 아니다.** 반대로 이 결론이 API·DB·Graph/Vector·LLM/AR 통합 구현을 승인했다는 의미도 아니다.

### 10-3. 이후 문서화·결정 관리

- 새 사용자 결정이 필요한 새 안건은 대화에서 먼저 선택지·영향·추천 근거를 제시한다. 확정이 없던 `OPEN-T01`, `OPEN-SYNC-01`, `OPEN-VECTOR-01`, `OPEN-RIGHTS-01`을 채택 결정으로 승격하지 않는다.
- 2-5 설계 종료 시의 문서 변경은 이번에 일괄 반영하며, 2-6/2-7의 일반 토론마다 GitHub·Notion을 갱신하지 않는다. 중요한 충돌은 예외로 처리.
- [결정 로그](DECISIONS.md)의 상태를 참고하고 실제 코드/실기기 검증 성공 표기에는 별도 재현 근거를 요구한다.

### 변경 기록

- 2026-11-15: 2-5-5~2-5-7 설계 범위 종료 판단·가격/후보 판정·권한·철회·실패 책임·후속 단계 인계를 일괄 기록. **설계 검토 완료, 기술 팀 승인/구현·시험 완료 아님**.
