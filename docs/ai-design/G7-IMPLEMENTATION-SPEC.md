# VISHUE G7 구현 명세서 v1.1 — 네 가지 계약 보완

> **용도:** Codex가 읽고 G7-1~G7-7을 순차 구현할 수 있는 실행 계약. **설계 문서이며 구현·테스트 완료 증빙이 아니다.**
>
> **기준 시각:** 2026-11-23 (KST) · **확인한 `develop`:** `d9c6a77c1467d11465a72c66b8f2579b8ab68609` · **상위 설계:** [PR #241](https://github.com/gyuniverse-hq/SKN34-Final-Project/pull/241)
>
> **문서 위치:** `docs/ai-design/G7-IMPLEMENTATION-SPEC.md` · **파일 상태:** 전달용 v1.1에 중복 요청 순서, 실행 세대, 계정 단위 멱등성, 삭제 완료 계약을 보완한 저장소 문서. 구현·테스트 완료를 뜻하지 않는다.

## 0. 문서 활용과 결정의 상태

### 0.1 목적

G7은 **로그인 사용자의 영속 대화방·현재 상담 상태 재개·명시적 동의 기반 장기 기억**을 구현한다. G1~G6의 `ChatService`·Tool·AR·ACK·게스트 상담은 재사용한다. G8을 대비하되 G7에서 전 상담 경로를 LangGraph로 재작성하거나 별도 자율 Memory Agent를 만드는 작업은 하지 않는다.

### 0.2 우선순위 및 변경 관리

1. 이 문서의 **확정된 사용자 정책 및 이 문서의 G7 구현 계약**을 먼저 따른다.
2. PR #241의 사용자 경험·실행·공통 문맥 계약은 유지한다. G7에서 더 구체화한 항목만 이 문서가 보완한다.
3. 실제 코드와 충돌하면 임의로 설계를 폐기하지 않는다. **기존 동작을 보존할 어댑터를 우선 구현**하고 충돌·해결을 PR에 기록한다.
4. DB·지식 저장소에 대해서는 [ADR-0012](https://github.com/gyuniverse-hq/SKN34-Final-Project/blob/d9c6a77c1467d11465a72c66b8f2579b8ab68609/docs/adr/0012-pgvector-instead-of-neo4j.md)가 이전 ADR-0002의 Neo4j 전제를 대체한다. 기존 `AGENTS.md`·아키텍처 문서에 남은 Neo4j 설명을 G7의 신규 설계로 채택하지 않는다.
5. 팀 인프라 권한, API 담당자 공동 `DELETE /api/me` 변경은 **미확정 외부 의존성**이다. 로컬의 G7 독립 구현을 진행하되, 공동 삭제가 완성되기 전 운영용 G7 영속 기능을 켜지 않는다.
6. 작업 브랜치에서만 구현하고, `develop`/`main` 직접 수정·자동 병합 금지. 기존 작업 브랜치가 있으면 HEAD와 미반영 커밋을 먼저 확인한다. 선행 브랜치 내용의 존재나 테스트 성공을 가정하지 않는다.

### 0.3 사용자 확정 정책 — 변경하지 말 것

| 정책 | 게스트 | 로그인 사용자 |
|---|---|---|
| G1~G6 상담 | 기존과 동일하게 지원 | 지원 |
| 현재 대화 맥락 | 앱 실행 중 유지 | 서버가 복원한 현재 대화 사용 |
| 대화방 영속 저장·재실행 복원 | 미지원 | 지원 |
| 계정 로그인 시 게스트 대화 이전 | 미지원 | 이전 받지 않음 |
| 장기 기억 | 미지원 | 명시적 동의 후 저장·조회·수정·삭제 |
| 이전 대화방 조회 | 재실행 이후 없음 | **명시적 요청 또는 사용자 방 선택**에만 접근. 자동 타 방 검색 금지 |

게스트의 Redis 단기 세션(최대 600초)은 **검색 실행 보조 상태**이지 G7 영속 기록이 아니다. 앱 재실행 시 게스트의 대화방·메시지를 저장소에서 복원하지 않는다.

### 0.4 G7 v1.1 보완의 다섯 가지 불변조건

- **서버 문맥 정본:** 로그인 요청은 `ConversationService`가 PostgreSQL의 현재 상담 상태와 제한된 최근 메시지를 읽어 `ChatService`에 제공한다. 앱의 `chatContext`, `recentMessages`, `styleContext`, 후보 순번을 정본으로 신뢰하지 않는다.
- **Checkpoint 검증:** 마지막 **완료된** 대화 버전에 결합된 Checkpoint만 복원한다. `thread_id`의 최신 Checkpoint를 무조건 사용하지 않는다. Checkpoint에 전체 `ChatResponse`, 세션 토큰·계정 인증 토큰을 저장하지 않는다.
- **중단·멱등:** `IN_PROGRESS` 중단을 판정하고 조회할 수 있어야 한다. `COMMITTED`는 재실행하지 않는다. 결과가 불명확한 AR·외부 변경은 자동 재실행하지 않는다.
- **인증·첫 진입:** 영속 소유자 ID는 검증된 JWT의 `AuthUser.id`다. `rate_limit_key`와 분리한다. 로그인 앱은 **첫 질문 전에** 서버 대화방을 만들고 ID를 전달한다. 구형 `conversationId` 없는 요청은 기존 경로를 유지한다.
- **탈퇴:** API 서비스가 탈퇴 작업을 총괄하고 챗봇이 영속 접근 차단·삭제를 담당한다. API 공동 연동 미완료 시 G7 영속 기능의 **운영 활성화 금지**.

---

## 1. 확인한 코드 기준선과 회귀 위험

최신 기준선은 `develop` `d9c6a77`이며, 실제 코드는 구현 시 다시 fetch/rebase하여 차이를 기록한다.

| 코드 | 확인된 현재 동작 | G7 작업 경계 |
|---|---|---|
| `backend/chatbot/app/core/auth.py::chat_principal` | Bearer 검증 실패 후 익명 헤더가 있으면 게스트가 될 수 있음 | **인증 실패 ≠ 게스트**, G7-1에서 수정 |
| `backend/chatbot/app/core/auth.py::require_user` | JWT 검증 후 `AuthUser.id` 반환 | 영속 엔드포인트에 재사용 |
| `backend/chatbot/app/routers/chat.py::chat` | `POST /api/chat` → `ChatService.answer(req, principal.rate_limit_key)` | 영속 요청만 `ConversationService`로 분기; 레거시 그대로 |
| `backend/chatbot/app/schemas/chat.py::ChatRequest` | `requestId`·`chatContext`·`recentMessages` 존재. `ignore_ar_fields_for_chat`가 조건에 따라 일반 채팅의 `requestId`를 제거함 | G7 요청 식별자는 **필수 보존**; AR·구형 경로 회귀 금지 |
| `backend/chatbot/app/services/chat_service.py::answer` | style 검색, knowledge, G2, AR, supervisor 등 여러 조기 반환 경로 | 영속 처리 전후의 래퍼를 사용하여 특정 경로 누락 방지 |
| `ChatService._run_supervisor` | `thread_id` 유무가 G1 선택 로직에 영향을 줌 | Redis G2 의미와 LangGraph 영속 ID를 분리 |
| `ChatService._answer_session` + `ChatSessionRepository` | `sessionId`, `resultSetId`, `stateVersion`, Redis WATCH/CAS, TTL ≤600초; `last_response`에 전체 JSON 일시 저장 | **Redis 자체 구조를 재구축하지 말 것**. Redis 토큰을 PostgreSQL·Checkpoint에 복제하지 않음 |
| `schemas/vishue_state.py::VishueState` | 단일 턴 필드 및 `response: ChatResponse` | 영속 Checkpointer에 응답 전체가 기록되지 않도록 조정 |
| `services/product_consultation_graph.py` | `plan_turn → execute_turn`, `.compile()`에 영속 Checkpointer 없음 | 실제 그래프 실행 경로에만 Checkpointer 도입 |
| `schemas/style_recipe.py::StyleContext` | `kind/lookId/recipeId/recipeVersion/currentStep` | 기존 타입·검증 재사용 |
| `store/chatConversationStore.ts` | 메모리 상태의 방·메시지·선택·요청 스냅샷, 사용자 변경 시 초기화 | 게스트 그대로; 로그인은 서버 하이드레이션(hydration) 추가 |
| `lib/api.ts::apiPostChat`, `app/chat.tsx` | 인증자 고정·진행 중 응답 격리의 기존 장치 있음 | 첫 방 생성, 계정별 서버 조회, PATCH 지원 추가 |
| `backend/chatbot/app/main.py` | Chatbot CORS 허용 메서드 POST | G7 GET/PATCH/DELETE 허용 |
| `backend/api/app/services/member_service.py::delete_account` | Supabase 계정 선삭제, 회원 DB 후삭제 | 챗봇 삭제·탈퇴 작업 기록을 포함하도록 **API 담당자 공동 계약** 필요 |
| `infra/compose/compose.yaml` | API는 PostgreSQL, 챗봇은 Redis/Neo4j 중심 설정 | 챗봇 전용 DB·마이그레이션의 로컬 경로 신규 추가 |

**주의:** `backend/api`가 지식·임베딩 저장을 관리할 수 있다는 ADR-0012와, 챗봇이 **사용자 대화·기억 DB를 독립 관리**한다는 G7 결정은 동시에 만족해야 한다. 지식/Catalog 테이블에 G7 개인 대화를 넣지 않는다.

---

## 2. 저장소 책임과 식별자 계약

### 2.1 저장소별 유일 정본

| 데이터 | 정본·수명 | 복원 시 원칙 |
|---|---|---|
| 대화방 소유권, 현재 목표, 선택 상품·룩·조건·단계, 완료 버전 | `vishue_chat_db.chat_conversations` | 서버에서 소유권 확인 후 읽음 |
| 사용자·AI 메시지와 표시용 카드/레시피의 **당시 결과** | `chat_messages` | 이력 표시용. 당시 상품 상태를 최신 사실로 사용 금지 |
| 논리 요청·동시성·확정 상태 | `chat_turns` | 중복 실행 금지, 완료 결과 참조 |
| 동의한 선호·프로필·보유 제품 | `chat_memories` | 활성·동의 범위·철회 버전 검사 |
| 사용자 삭제 차단 및 기억 철회 버전 | `chat_owner_status` | 모든 영속 조회·쓰기·복원 진입점에서 검사 |
| LangGraph 노드·중단 위치·안전한 실행 참조 | 별도 Checkpointer 테이블 | **DB에서 승인한 Checkpoint ID+버전**만 활용 |
| 단기 후보·확인 질문·Redis CAS·세션 capability | 기존 Redis | TTL 안에서만 활용, 영속 토큰 복원 금지 |
| Catalog 상품·옵션·성분·룩의 현재 사실 | 기존 Catalog API | 현재 API·근거 상태 재검증 |
| 실제 AR 렌더·적용·ACK | 앱 렌더러 및 AR 기존 계약 | 대화·Checkpoint만으로 실행 성공 판단 금지 |
| 화면 스크롤·입력 초안·진행 중 요청 UI | 기존 Zustand | 서버 소유 정본으로 쓰지 않음 |

### 2.2 식별자와 버전 — 이름을 섞지 말 것

| 키 | 의미 | 소유권/유효기간 |
|---|---|---|
| `ownerId` | **JWT 검증 후 `AuthUser.id`** | 로그인 계정. 클라이언트 제공 owner 사용 금지 |
| `rate_limit_key` | 현재 `user:...` / `guest:...` 요청 제한용 | **영속 소유자 ID로 사용 금지** |
| `conversationId` | 영속 대화방 UUID | 서버 발급, 계정 소유 |
| `threadId` | LangGraph 영속 실행 스레드 UUID | 대화방과 1:1 매핑, 서버 관리 |
| `checkpointId` | 라이브러리 Checkpoint 식별자 | `conversationVersion`과 별도; 완료 DB에서 참조 |
| `conversationVersion` | PostgreSQL 상담 상태의 단조 증가 버전(0부터) | 완료 원자적 트랜잭션마다 +1 |
| `sessionId` / Redis `stateVersion` | G2 600초 상품 세션·CAS | 영속 버전이 아님; 의미 불변 |
| `resultSetId` | 단기 후보 집합 참조 | 만료 시 재사용 금지 |
| `requestId` | **한 논리 요청**의 멱등 키(UUID) | 같은 요청 재전송에 동일 ID·동일 fingerprint |
| `turnId` | 완료된 논리 사용자 발화 식별자(UUID) | DB 메시지 연결 |
| `memoryVersion` / `revocationEpoch` | 기억별 CAS 버전 / 계정 철회 세대 | 기억 변경·삭제 시 사용 |
| `actionId` / `arStateVersion` | 실제 AR 상태 변경 식별 | 기존 AR 실행 계약이 정본 |
| `sourceVersion` | 제품·성분·룩 근거 버전 | 복원 시 재검증 기준 |

### 2.3 체크포인터 연결 형태

- **로그인 실제 그래프 실행만** `AsyncPostgresSaver`를 사용한다. 게스트 그래프는 기존 비영속 동작 유지.
- G7 대화방의 `thread_id`와 기존 `_run_supervisor(thread_id=...)` 인자를 그대로 합치지 않는다. 해당 인자는 현재 G1 처리 분기 판단에도 사용된다. **영속 그래프 실행 설정(configurable.thread_id)과 G2 상품 세션 문맥 인자를 분리**해야 한다.
- 체크포인트에는 토큰·전체 `ChatResponse`·사용자 기억 원문·대용량 자료를 직렬화하지 않는다. 기존 `VishueState.response`는 저장 가능한 `result_ref`, `execution_status` 등의 안전한 필드로 교체하거나 응답 객체를 per-invocation runtime으로만 전달한다. 실제 LangGraph serializer가 무엇을 저장하는지 테스트한다.
- `chat_conversations.accepted_checkpoint_id`, `accepted_checkpoint_version`에 **DB에서 완료 승인한 Checkpoint**를 기록한다. Checkpointer 내부의 최신 상태만을 조회 기준으로 사용하지 않는다.
- 노드 중간 Checkpoint는 있을 수 있다. DB의 승인된 ID와 버전에 해당하지 않으면 다음 요청에 자동 적용하지 않는다. `checkpointId`만으로 소유권을 인정하지 않는다.

---

## 3. 물리 DB 및 최소 스키마

### 3.1 데이터베이스 배치

**기본안:** 기존 PostgreSQL 인스턴스에 `vishue_chat_db`와 챗봇 전용 DB 역할·자격증명을 추가한다. 새로운 DB 서버를 만들지 않는다. G7 전용 Alembic 마이그레이션을 `backend/chatbot`에서 관리한다.

- `backend/api`의 Catalog 테이블과 G7 사용자 대화 테이블은 분리한다.
- 로컬에서는 Docker Compose로 DB 생성·마이그레이션을 재현한다. 운영 RDS DB/역할 생성 권한은 **팀 인프라 승인 대기**.
- 물리 별도 DB가 팀 권한상 불가능한 때에만 같은 PostgreSQL 내 전용 `chatbot` **스키마/역할** 대안을 검토한다. 동일한 권한 경계를 유지한다.
- Checkpointer 스키마 초기화(`setup`)는 명시적 배포·마이그레이션 단계에서 실행하여 여러 API 프로세스가 동시에 초기화하지 않도록 한다. 버전·의존성은 구현 때 `uv.lock`과 라이브러리 API를 확인한다.

### 3.2 DDL 기준안

아래 SQL은 **논리 스키마를 고정하기 위한 기준안**이다. 실제 마이그레이션에서는 Alembic·SQLAlchemy 및 DB 제약과 시간대·인덱스를 맞춘다. 테스트·운영 데이터 변경 없이 문서만으로 테이블이 생성되는 것은 아니다.

```sql
CREATE TABLE chat_owner_status (
  owner_id VARCHAR(64) PRIMARY KEY,
  status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'DELETING', 'DELETED')),
  revocation_epoch BIGINT NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE chat_conversations (
  id UUID PRIMARY KEY,
  owner_id VARCHAR(64) NOT NULL REFERENCES chat_owner_status(owner_id),
  thread_id UUID NOT NULL UNIQUE,
  subject_json JSONB NOT NULL,
  context_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  schema_version INT NOT NULL DEFAULT 1,
  conversation_version BIGINT NOT NULL DEFAULT 0,
  accepted_checkpoint_id TEXT NULL,
  accepted_checkpoint_version BIGINT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ NULL
);
CREATE INDEX chat_conversations_owner_updated_idx
  ON chat_conversations(owner_id, updated_at DESC) WHERE deleted_at IS NULL;

CREATE TABLE chat_messages (
  id UUID PRIMARY KEY,
  conversation_id UUID NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
  sequence BIGINT NOT NULL,
  role VARCHAR(12) NOT NULL CHECK (role IN ('user', 'assistant')),
  text TEXT NOT NULL,
  display_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  request_id UUID NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(conversation_id, sequence)
);
CREATE INDEX chat_messages_conversation_idx ON chat_messages(conversation_id, sequence);

CREATE TABLE chat_turns (
  owner_id VARCHAR(64) NOT NULL REFERENCES chat_owner_status(owner_id),
  request_id UUID NOT NULL,
  conversation_id UUID NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
  operation VARCHAR(32) NOT NULL,
  fingerprint CHAR(64) NOT NULL,
  status VARCHAR(16) NOT NULL
    CHECK (status IN ('IN_PROGRESS', 'COMMITTED', 'FAILED', 'INTERRUPTED')),
  base_version BIGINT NULL,
  committed_version BIGINT NULL,
  result_resource_id UUID NULL,
  result_version BIGINT NULL,
  result_payload JSONB NULL,
  turn_id UUID NULL,
  response_message_id UUID NULL,
  lease_until TIMESTAMPTZ NULL,
  attempt_count INT NOT NULL DEFAULT 1,
  error_code VARCHAR(64) NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(owner_id, request_id),
  CHECK (operation NOT IN ('chat', 'state_update') OR
         (conversation_id IS NOT NULL AND base_version IS NOT NULL))
);
CREATE INDEX chat_turns_conversation_idx ON chat_turns(conversation_id, created_at DESC);

CREATE TABLE chat_memories (
  id UUID PRIMARY KEY,
  owner_id VARCHAR(64) NOT NULL REFERENCES chat_owner_status(owner_id),
  kind VARCHAR(24) NOT NULL CHECK (kind IN ('preference', 'profile', 'owned_product')),
  memory_key VARCHAR(128) NOT NULL,
  value_json JSONB NULL,
  version BIGINT NOT NULL DEFAULT 1,
  consent_scope VARCHAR(64) NOT NULL,
  source_message_id UUID NULL REFERENCES chat_messages(id) ON DELETE SET NULL,
  confirmed_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX chat_memories_owner_active_key_uidx
  ON chat_memories(owner_id, kind, memory_key) WHERE revoked_at IS NULL;
```

**추가 제약/규칙:**

- 위 DDL은 `chat_turns`를 요청 기록으로 확장한 기준안이다. `chat`·`state_update`는 `conversation_id`와 `base_version`이 필수이고, `conversation_create` 및 `memory_create`·`memory_update`·`memory_delete`는 방 없이 예약할 수 있다. 실제 마이그레이션은 허용 `operation` 목록, 작업별 필수 필드·완료 결과에 대한 DB 제약을 정의한다. 별도 요청 기록 테이블을 선택하더라도 같은 멱등·소유권·삭제 계약을 만족해야 한다.
- 방 생성은 생성 전 방 ID가 없으므로 요청 기록의 방 FK를 필수로 삼지 않는다. 방 생성 결과 ID, 기억 생성·수정 결과 ID와 버전, 기억 삭제 완료 여부를 재전송 시 확인 가능하게 한다. 위 기준안의 `result_resource_id`·`result_version`은 작업별 결과 참조다. 완료 여부는 `status`와 작업 종류로 구분하며 삭제된 내용·기억 값·메시지 원문을 결과 기록에 넣지 않는다.
- 상태 PATCH의 완료 결과는 같은 트랜잭션에서 `result_payload`에 기록한다. 허용 구조는 `conversationId`, 완료 `conversationVersion`, 검증된 상담 상태 `context`이며 인증·Redis 토큰, 메시지 원문, 원시 Tool 결과, 얼굴 이미지·영상은 넣지 않는다. 동일 요청 재전송은 이후 대화 버전이 바뀌었더라도 이 당시 결과를 반환한다. 방 물리 삭제 시 해당 턴과 스냅샷도 함께 삭제한다.
- 요청 예약과 작업 완료 결과는 실제 방 생성·기억 변경과 모순되지 않도록 트랜잭션 경계를 정한다. 결과 유실 후 같은 `requestId`와 fingerprint는 중복 실행 없이 결과를 확인하고, 다른 fingerprint는 409다.
- 방 삭제 시 FK의 `ON DELETE CASCADE`로 방에 연결된 턴 기록이 제거될 수 있다. 방 생성 요청을 계정 단위로 기록하는 경우 결과 방이 삭제되면 해당 생성 요청의 재전송은 방을 재생성하거나 삭제된 내용을 반환하지 않고 삭제된 결과임을 안내한다. 재시도 보장 기간·만료 후 동작은 G7-2에서 명시한다. 삭제된 콘텐츠를 멱등성 기록에 보존하지 않는다.
- `chat_turns.response_message_id`는 완료된 AI 응답 메시지 참조다. 스키마 마이그레이션에서 FK 적용 가능성과 동시 삽입 순서를 검토한다.
- `subject_json`은 기존 `ConversationSubject`(`general`/`product`/`look`)의 허용된 구조만 저장한다.
- `context_json`은 스키마 버전이 있는 **허용 목록(allowlist) 상태**만 저장한다. `chatContext.session`, `sessionToken`, Authorization, 모든 프롬프트/원시 Tool 결과 전체, 얼굴 이미지·영상 등은 금지한다.
- `display_payload`는 당시 카드·룩·레시피 참조와 UI 표시에 필요한 검증된 필드만 보관한다. 상태 정본·권한 토큰을 넣지 않는다.
- 장기 기억 삭제 시 `revoked_at` 설정과 `value_json=NULL` 또는 해당 값의 안전한 제거를 수행하고 `revocation_epoch`를 증가시킨다. 삭제의 재시도는 멱등이어야 한다.
- 삭제된 계정의 `owner_id` 보유와 오래된 JWT 차단 기간 사이에 개인정보 보존 문제가 있다. **운영에서는 필요한 최소 기간의 재사용 방지 표식(가능하면 HMAC 기반 불가역 식별자)을 유지하고, 계정 삭제 후 정본 개인정보를 보존하지 않는 방식**을 API·인프라와 정한다. JWT 만료 이전에 차단 표식을 없애서는 안 된다.
- Checkpointer 라이브러리 전용 테이블은 앱 정본 테이블로 취급하지 않는다. 대화방 삭제·탈퇴 시 라이브러리의 thread 삭제 경로와 연동한다.

### 3.3 상담 상태 JSON 계약

```json
{
  "schemaVersion": 1,
  "currentGoal": {"domain": "style", "status": "active"},
  "product": {
    "selectedProductId": null,
    "selectedShadeId": null,
    "filters": {},
    "historicalCandidateRefs": [],
    "sourceVersion": null
  },
  "style": {
    "kind": "video",
    "lookId": "example-look-id",
    "recipeId": null,
    "recipeVersion": null,
    "currentStep": 0,
    "conditions": [],
    "historicalCandidateRefs": []
  },
  "pendingGoal": null,
  "memoryRevocationEpoch": 0
}
```

- `example-look-id`는 예시일 뿐 유효한 실제 데이터임을 뜻하지 않는다.
- 위 필드는 **논리 개념**이다. 실제 타입은 `BeautyFilters`, `StyleContext`, `StyleCondition`, G2 pending 타입을 가져와 중복 설계를 최소화한다.
- 후보 참조는 *과거 대화의 선택 맥락*을 위한 것이며, Redis 만료 후보의 현재 유효성·순번을 증명하지 않는다.
- 사용자가 수정한 목표·필터·룩·레시피 단계는 앱 재실행 후 후속 질문에 필요하므로 서버에 저장한다. 실제 AR 상태는 저장하지 않는다.

---

## 4. API 계약 v1.1

**공통:** JSON camelCase, `Authorization: Bearer <JWT>`는 인증된 영속 요청 필수, `ownerId`는 요청 본문에서 받지 않는다. 오류는 기존 `{ "error": "...", "code": "..." }` 형식을 보존한다. 신규 영속 API는 `require_user`를 기본으로 한다.

### 4.1 로그인 첫 진입·방 생성

`POST /api/chat/conversations`

```json
{
  "requestId": "c5c5ca25-184f-4f76-a516-8cf9008c69f7",
  "entry": {"type": "general"}
}
```

성공 `201` (동일 requestId·fingerprint 재요청은 같은 논리적 방 반환; 구현상 기존 방 확인 후 `200` 허용):

```json
{
  "conversationId": "2e36f027-2d57-44a1-b882-38a291d4ce94",
  "conversationVersion": 0,
  "subject": {"type": "general"},
  "createdAt": "2026-11-23T09:00:00Z"
}
```

- **로그인 상담 첫 메시지 이전**에 앱이 호출해 `conversationId`를 확보한다. 제품/룩 화면에서 진입할 때는 `entry`를 `product`/`look`로 생성한다.
- 방 생성 실패 시 **영속 저장이 된 것처럼 기존 `/api/chat`으로 조용히 전환하지 않는다**. 오류·재시도를 안내한다.
- 기존 앱의 `conversationId` 없는 상담 요청은 레거시 경로로 그대로 허용한다. **구형 요청의 자동 영속화는 하지 않는다.**
- 게스트가 이 엔드포인트 호출 시 `401`. 게스트에 별도 영속 방을 만들지 않는다.

### 4.2 대화방 목록·조회·삭제

| 메서드 | 경로 | 핵심 계약 |
|---|---|---|
| GET | `/api/chat/conversations?limit=20&cursor=...` | 본인 방만 최신 수정 순, 안정된 커서·`nextCursor` |
| GET | `/api/chat/conversations/{id}` | 본인 이력 페이지·`context`·`conversationVersion`·복원 상태 |
| DELETE | `/api/chat/conversations/{id}` | 본인 방 차단 후 메시지·턴·Checkpoint 정리, 실패 시 재시도; 필수 정리 완료 후에만 완료 응답 |
| GET | `/api/chat/conversations/{id}/requests/{requestId}` | 본인 요청의 `IN_PROGRESS/COMMITTED/FAILED/INTERRUPTED`, 완료 시 결과 참조 |

**방 삭제 처리:** 먼저 방을 삭제 진행 상태로 만들어 조회·재개·새 쓰기를 차단하고, 진행 중인 턴은 완료 커밋에서 삭제 여부를 다시 확인한다. 메시지·턴·상담 상태·해당 thread의 Checkpoint를 정리하며, `deleted_at`만 설정해서는 `ON DELETE CASCADE`가 실행되지 않는다. 정리 실패는 단계별로 식별·재시도할 수 있어야 하고 Checkpoint 삭제에 필요한 thread 참조를 정리 완료 전 잃지 않는다. 필수 정리가 확인되기 전에는 물리 삭제 완료로 응답하지 않는다. 비동기 처리라면 진행 중 응답·상태 조회 계약을 구현 전에 정의한다. 대화방에서 출처를 얻은 별도의 동의된 장기 기억은 자동 삭제하지 않고, 출처 메시지와의 연결을 안전하게 해제한다.

GET 상세 응답 예시:

```json
{
  "conversationId": "2e36f027-2d57-44a1-b882-38a291d4ce94",
  "conversationVersion": 4,
  "subject": {"type": "look", "kind": "video", "lookId": "example-look-id"},
  "context": {"schemaVersion": 1, "style": {"kind": "video", "lookId": "example-look-id", "currentStep": 2}},
  "messages": [{"id": "16b5d3bf-9c30-45d9-b91a-09fc9e23fe19", "role": "assistant", "text": "립을 더 강조하는 방법이에요.", "displayPayload": {}}],
  "nextMessageCursor": null,
  "restoreStatus": "ready"
}
```

`restoreStatus` 값은 최소 `ready`, `needs_revalidation`, `partial`을 사용한다. 과거 카드·조건이 최신 유효하다고 단정하지 않는다. 요청 ID·토큰·전체 실행 상태는 응답에 노출하지 않는다.

### 4.3 기존 `POST /api/chat` 확장

로그인 영속 요청:

```json
{
  "conversationId": "2e36f027-2d57-44a1-b882-38a291d4ce94",
  "expectedConversationVersion": 4,
  "requestId": "ef3b54e3-cd78-4ff6-9b27-27fbf4b8403d",
  "message": "아까 선택한 룩에서 립을 더 강조하면?",
  "locale": "ko",
  "requestType": "chat"
}
```

현재 `ChatResponse`의 `answer`, `products`, `chatContext`, `styleContext` 등 기존 필드를 유지하며 **추가 메타데이터**를 전달한다.

```json
{
  "conversation": {
    "id": "2e36f027-2d57-44a1-b882-38a291d4ce94",
    "version": 5,
    "turnId": "94f579bb-07ce-4bcd-9021-4efdf8b9452c",
    "persistenceStatus": "stored"
  }
}
```

- `conversationId`가 있을 때 `requestId`, `expectedConversationVersion`을 필수로 검사한다.
- 인증된 사용자와 서버의 `(conversationId, ownerId)` 관계를 검사한다. `conversationId`는 서명된 권한 수단이 아니며 추측 가능한 ID만으로 접근할 수 없다.
- 앱 `recentMessages`, `chatContext`, `styleContext`를 **서버 영속 정본으로 신뢰하지 않는다**. 서버가 `context_json`과 필요한 최근 메시지(우선 기존 최대 8개/8,000자 한도 이내)를 읽고 `ChatService`에 전달한다. 화면 포커스 힌트 등은 별도 검증 후만 적용한다.
- 현재 `ChatRequest.ignore_ar_fields_for_chat`가 일반 상담에서 `requestId`를 제거하는 구간을 보완하되 구형 G1 OFF·AR·G2 계약은 회귀시키지 않는다.
- `requestType=ar_command`는 G7의 대화방 영속 처리로 부작용을 새로 만들지 않는다. 기존 AR 실행·ACK 경로를 보존하고 실제 수행 완료가 불명확한 명령은 재실행하지 않는다.
- 구형 `conversationId` 누락 요청은 기존 경로. 게스트가 `conversationId`를 제출하면 `403` (`persistent_login_required` 등 일관된 코드)로 거부한다. 로그인 유효성이 없으면 `401`이 우선한다.

### 4.4 메시지 없이 바뀌는 선택·룩 단계

`PATCH /api/chat/conversations/{id}/state`

```json
{
  "requestId": "ce34b3ce-485e-49de-a0af-655af2080665",
  "expectedConversationVersion": 5,
  "operation": "set_recipe_step",
  "payload": {"kind": "video", "lookId": "example-look-id", "recipeVersion": "v1", "currentStep": 2}
}
```

허용된 `operation` 목록: `select_product`, `select_shade`, `select_look`, `set_recipe_step`, `clear_selection`. 임의 전체 JSON 교체 금지. 서버는 Catalog·룩 타입·레시피 버전·단계 범위를 검증하고 CAS로 현재 상태만 수정한다. **AR 실행 명령이 아니다.**

성공 시 `{ "conversationId": "...", "conversationVersion": 6, "context": { ... } }`를 반환한다. 409 충돌 시 앱은 서버 상태 재조회 후 사용자에게 필요한 재시도를 안내한다.

### 4.5 장기 기억 API

| 메서드 | 경로 | 계약 |
|---|---|---|
| GET | `/api/chat/memories` | 현재 로그인 사용자 활성·동의 기억만 |
| POST | `/api/chat/memories` | 서버가 제안한 `proposalId` 확인 후 저장, `requestId` 멱등 |
| PATCH | `/api/chat/memories/{id}` | 본문 `requestId`, `expectedVersion` CAS, 사용자 확인 필요 |
| DELETE | `/api/chat/memories/{id}` | `Idempotency-Key` 헤더의 UUID 요청 ID, 사용자 소유 확인, 철회·무효화, 멱등 |

기억 저장 예시:

```json
{
  "requestId": "9293f79f-8f85-4919-8be2-136f61d51e8e",
  "proposalId": "server-issued-proposal-id",
  "expectedProposalVersion": 1,
  "confirmed": true
}
```

- 모델은 사용자 발화에서 **기억 저장 후보**만 제안한다. 저장 후보의 정본과 소유권·범위·만료는 서버에 두며, 앱이 임의로 보낸 `value`를 확인 없이 저장하지 않는다.
- `proposalId`는 서버에서 발급·검증한다. 미확정 후보는 현재 대화의 `pendingGoal` 등에 보유할 수 있으나 **장기 기억 테이블에는 저장하지 않는다**. 후보를 별도 영속 DB 시스템으로 만들 필요는 없다.
- 저장 성공 전에는 사용자에게 “기억했어요”라고 답하지 않는다. 임시 대화 문맥과 동의한 장기 기억을 분리한다.
- 동일 기억 삭제·수정과 오래된 버전의 저장 제안은 무효화한다. 생성·수정·삭제의 요청 ID는 계정 범위에서 fingerprint와 함께 기록한다. 삭제 재시도는 이미 철회한 기억 값을 되살리거나 철회 세대를 중복 증가시키지 않는다.

### 4.6 HTTP 오류 및 가시 상태

| 코드 | 의미 | 앱 조치 |
|---|---|---|
| 400 | 잘못된 스키마·요청 본문 | 입력 오류 표시 |
| 401 | 인증 없음·만료·잘못된 Bearer | 재인증 안내, 게스트 자동 전환 금지 |
| 403 | 게스트의 영속 기능 요청 등 | 기능 제한 안내 |
| 404 | 없는/타 사용자 대화·기억 | 소유자 정보 노출 없이 안내 |
| 409 | 다른 fingerprint의 동일 `requestId`, 동시 버전 충돌 | 상태 재조회·충돌 안내 |
| 410 | 기존 G2 Redis 세션 만료 | 세션 재사용 금지, 새 검색 진행 |
| 429 | 기존 요청 제한 | 현재 정책 유지 |
| 503 | 인증·영속 DB·Checkpoint 등 사용 불가 | 저장 성공으로 안내 금지 |

`COMMITTED` 결과 확인을 위한 조회 API를 제공한다. 앱 네트워크 타임아웃과 서버 커밋 실패를 같은 오류로 취급하지 않는다.

---

## 5. `ConversationService` 실행·트랜잭션·복원

### 5.1 신규 요청 정상 흐름

1. 라우터의 `chat_principal`이 인증한다. 영속 요청은 `principal.user.id`를 `ownerId`로 사용한다. `rate_limit_key`는 기존 ChatService/RateLimiter에만 전달한다.
2. 해당 계정의 `chat_owner_status=ACTIVE`, 대화방 소유권·존재·삭제 여부를 확인한다. 완료 요청을 찾기 전에 현재 대화 버전 불일치로 재전송을 거부하지 않는다.
3. `(ownerId, requestId)`의 기존 기록을 확인한다. 다른 fingerprint는 409다. 같은 fingerprint의 `COMMITTED` 요청은 현재 버전이 원래 기대 버전과 달라도 접근 권한 확인 후 기존 결과를 반환하고 재실행하지 않는다. `IN_PROGRESS`, `FAILED`, `INTERRUPTED`는 각 상태의 규칙을 따른다.
4. 신규 요청일 때만 `expectedConversationVersion`을 검사하고 `(ownerId, requestId, fingerprint)`를 원자적으로 예약한다. 동시 요청이 같은 ID를 먼저 예약하면 기존 요청 확인으로 돌아간다. 같은 대화방의 동시 실행은 **하나만 허용**한다. 단순 `SELECT` 후 실행이 아니라 DB 기반 실행 예약·임대(lease) 또는 사용자별 대화방 직렬화 장치로 경쟁을 막는다. 긴 LLM 호출 내내 DB 행 잠금을 잡지 않는다.
5. 서버는 대화의 `context_json`과 최근 `chat_messages`를 읽어 **검증·정규화된 기존 `ChatRequest` 문맥**으로 변환한다. 앱은 메시지 텍스트·화면 힌트만 제공하며 과거 상태의 권위가 아니다.
6. `ChatService.answer`의 기존 스타일·상품·성분·지식·일반 상담 분기를 그대로 호출한다. Graph 경로만 G7 Checkpointer를 사용한다. AR 실행은 기존 안전 경계 보존.
7. LLM/Tool 결과와 Catalog 근거 및 일시적 세션 상태를 확인한다. `ChatResponse`의 허용 필드만 `display_payload`로 변환하고 세션 토큰을 제거한다.
8. **한 PostgreSQL 트랜잭션**에서 버전·소유자·삭제 상태와 실행자의 `attempt_count`, `IN_PROGRESS` 상태 및 유효한 lease를 조건부로 다시 검사한 다음 사용자 메시지, AI 메시지, 상담 상태, 버전 증가, 턴 `COMMITTED`, 안전한 `accepted_checkpoint_id/version` 참조를 함께 기록한다.
9. DB COMMIT 성공 이후에만 `persistenceStatus=stored`를 반환한다. 앱은 최신 `conversationVersion`을 저장한다. 중간 실패를 완료로 안내하지 않는다.

### 5.2 중복·동시 요청·fingerprint

- fingerprint는 사용자·대화방·실행 종류·원래 사용자 발화·의미 있는 명시 입력·기대 버전을 포함한 **정규화된 논리 요청**에서 생성한다. 임의 JSON 키 순서나 전송 시각·인증 토큰·Redis capability를 해시에 섞지 않는다.
- 같은 `(ownerId, requestId)`의 다른 fingerprint는 409. 요청 ID는 방이 다르더라도 같은 소유자 범위에서 중복되어서는 안 된다.
- 이미 `COMMITTED`된 요청을 재전송하면 메시지/상태/Tool을 다시 실행하지 않는다. 저장된 메시지·카드 참조로 논리적 결과를 복원한다. 만료된 Redis 토큰을 그대로 재발급하지 않는다.
- 동시 다른 요청은 `409 conversation_busy` 또는 기대 버전 충돌로 거부하고 클라이언트가 최신 상태를 다시 읽는다.
- 요청 중복 방지와 Redis G2의 idempotency/CAS는 별개의 책임이다. 기존 Redis 구현을 G7 DB로 대체하지 않는다.

### 5.3 `IN_PROGRESS` 중단·재시도

- 예약 시 `lease_until`과 단조 증가하는 실행 세대 `attempt_count`를 기록한다. 실행자는 자신에게 발급된 세대를 보유하며 재예약 시 세대를 원자적으로 증가시킨다. lease는 현재 `llm_timeout_seconds` 및 실행 경로의 상한·heartbeat를 고려해 설정하되 근거 없이 고정 10분 같은 수치를 만들지 않는다.
- 완료 트랜잭션은 현재 상태가 `IN_PROGRESS`이고 실행자가 받은 `attempt_count`가 DB의 현재 세대와 같으며 lease가 유효할 때만 성공한다. 중단 전환·재예약·lease 갱신·완료는 상태와 세대를 조건으로 DB에서 원자적으로 처리한다. 조건에 실패한 이전 실행은 메시지·상태·Checkpoint 승인 정보를 커밋하지 못한다.
- 실행 세대는 DB 완료를 보호한다. 이미 발생했을 수 있는 AR·외부 부작용의 중복 방지는 기존 actionId·ACK와 외부 작업 계약을 별도로 따른다.
- lease 동안 동일 요청 재전송 → `IN_PROGRESS` 조회 결과 또는 재시도 안내. 같은 실행을 병렬 재시작하지 않는다.
- lease 만료·프로세스 종료 후 활성 실행이 확인되지 않으면 `INTERRUPTED`로 전이한다. 이미 `COMMITTED`된 것은 절대 덮어쓰지 않는다.
- `INTERRUPTED`에서 **실제 실행 여부가 불명확한 AR·상태 변경·외부 작업은 자동 재실행 금지**. 기존 actionId/ACK 확인 후 별도 안전 절차를 사용한다.
- 부작용 없는 읽기·검색은 실행 완료 여부·DB/Redis 상태가 확인될 때에만 사용자 명시적 재시도로 다시 수행한다. 최신 대화 버전 확인과 새 실행 예약이 필요하다. 동일 requestId에 대해 무조건 새 LLM 호출을 시작하지 않는다.
- `FAILED`는 확인된 실패다. 메시지·상담 상태를 완료로 기록하지 않는다. 앱에서 실패 안내·명시 재시도 동작을 제공한다.
- `COMMITTED`인데 HTTP 응답만 유실됐다면 GET requests로 기존 완료 결과를 가져오고 재실행하지 않는다.

### 5.4 Checkpointer와 DB 원자성의 한계

- LangGraph Checkpointer와 앱 PostgreSQL 완료 트랜잭션을 **하나의 원자적 저장으로 가정하지 않는다**. Redis도 마찬가지다.
- 실행 중간에 여러 Checkpoint가 생겨도 `chat_conversations.accepted_checkpoint_id/version`에 연결되지 않은 것은 미승인이다.
- 마지막 그래프 실행이 **성공했고 결과를 확인했을 때만** 완료 가능하다. Checkpointer 장애로 성공 여부가 불명확하면 `COMMITTED`로 위장하지 않는다.
- Checkpointer의 최종 기록만 실패했으나 실제 읽기 상담 결과가 독립적으로 성공·검증됐다면, 안전성 검사를 통과하는 경로에 한해 `accepted_checkpoint_id=NULL`로 PostgreSQL 대화 결과를 완료 기록하고 이후 **DB 상담 상태 복원**을 사용해도 된다. 사용자에게 Checkpointer 복구가 성공했다고 말하지 않는다. 부작용 있는 명령은 이 예외 대상이 아니다.
- Checkpoint가 DB보다 앞서거나 뒤처진 경우 `thread_id` 최신값을 임의 재사용하지 않는다. **DB에서 승인한 exact `checkpointId`, 목표 `conversationVersion`, `requestId`**가 모두 확인된 경우에만 그 지점을 사용한다.
- 이후 그래프 시작에서도 기본 최신 thread 상태를 자동 로드하지 않게 하고, 승인된 Checkpoint config에서 시작하거나 안전한 서버 대화 문맥을 사용해 새 실행을 구성한다. 체크포인터 API의 정확한 동작은 설치한 버전으로 테스트한다.

### 5.5 서버 문맥 구성

서버가 `ChatContextProvider(ownerId, conversationId)`에서 다음 순서로 구성한다.

1. 소유권·삭제 상태·`conversationVersion` 확인.
2. 현재 목표·선택 상품/옵션·룩·레시피 단계·명시 조건을 `context_json`에서 읽기.
3. 최근 **완료된** 사용자↔AI 메시지쌍만 제한된 범위(우선 기존 최대 8개·8,000자)에서 선택. UI 전용·실패한 임시 메시지 제외.
4. 다른 방의 메시지는 **사용자가 명시적으로 요청한 경우**에만 소유권 검사를 거쳐 조회.
5. 활성 동의 기억만 필요 범위에서 추가. 기억 삭제·철회 `revocationEpoch` 검사.
6. Redis 세션이 유효하더라도 서버가 소유자·capability·TTL을 검증한 경우에만 단기 상품 문맥 사용. 앱 재실행 후 capability가 없으면 후보 순번을 확정하지 않음.
7. 현재 Catalog에서 상품/옵션/룩 ID·근거 버전 유효성 재검증. `UNKNOWN/ERROR`를 임의 확정으로 변경하지 않음.
8. `ChatService`에 전달. G1~G6 기존 의도 분류·Tool 실행 경계 유지.

### 5.6 앱/서버 재실행 이후

- **로그인:** 앱 인증 확인 → 서버 대화 목록 → 사용자 선택 방 조회 → 서버 context 및 메시지 복원 → 필요한 선택·레시피 검증 → 사용자 후속 질문으로 이어짐.
- **게스트:** 앱 메모리에만 방이 있다. 완전 종료 후 서버 조회 불가, 새로운 임시 방 시작.
- **G6:** `StyleContext.kind/lookId/recipeId/recipeVersion/currentStep`, `StyleCondition[]`을 검증 후 복원. 레시피 버전·단계 불일치면 변경된 단계가 유효한지 확인하거나 확인 요청. **단계 버튼 선택도 PATCH로 영속 갱신**.
- **G2 Redis 만료:** 상품·조건의 **과거 맥락**은 보존하되 세션 토큰·pending clarification ID·확정되지 않은 순번·현재 후보 유효성을 재사용하지 않는다. 필요 시 Catalog 새 조회·명시적 재선택.
- **AR:** 과거 제안·메시지를 표시할 수는 있지만 렌더 적용·완료 ACK·명령 자동 재전송 금지.
- **서버 재시작:** `IN_PROGRESS` lease 만료와 Checkpoint 승인 상태를 확인한 뒤 읽기 재개. 사용자에게 미확정 응답을 완료된 답변으로 표시하지 않는다.

---

## 6. 장기 기억과 삭제된 기억 재노출 방지

### 6.1 기억의 대상과 동의

- 허용 종류: `preference`, `profile`, `owned_product` (PR #241 유지).
- 사용자 발화에서 취향을 언급한 것과 **다음에도 저장해 달라고 확인한 것**을 구분한다.
- 모델은 후보를 추출할 수 있으나 **`MemoryService`만 최종 저장**할 수 있다.
- 앱은 저장할 정확한 내용·이후 상담에서 활용할 목적/범위를 보여주고 확인 버튼을 받는다.
- 서버가 발행한 `proposalId`·소유자·내용·버전과 사용자 확인을 검증한다. `confirmed=true`만으로 임의 텍스트를 허용하지 않는다.
- 기억 저장 성공이 DB에서 확인된 후에만 저장 완료를 안내한다. 게스트는 현재 대화 문맥에서만 취향을 활용하고 기억 API는 제공하지 않는다.

### 6.2 기억 수정·삭제

- `memoryId`, `ownerId`, `expectedVersion`으로 수정 CAS. 오래된 편집은 409.
- 삭제는 `revoked_at`과 값 제거, `chat_owner_status.revocation_epoch += 1`을 **같은 트랜잭션**으로 처리한다. 기존 활성 기억 조회에서 즉시 제외.
- ContextProvider는 매 턴 활성 기억을 DB에서 검증한다. 과거 Checkpoint나 요약에 저장된 `memoryRefs`는 `revocationEpoch` 불일치 시 사용하지 않는다.
- 자동 기억 추출로 과거 원문에서 삭제된 취향을 재생성하는 기능은 G7에 넣지 않는다. 기본적으로 다른 대화방 원문 자동 검색도 금지한다.
- 사용자가 삭제한 기억의 출처 메시지가 **현재 방의 최근 문맥**에 있는 경우에도, 해당 내용을 개인화 기억으로 재활용하지 않도록 메시지 출처·기억 키를 검사한다. 원문 UI 표시는 그대로 둘 수 있으나 LLM 문맥에서 민감 구간 가리기 또는 해당 문맥 제외를 적용한다. 이 경계는 실제 삭제 후 후속 질문으로 검증한다.
- 기억 삭제와 과거 **메시지 원문 삭제는 별개**다. 과거 방 원문을 사용자가 명시적으로 열람하는 것과 해당 취향을 장기 개인화로 사용하는 것을 구분한다.
- 대화방 삭제 시에는 해당 방·메시지·파생 문맥·Checkpoint를 차단·정리한다. 별도로 명시적으로 저장된 장기 기억까지 자동 삭제하지 않는다. 원문 출처가 삭제되면 `source_message_id` 연결을 안전하게 해제한다.

### 6.3 요약·색인

G7에서 **복잡한 자동 요약·VectorDB·의미 검색을 새로 만들지 않는다**. 필요한 문맥은 서버가 허용된 최근 메시지와 구조화 상태에서 직접 구성한다. 향후 요약 도입 시 출처 메시지 범위·원문 버전·기억 참조를 유지하여 삭제 시 무효화해야 한다.

---

## 7. 인증·로그인 전환·소유권

### 7.1 서버 인증 상태

| 서버 요청 | 처리 |
|---|---|
| Authorization 없음 + 유효한 익명 ID | **기존 게스트 G1~G6** 허용; 영속 엔드포인트 401 |
| 유효한 Bearer JWT | `AuthUser.id` 확인, 영속 API 허용 |
| 잘못된/만료된/형식 오류 Authorization | 401, 익명 ID가 있어도 게스트로 폴백 금지 |
| Authorization 있음 + 검증 설정/서비스 불가 | 503, 게스트 폴백 금지 |
| `AUTH_CHECKING` 앱 상태 | 사용자 식별 확정 전 영속 요청·게스트 자동 요청을 시작하지 않음 |

- `rate_limit_key`는 현재 요청 제한 키다. 영속 테이블의 owner에 `user:...` 문자열을 저장하지 않는다.
- 모든 대화·기억 API는 SQL 조건에 `(id, owner_id, deleted_at IS NULL)` 또는 동일한 소유권 제약을 적용한다. 단순히 id만으로 먼저 전체 레코드를 돌려주지 않는다.
- 타인 대화/기억 ID는 404 등으로 처리해 존재 여부 노출 최소화. 내부 Checkpointer에 대해서도 대화방 소유권을 검사하기 전에는 접근하지 않는다.
- 로그아웃·사용자 A→B 전환 시 `store/chatConversationStore.ts`의 `activate`, generation/ticket 체크를 재사용한다. 진행 중 요청의 늦은 응답·계정별 캐시·서버 hydration 요청을 모두 새 계정 UI에 적용하지 않는다.
- 토큰 새로고침으로 **같은 사용자**인 경우 방 상태를 불필요하게 초기화하지 않는다.

### 7.2 앱 첫 영속 대화 생성

로그인 후 `app/chat.tsx`의 채팅 화면으로 진입하면 다음 순서를 지킨다.

1. `useAuth().ready=true`이며 유효한 로그인 사용자인지 판정.
2. 기존 서버 대화방을 여는 경우 GET; 새 상담이면 POST conversations로 **첫 메시지 전 방 생성**.
3. 서버 `conversationId`/버전을 Zustand의 해당 방에 연결하고 실제 `/api/chat`에 포함.
4. 첫 방 생성 실패 시 영속 대화로 보이는 임시 기록을 계속 전송하지 않는다. 저장 실패 안내 및 재시도.
5. 게스트는 기존 로컬 `open`/`resume`을 그대로 사용. 계정 로그인 시 게스트 기록 이전 금지.
6. 재실행 시 서버 방 목록을 읽고 명시 선택한 방을 복원. 다른 방을 몰래 맥락에 결합하지 않는다.

---

## 8. 회원 탈퇴 및 서비스 간 삭제 계약

### 8.1 책임

- **API 서비스:** `DELETE /api/me` 접수, 삭제 작업의 영속 상태·재시도·Supabase Admin secret 관리, 최종 완료 여부 판단.
- **Chatbot:** 계정의 영속 읽기/쓰기 차단, `chat_conversations`, `chat_messages`, `chat_turns`, `chat_memories`, Checkpoint 삭제, 재시도 안전한 완료 응답.
- **클라이언트:** 탈퇴 진행 중 데이터 접근·쓰기 중단 및 UI 캐시 제거.
- Supabase secret (`SUPABASE_SECRET_KEY`)은 `backend/api`에만 둔다. 내부 삭제 호출의 인증 방식은 팀 API/인프라 공동 계약으로 최종 확정한다.

### 8.2 안전한 순서

1. API가 삭제 작업을 영속 기록(예: `PENDING`/`BLOCKING`/`PURGING_CHAT`/`DELETING_AUTH`/`DONE`/`RETRY_REQUIRED`). 중복 탈퇴 요청은 같은 작업을 조회한다.
2. 내부 인증된 호출로 Chatbot이 `chat_owner_status`를 `DELETING`으로 전환해 영속 **읽기·새 쓰기**를 차단한다. 이전 처리 중인 턴도 마지막 완료 커밋 시 상태를 재확인하므로 삭제 후 커밋 금지.
3. Chatbot이 메시지·대화 상태·기억·Checkpoint를 정리하고 완료를 보고한다. 부분 실패는 재시도할 수 있도록 상태 유지. 물리 삭제가 완료되기 전에는 완료라고 답하지 않는다.
4. API가 Supabase 계정 및 회원 기록을 정리한다. 이미 삭제된 계정/재시도 시 idempotent 처리. 모든 단계가 확인된 후만 최종 완료 응답.
5. 오래된 JWT가 만료되기 전 새 영속 대화가 생성되지 않도록 Chatbot의 삭제 차단 표식과 요청 진입 검사를 유지한다. 소유자 상태의 생성·조회·upsert가 기존 `DELETING`/`DELETED`를 `ACTIVE`로 덮어쓰지 못하게 한다. 유효한 삭제 재시도와 충돌하지 않게 설계한다. 표식 식별 방식·보존 기간과 백업 정리는 API·인프라 담당자와 확정한다.

### 8.3 공동 미확정 의존성

- API 담당자: `MemberService.delete_account()` 변경, 삭제 작업 테이블·재시도, 기존 `DELETE /api/me` 204/진행 중 응답 정책, 내부 서비스 호출 계약.
- 인프라 담당자: Chatbot DB 계정·Secret·권한·백업/보존 정책, 내부 삭제 호출 인증(mTLS/서비스 서명 등).
- API 공동 계약 미완료면 **Chatbot 차단·삭제 로직은 로컬 fake 호출자로 테스트**할 수 있지만, 운영 G7 영속 기능은 활성화하지 않는다.
- 기존 ADR-0010의 “Supabase 계정 선삭제” 순서는 새 챗봇 DB 삭제와 충돌할 수 있으므로 API 담당 공동 수정 대상으로 기록한다. G7 담당자가 API 코드를 무단 변경하지 않는다.

### 8.4 공동 연동 권장안 — 팀 검토 전 초안

아래는 사용자와 정리한 **검토용 권장안**이다. API·인프라·개인정보 담당자의 공동 합의, 운영 구현 또는 검증이 끝났다는 뜻이 아니다. 8.3의 미확정 의존성과 운영 활성화 금지는 그대로 유지한다.

사용자는 모든 필수 삭제 후 완료 표시, 미완료 시 진행 안내, 서버 자동 재시도, Redis 단기 세션의 즉시 삭제를 목표로 하는 방향을 선택했다. Redis 즉시 삭제를 필수 완료 조건으로 적용할 수 있는지와 그 구현·운영 방법은 팀 검토가 필요하다.

1. **작업 기록·재시도:** API가 인증된 사용자별 삭제 작업을 영속 기록하고, 중복 요청을 같은 작업에 연결한다. API 측 워커가 서버 재시작이나 사용자 이탈 이후에도 미완료 단계를 재시도한다. 동시 워커의 중복 처리 방지, 단계별 멱등성, 실패 단계·시각·재시도 기록, 재시도 간격과 장기 실패 알림·수동 복구 책임을 공동 계약에 포함한다. Supabase 계정 삭제 이후 회원 정리나 최종 응답이 실패해도 사용자 재로그인 없이 복구 가능해야 한다.
2. **차단·삭제 순서:** API는 작업을 기록한 뒤 해당 계정의 접근·쓰기를 차단하고, 인증된 내부 호출로 Chatbot의 차단과 데이터 삭제 완료를 확인한다. 그 후 Supabase 계정과 회원 기록을 삭제하고 전체 완료를 기록한다. Chatbot 삭제가 미완료면 Supabase 삭제로 넘어가지 않는다. 진행 중 요청의 늦은 응답·저장과 API 측 접근 차단 범위도 실제 연동에서 확인한다.
3. **서비스 간 인증:** 내부 삭제 요청은 API 서비스의 신원을 검증하며 사용자 JWT를 서비스 인증으로 사용하지 않는다. API가 검증한 소유자 ID와 삭제 작업 ID를 최소 범위로 전달하고, 인증·권한 실패 시 삭제하지 않는다. 내부 네트워크 제한과 전용 인증 정보를 사용하며, 타임아웃·응답 유실 후 동일 작업 재호출을 허용한다. mTLS 또는 서비스 간 서명 등 실제 인증 방식과 비밀 관리·교체는 API·인프라 담당자가 확정한다.
4. **클라이언트 응답:** 우선 기존 `DELETE /api/me`의 `204`는 모든 필수 삭제가 완료된 경우에만 반환한다. 접수됐지만 완료되지 않은 작업과 접수 자체가 실패한 경우는 완료로 표시하지 않도록 구분한다. 현 앱은 2xx를 성공으로 처리하므로, `202`를 도입하려면 앱의 진행 상태·캐시 처리와 인증 만료 후 결과 확인 방법까지 함께 변경해야 한다. 최종 응답 유실 시 사용자에게 결과를 확인시키는 안전한 방법과 구체적인 오류·상태 조회 계약은 미확정이다.
5. **차단 표식과 보존:** 정본 대화·기억·Checkpoint는 필수 삭제 확인 후 완료 처리한다. 오래된 JWT 차단 표식은 최소 식별자를 사용하고 HMAC 기반 방식의 적용 가능성, 키 보관·교체, 보존 기간을 개인정보·인프라 담당자와 확정한다. 표식은 유효한 기존 JWT를 차단해야 하는 기간보다 먼저 제거하지 않는다. 현재 로컬 구현은 원본 소유자 ID를 표식으로 보유하므로 운영 개인정보 정책 확정으로 간주하지 않는다.
6. **Redis·백업:** 기존 Redis 단기 세션은 최대 600초 TTL을 사용하지만 TTL 만료와 즉시 물리 삭제는 다르다. 로컬·테스트 단일 Redis에서는 계정을 먼저 차단한 후 기존 세션의 소유자를 확인해 삭제하고, 해당 계정의 요청 기록·요청 제한 키도 정리한다. Redis 장애나 소유자를 판별할 수 없는 비정상 세션이 있으면 정리 완료로 응답하지 않고 재시도한다. 과거에 이미 `DELETED`로 표시된 계정도 재호출 시 정리한다. 기존 `DELETED` 표식 자체는 Redis 정리 완료 증거가 아니다. `SCAN` 전체 순회는 키 수에 따른 부하가 있으며, 혼합 버전 서버·복제본·클러스터 및 백업 복구 환경에서의 정리 보장은 팀 검토 전 미확정이다. 백업 보존·삭제 요청 처리 및 복구 시 삭제 데이터 재노출 방지 절차도 확정한다. 확정 전에는 운영 삭제 완료 범위로 가정하지 않는다.
7. **플래그·장애:** 영속 상담 기능과 탈퇴 차단을 별도로 관리한다. 영속 기능을 사용한 환경에서는 기능을 끄기 전에 차단 설정을 적용하고, 차단 표식이 필요한 동안 유지한다. 차단 DB 확인 실패 시 로그인 상담과 AR 확인은 거부하며 게스트는 기존 경로를 유지한다. 로컬·테스트에서는 영속 기능이 꺼져도 차단 설정이 켜져 있고 Chatbot 소유자 상태가 이미 `DELETING`이면 삭제를 재시도할 수 있으며 `DELETED` 재호출은 멱등 처리한다. `ACTIVE` 또는 미등록 계정은 OFF 상태에서 새로 차단·삭제하지 않는다. API에는 접수됐으나 Chatbot 차단 전인 작업의 복구와 운영 적용은 공동 계약에서 정한다. 차단 설정을 함께 끄거나 차단 코드가 없는 이전 버전으로 롤백하면 보호가 유지되지 않는다.

### 8.5 공동 연동 검증·운영 게이트

- 정상 탈퇴에서 Chatbot 데이터·Checkpoint 삭제 확인 후 Supabase 계정·회원 기록을 정리하고 최종 완료를 반환한다.
- `DELETING` 및 `DELETED` 계정의 오래된 JWT로 기존 상담·영속 조회·쓰기·기억·AR 확인에 접근하지 못하며, 진행 중 요청이 늦게 응답하거나 저장하지 않는다.
- Chatbot DB·Checkpoint·Supabase 장애, 응답 유실, 서버 재시작, 중복 요청 및 동시 워커에서 허위 완료·중복 실변경 없이 복구한다. Supabase 삭제 후에도 사용자 재로그인 없이 남은 작업을 끝낼 수 있어야 한다.
- 영속 상담을 끈 뒤 차단 유지와 삭제 작업 재시도를 확인하고, 차단 DB 장애 시 로그인 요청 거부·게스트 기존 동작을 확인한다. 타 계정과 기존 G1~G6 기능의 회귀도 확인한다.
- 백업 복구 시 삭제 데이터가 재노출되지 않는 절차, 차단 표식 보존·키 관리, 롤백 및 장기 실패 대응을 팀이 검토한다. 운영 설정·인증·보존 정책과 통합 검증이 완료되기 전에는 G7 영속 기능을 운영 활성화하지 않는다.

---

## 9. 파일·함수별 변경 지도

### 9.1 변경할 기존 파일

| 파일 | 정확한 변경 경계 |
|---|---|
| `backend/chatbot/app/core/auth.py` | `chat_principal()`의 Authorization 존재/검증 실패 경계, `AuthUser.id` 전달 |
| `backend/chatbot/app/routers/chat.py` | `chat()`에서 영속 요청을 `ConversationService`에 전달, 구형/게스트는 기존 `ChatService`, `/chat/acks` 유지 |
| `backend/chatbot/app/schemas/chat.py` | `ChatRequest`의 선택적 `conversationId`, `expectedConversationVersion`, `requestId` 유지; `ChatResponse`에 선택적 `conversation` 추가; 기존 validators 호환 |
| `backend/chatbot/app/services/chat_service.py` | `answer`, `_run_supervisor`, `_answer_session`의 서버 복원 문맥 전달·G2 session ID와 영속 graph thread 구분; 조기 반환 경로 전체 보존 |
| `backend/chatbot/app/services/product_consultation_graph.py` | 실제 graph 경로만 Checkpointer, 런타임 응답·영속 state 분리 |
| `backend/chatbot/app/schemas/vishue_state.py` | 영속 직렬화 허용 필드/버전으로 축소·확장; `ChatResponse` 직접 저장 제거 |
| `backend/chatbot/app/core/config.py` | `CHAT_DATABASE_URL`, `G7_PERSISTENCE_ENABLED`, `G7_MEMORY_ENABLED`, 운영 활성화 게이트 등 설정 |
| `backend/chatbot/app/main.py` | G7 router 등록, CORS GET/POST/PATCH/DELETE, pool lifecycle |
| `backend/chatbot/pyproject.toml`·`uv.lock` | Python PostgreSQL 드라이버, DB 마이그레이션, Checkpointer 공식 의존성; `uv`로 갱신 |
| `store/chatConversationStore.ts` | server conversation ID·version, 로그인 서버 hydration, G6 단계 PATCH, 계정 전환 캐시 격리 |
| `types/chatConversation.ts`·`types/index.ts` | G7 대화·기억·상태 API 공통 타입 |
| `hooks/useChat.ts` | 로그인용 conversationId/version/requestId 요청 연결, 구형 레거시 호환 |
| `lib/api.ts` | 인증된 채팅 GET/PATCH/DELETE 및 바뀌지 않은 owner에 응답 귀속, 토큰 오류 폴백 금지 |
| `app/chat.tsx` | 첫 서버 방 생성, 목록·조회·재개, 기억 확인 UI, logout/invalid auth 처리 |
| `components/chat/RecentConversations.tsx` | 로그인 서버 목록과 게스트 메모리 목록 표시 분기 |
| `infra/compose/compose.yaml` | 로컬 챗봇 DB·마이그레이션·환경변수 추가 (팀 공용 Helm은 별도 승인) |

### 9.2 새 파일 후보 (필요한 단위만 생성)

- `backend/chatbot/app/schemas/conversation.py`, `schemas/memory.py`
- `backend/chatbot/app/repositories/conversation_repository.py`, `repositories/memory_repository.py`
- `backend/chatbot/app/services/conversation_service.py`, `services/conversation_context.py`, `services/memory_service.py`
- `backend/chatbot/app/routers/conversations.py`, `routers/memories.py`
- `backend/chatbot/app/core/persistence.py` 또는 레이어 규칙을 만족하는 동일 책임의 DB 연결 모듈
- `backend/chatbot/alembic/` 챗봇 전용 마이그레이션
- `backend/chatbot/tests/test_g7_auth_*.py`, `test_g7_conversation_*.py`, `test_g7_memory_*.py`, `test_g7_recovery_*.py`

**레이어 규칙:** 라우터가 Repository에 직접 접근하지 않게 한다. 서비스가 트랜잭션을 조정하고 Repository가 저장을 수행한다. 기존 API/AR 소유 파일은 담당자 리뷰 없이 수정하지 않는다.

---

## 10. 단계별 구현·검증·인계

### G7-1 — 인증·API 계약

**수정:** `auth.py`, `schemas/chat.py`, 신규 스키마·라우터의 계약 스켈레톤, 테스트. **DB가 없는 단계에서는 영속 저장 성공을 반환하지 않는다.** 필요하면 feature flag OFF·503 경로로 닫는다.

**완료 기준:** (1) 게스트/정상 로그인 정상, (2) 위조·만료 Bearer가 익명 ID 있어도 401, (3) 인증 미설정 503, (4) 게스트 영속 요청 거부, (5) `conversationId` 없는 기존 chat/AR/ACK 호환, (6) `conversationId`·버전·requestId 입력 검증, (7) `AuthUser.id`와 rate-limit key 분리. G7-2로 스키마 계약 인계.

### G7-2 — PostgreSQL·Repository

**수정:** 챗봇 전용 DB 연결, Alembic, 5개 테이블, 실제 CRUD/소유권·인덱스, Checkpointer 초기화 경로. 로컬 Compose 구성.

**완료 기준:** 실제 PostgreSQL 마이그레이션 up/down 검증, 다른 사용자의 ID로 조회·변경 불가, 원자적 커밋과 동시 요청 CAS, Checkpointer safe serialization 테스트. 팀 DB 권한은 독립 의존성.

### G7-3 — ConversationService·서버 문맥·중단 요청

**수정:** 대화방 CRUD, 영속 컨텍스트 읽기·검증, 최근 메시지 추출, `chat_turns` 예약/lease/중단/멱등, 완료 단일 DB 커밋.

**완료 기준:** (1) 앱 없이 API 두 턴 후 후속 질문 문맥 연결, (2) 중복·요청 충돌·버전 충돌, (3) 응답 유실 후 완료 조회, (4) 서버 강제 중단 후 INTERRUPTED, (5) 오저장·미완료 메시지 없음.

### G7-4 — 기존 G1~G6·Checkpointer

**수정:** ChatService 어댑터, 실제 LangGraph 경로 Checkpointer, G2 Redis 만료 처리, G6 StyleContext/레시피 단계 저장·복원.

**완료 기준:** 실제 Catalog 연동으로 로그인 대화 재개, G3/G4 후속 질문과 G6 룩 단계 이어짐, Redis 600초 후 새 검색, 미승인 Checkpoint 자동 복원 0, 전체 ChatResponse/token 직렬화 0, AR 자동 실행 0.

### G7-5 — 기억 저장·철회

**수정:** MemoryService, 동의 확인, 기억 API·메모리 refs·철회 epoch, 앱 확인 UI.

**완료 기준:** 동의 전 저장 0, 동의 후 새 방 사용, 수정 CAS·삭제 멱등, 삭제 기억의 현재 문맥·요약·Checkpoint 재노출 0.

### G7-6 — 앱 실제 E2E

**수정:** 첫 방 생성, 서버 목록·조회·재개, Zustand 연결, 단계 PATCH, 로그인/게스트/계정 전환 분기.

**완료 기준:** **로그인 → 첫 상담 → 앱 완전 종료/재실행 → 같은 방 선택 → 상품·룩 후속 질문** 실제 실행, 서버 재시작 복원, 계정 A→B·로그아웃 늦은 응답 격리, 게스트 재실행 복원 0.

### G7-7 — 삭제 공동 연동·통합 게이트

**독립:** Chatbot 계정 차단·삭제 서비스 및 fake API 호출 통합. **공동:** API `DELETE /api/me` 삭제 작업·인프라 보안·운영 게이트.

**완료 기준:** 타인 접근 차단, 탈퇴 후 오래된 JWT 새 기록 0, 대화/기억/Checkpoint 삭제 확인, 중간 장애 시 재시도·완료 여부 검증, 필수 CI와 회귀. 외부 승인 미완료 시 `BLOCKED_DEPENDENCY`로 표시하고 운영 플래그 OFF.

---

## 11. 필수 검증 매트릭스·차단 결함

### 11.1 PR #241 G7 기존 대표 시나리오

| ID | 실행 | 기대 결과 |
|---|---|---|
| G7-N01 | 로그인 사용자 이전 방 선택·재접속 | 본인 방·상태 복원, 최신 근거 재확인 |
| G7-N02 | “코랄 립 다음에도 기억해줘” | 동의 전 저장 0, 확인 후 저장, 새 방에서 활용 |
| G7-E01 | 기억 삭제 후 이전 Checkpoint/메시지 존재 | 삭제 기억 자동 재노출·재저장 0, 삭제 멱등 |
| G7-E02 | 다른 사용자 방 조회 + 동시 변경 | 타인 정보 노출 0, 성공 커밋 하나만 |

### 11.2 추가 필수 사례

| ID | 사례 | 통과 조건 |
|---|---|---|
| G7-AUTH-01 | 게스트 3턴 후 앱 재실행 | 대화 복원 0, G1~G6 상담 정상 |
| G7-AUTH-02 | 게스트 상담 후 로그인 | 게스트 대화 이전 0, 계정 방만 표시 |
| G7-AUTH-03 | 로그인 A→로그아웃→B | A 메시지·기억·늦은 응답 B 노출 0 |
| G7-AUTH-04 | 잘못된 Bearer+유효 익명 ID | 401, guest fallback 0 |
| G7-AUTH-05 | guest의 기억/영속 API 호출 | 저장 0, 권한 오류 |
| G7-FIRST-01 | 로그인 최초 대화 | 첫 질문 전에 영속 방 생성, 실패 시 조용한 레거시 폴백 0 |
| G7-CTX-01 | 앱 재실행 후 “아까 두 번째 립은?” | 서버 이력·선택 기반 연결, 만료 순번은 무조건 단정하지 않음 |
| G7-CTX-02 | G6 룩 2단계 선택 후 종료·재실행 | 같은 유효한 룩·단계, 레시피 변경 검증 |
| G7-DB-01 | 완료 저장 중 DB 오류 | 메시지/상태/버전 부분 커밋 0 |
| G7-DB-02 | 동일 requestId 재전송 | LLM/Tool 재실행 0, 결과 1건 |
| G7-DB-03 | 다른 payload 동일 ID / 동시 버전 충돌 | 409, 중복 커밋 0 |
| G7-DB-04 | COMMITTED 후 HTTP 응답 유실·원래 기대 버전으로 재전송 | 권한 확인 후 기존 결과 반환, 버전 충돌·재실행 0; requests 조회도 가능 |
| G7-DB-05 | 방 생성 성공 후 응답 유실·동일 요청 재전송 | 같은 방 결과 반환, 중복 방 생성 0 |
| G7-DB-06 | 방 없는 기억 생성·수정·삭제 요청 재전송 | 한 번만 변경·철회, 같은 결과 확인; 다른 fingerprint는 409 |
| G7-DB-07 | 생성된 방 삭제 후 이전 생성 요청 재전송 | 삭제된 방의 재생성·내용 노출 0, 삭제된 결과 안내 |
| G7-REC-01 | IN_PROGRESS 중 프로세스 종료 | lease 만료 → INTERRUPTED, 모호한 AR 자동 재실행 0 |
| G7-REC-02 | Redis 만료 후 복원 | 영속 대화 유지, 만료 토큰·미검증 후보 미사용 |
| G7-REC-03 | 실행 A lease 만료 후 B 재예약, A가 늦게 완료 | A 커밋 0, 현재 세대 B만 조건 충족 시 완료; 실제 DB 경쟁 검증 |
| G7-CP-01 | 그래프 중간 Checkpoint 존재·DB 미완료 | 미승인 Checkpoint 자동 복원 0 |
| G7-CP-02 | `VishueState` 직렬화 | 인증/세션 토큰·전체 ChatResponse 저장 0 |
| G7-CP-03 | Checkpointer 실패 | 확인된 실행만 완료, DB 정본 복원 유지 |
| G7-MEM-01 | 기억 저장 요청을 단순 언급과 구분 | 동의 전 저장 0 |
| G7-MEM-02 | 기억 수정/삭제·기존 문맥 사용 | 무효화 후 자동 개인화 재등장 0 |
| G7-DEL-01 | 탈퇴 진행·오래된 JWT·재시도 | 영속 접근/새 쓰기 0, 삭제 상태 확인, ACTIVE 재생성 0 |
| G7-DEL-02 | 방 삭제 중 Checkpoint 정리 실패 후 재시도 | 접근 차단 유지, 완료 허위 표시 0, thread 참조 보존 후 실제 정리 |
| G7-DEL-03 | 방 삭제 중 진행 턴의 늦은 완료 | 삭제 후 메시지·상태 커밋 0 |
| G7-REG-01 | 기존 AR 제안·ACK·G1~G6 | 기존 핵심 경로 회귀 없음 |

**병합 차단:** 타인 정보 노출, 인증 실패 폴백, 무단 기억 저장/삭제된 기억 복구, 중복 실변경, DB 부분 완료, 미확정 Checkpoint/AR 자동 실행, 앱의 저장 성공 허위 표시, 완료 기준의 미실행 테스트 PASS 표기. 비차단 문구·UI 미세 조정·요약/성능 최적화는 후속 Issue로 인계한다.

### 11.3 검증 환경·명령

- 백엔드 변경: `uv run ruff check .`, `uv run lint-imports`, `uv run pytest` (변경 서비스 각각). `pyproject.toml`/lock 수정 동기화.
- 앱 변경: 프로젝트 `package.json`의 표준 검사 스크립트 및 `npx tsc --noEmit`, lint, 관련 Jest/앱 테스트. 기존 `AGENTS.md` 준수.
- 로컬 실제 PostgreSQL·Redis·Catalog API·Chatbot 통합 테스트와 최소 한 건의 앱→API→DB 복원 시나리오.
- API 담당자/Helm 공동 변경은 별도 리뷰·환경별 검증. **모의 검증과 실제 DB/앱 검증을 혼동하지 않는다.**

---

## 12. 미확정 의존성·범위 제외·보고 형식

### 12.1 팀 확인이 필요한 사항(구현과 병행)

| 항목 | 상태 | 독립 진행 가능 범위 |
|---|---|---|
| 공용 PostgreSQL `vishue_chat_db` 및 전용 계정 생성 권한 | `BLOCKED_DEPENDENCY` | 로컬 Compose DB·마이그레이션·Repository |
| 운영 RDS·Secrets·Helm·마이그레이션 실행 주체 | `BLOCKED_DEPENDENCY` | 로컬/테스트 환경 완성 |
| `DELETE /api/me` 삭제 작업 상태·내부 통신 인증·응답 계약 | `BLOCKED_DEPENDENCY` | Chatbot 삭제 엔드포인트/서비스 및 fake 호출 테스트 |
| 데이터 보존·백업 삭제·운영 개인정보 정책 | 운영 출시 전 팀 결정 | 개발 테스트·기능 플래그 기본 OFF |
| 영속 기능 OFF 이후 삭제 재시도·차단 설정·롤백 절차 | API·인프라 공동 검토 필요 | 로컬 차단 설정 분리; Chatbot이 이미 `DELETING`인 계정의 OFF 상태 재시도 검증. 차단 전 API 작업 복구는 미확정 |
| 탈퇴 최종 응답 유실 시 사용자 결과 확인 방법 | API·클라이언트 공동 검토 필요 | 완료 전 `204` 금지 권장; `202` 도입 시 앱 처리 변경 필요 |
| G1~G6 공용 코드 및 AR/API 리뷰 담당 | 팀 공동 리뷰 | Chatbot 독립 어댑터·기존 기능 회귀 검증 |

### 12.2 이번 G7에서 하지 않는 것

- 새 복합 다중 Agent 구조·G8 Task DAG 전면 구현
- 모든 G1~G6의 LangGraph 재작성
- 게스트 영속 대화·로그인 시 게스트 이전
- 자동 과거 방 의미 검색·VectorDB 기억 검색·전면 요약 최적화
- 사용자 동의 없이 취향 자동 수집·프로필 추정
- Checkpoint에 모든 응답/Tool 원문 저장, Catalog 직접 변경, 자동 AR 재실행
- 모든 S01~S12의 대규모 통합 평가를 G7 병합 조건으로 추가

### 12.3 Codex 단계별 완료 보고 형식

```markdown
## 단계
G7-X · 작업 브랜치 / develop 기준 SHA / 구현 HEAD

## 실제 변경
- 파일 / 함수 / 목적

## 검증
- 실행 명령, 환경, PASS/FAIL/NOT_RUN
- 실제 DB·Redis·앱·LLM 검증 구분

## 미완료
- BLOCKED_DEPENDENCY: 외부 승인 항목
- BLOCKER: 데이터·보안·무결성·실행 결함
- FOLLOW_UP: 비차단 품질·성능·UI 개선

## 다음 단계 인계
- 재사용 API/State/버전 계약
- 재시도/실패 복구 검증 결과
- PR 링크 및 병합 여부(Draft 유지)
```

**종료 판단:** G7은 **실제 로그인 대화방 재개와 동의 기반 기억이 작동하고, 서버 문맥 복원·원자적 완료·소유권·삭제 안전성의 필수 검증을 통과**한 경우에만 완료다. 외부 API 삭제 공동 계약 미완료는 운영 활성화의 명확한 차단 의존성으로 기록한다. G8 개발은 이와 무관한 품질 최적화 때문에 지연시키지 않는다.

---

## 부록 A. Codex 최초 실행 지시문

아래 문장을 Codex에 전달한다. **이 저장소 문서의 현재 버전과 작업 브랜치 상태를 확인한 뒤 Codex에 전달한다.**

> `docs/ai-design/G7-IMPLEMENTATION-SPEC.md`를 G7 v1.1 구현 기준으로 사용하라. 먼저 AGENTS.md, CONTRIBUTING.md, PR #241, 최신 develop 및 기존 G7 브랜치 HEAD를 확인하고 차이를 기록하라. 이전 작업 커밋을 무단 덮어쓰거나 force-push하지 마라. 이 문서의 G7-1 인증·API 계약부터 구현하고 실제 관련 테스트를 수행한 뒤 변경 파일·실행 증빙·미완료 항목을 보고하라. G7-2 이후 DB/Checkpointer/장기 기억의 완료를 G7-1에서 주장하지 말고, 기존 G1~G6 게스트 상담·AR·ACK 호환성을 유지하라. 개발 PR은 Draft로만 제출하고 자동 병합하지 마라. 팀 인프라·API 담당자 의존성은 BLOCKED_DEPENDENCY로 분리한다.

## 부록 B. 근거 문서 및 실제 코드

- [PR #241 — AI 0~4단계 설계·평가 계약](https://github.com/gyuniverse-hq/SKN34-Final-Project/pull/241)
- [G7 실행·기억·DB 책임 — 03-execution-contracts](https://github.com/gyuniverse-hq/SKN34-Final-Project/blob/d9c6a77c1467d11465a72c66b8f2579b8ab68609/docs/ai-design/03-execution-contracts.md)
- [G2/G6/G7 공통 문맥 — 09-common-conversation-context-contract](https://github.com/gyuniverse-hq/SKN34-Final-Project/blob/d9c6a77c1467d11465a72c66b8f2579b8ab68609/docs/ai-design/09-common-conversation-context-contract.md)
- [ADR-0012 — pgvector로 전환](https://github.com/gyuniverse-hq/SKN34-Final-Project/blob/d9c6a77c1467d11465a72c66b8f2579b8ab68609/docs/adr/0012-pgvector-instead-of-neo4j.md)
- [ADR-0010 — 계정 삭제와 Supabase secret 소유권](https://github.com/gyuniverse-hq/SKN34-Final-Project/blob/d9c6a77c1467d11465a72c66b8f2579b8ab68609/docs/adr/0010-account-deletion-secret-key.md)
- [ChatService](https://github.com/gyuniverse-hq/SKN34-Final-Project/blob/d9c6a77c1467d11465a72c66b8f2579b8ab68609/backend/chatbot/app/services/chat_service.py)
- [VishueState](https://github.com/gyuniverse-hq/SKN34-Final-Project/blob/d9c6a77c1467d11465a72c66b8f2579b8ab68609/backend/chatbot/app/schemas/vishue_state.py)
- [Chatbot 인증](https://github.com/gyuniverse-hq/SKN34-Final-Project/blob/d9c6a77c1467d11465a72c66b8f2579b8ab68609/backend/chatbot/app/core/auth.py)
- [Chatbot 라우터](https://github.com/gyuniverse-hq/SKN34-Final-Project/blob/d9c6a77c1467d11465a72c66b8f2579b8ab68609/backend/chatbot/app/routers/chat.py)
- [앱 대화 Zustand](https://github.com/gyuniverse-hq/SKN34-Final-Project/blob/d9c6a77c1467d11465a72c66b8f2579b8ab68609/store/chatConversationStore.ts)
