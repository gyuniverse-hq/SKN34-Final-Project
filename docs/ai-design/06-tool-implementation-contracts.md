# VISHUE AI — Tool 상세 입력·출력·권한·검증 계약 (2-5 개발 계약 초안)

> 상태: **PROPOSED — 계약안 v0.1, 2026-11-15**. 2-5 상세 검토 중이며 팀 승인·구현·실행 검증이 아님.  
> 개발 비교 기준: `develop d1cf4868f74d2ff6db188bf2c7646146f3ec72ad`.  
> 상위 개념: [05 Tool·근거·데이터 접근](05-tool-evidence-data-contract.md). 기존 [API 원본 계약](../INGREDIENT_CONSULTATION.md), [아키텍처/ADR](../ARCHITECTURE.md), [오류·실행 상태](03-execution-contracts.md)를 대체하지 않음.

## 0. 작업 원칙과 상태 범례

**EXISTING-CODE**: `develop`의 파일/라우터/스키마로 확인. **ADAPTER-PROPOSED**: 기존 API의 결과를 검증하여 새 Tool 타입으로 변환해야 함. **NEW-API-PROPOSED**: 현재 `develop`에 지원 계약 없음. **BLOCKED**: 라이선스·검수·발행·기기 상태로 아직 서비스 사용 불가. **VERIFIED-E2E**: 명시한 실환경에서 실행·관측된 경우에만 사용. 이 문서는 코드 정적 분석을 수행했으며 새 실행 테스트는 하지 않음.

공통 원칙: **Tool 이름과 실제 HTTP API 경로는 다르다**. Agent의 출력·클라이언트 입력값은 사용자 의도에 대한 힌트이며 서버 인증·권한·카탈로그 사실과 동일시하지 않는다. 기존 상품/성분 API 응답 필드를 지우거나 임의 추가하지 않고 어댑터가 새 내부 형태로 변환한다. LangGraph의 Tool 호출이 외부 부작용을 자동으로 멱등하게 만드는 것은 아니다.

## 1. 기존 HTTP API와 목표 Tool 매핑

| 목표 Tool | 기존 호출·스키마 (`develop`) | 상태 | 직접 연결의 제약 / 작업 |
| --- | --- | --- | --- |
| `search_products` | `GET /api/products?q=&category=&ids=&concerns=` → `ProductsResponse{products}`; [router](../../backend/api/app/routers/catalog.py), [Product](../../backend/api/app/schemas/catalog.py) | EXISTING-CODE + ADAPTER-PROPOSED | 80자 검색어 제한·`category` 값 검증. **복합 옵션별 현재 가격/재고/성분 필터 API 없음**. `priceKRW`는 원본 Product 필드이지 현재가 확정이 아님 |
| `get_product_detail` | `GET /api/products/{product_id}` → `ProductResponse{product}` | EXISTING-CODE | 404 `not_found`, 반환된 Product.id와 요청 ID 일치 확인. `shades[].id`가 해당 제품에 속하는지 재검증 |
| `find_similar_shades` | `GET /api/shades/similar?productId=&shadeId=&limit=` → `SimilarShadesResponse{source,matches,products}`; [shade router](../../backend/api/app/routers/shades.py) | EXISTING-CODE + ADAPTER-PROPOSED | 공식 셰이드 색 기준 유사색. 실제 발색·AR 진하기·수집 재고까지 증명하지 않음 |
| `get_option_ingredients` | `GET /api/products/{product_id}/ingredients?shadeId=&optionId=&ingredientName=&operator=` → `IngredientReadResult`; [ingredient schema](../../backend/api/app/schemas/ingredient.py) | EXISTING-CODE + ADAPTER-PROPOSED | `status`, `verdict`, `mappingStatus`, `reviewStatus`, `ingredientCoverage`, `sourceVersion`, `synthetic`를 모두 검사 |
| `check_ingredient_condition` | 위 성분 GET의 `ingredientName`/`operator` 사용 | EXISTING-CODE + ADAPTER-PROPOSED | `MATCH`는 **질문한 조건이 충족**이라는 뜻. `includes`/`excludes` 연산자 없이 단순 포함/부재로 해석 금지 |
| `get_catalog_look` | `GET /api/looks` / `GET /api/looks/{look_id}` → `LooksResponse/LookDetailResponse` | EXISTING-CODE | Catalog 룩·상품 연결은 검증 가능. 세부 영상 기법을 자동 보증하지 않음 |
| `get_video_look` | `GET /api/style-looks` → `StyleLooksResponse{looks}`; `GET /api/celebrity-videos` 별도 | EXISTING-CODE + ADAPTER-PROPOSED | 결과는 영상/제품 목록. API의 `StyleLook`에 검수 `recipe` 필드 없음; 챗봇 `CatalogStyleLook.recipe` 선택 필드와 불일치 |
| `get_style_recipe` | `backend/chatbot/app/services/style_recipe_service.py`의 `execute_style`; `StyleRecipe` 반환 | EXISTING-CODE (서비스 내부) + ADAPTER-PROPOSED | 실제 reviewed_recipe vs catalog_settings vs video_metadata를 구별. 승인 레시피의 원본 수량·서빙 경로 UNKNOWN |
| `execute_ar_action` / `get_ar_action_result` | `POST /api/chat` (`requestType=ar_command`) → `ChatResponse.arResult`, `POST /api/chat/acks` → `received:true` | EXISTING-CODE + NEW-API-PROPOSED | 현재 운영 AR 요청 저장 미구성 시 503. 제안은 적용이 아님; 영속 Action Ledger/ACK는 미구현 |
| `search_knowledge` | 현행 Neo4j `GraphRepository.find_products(terms,limit)`는 상품 관계 후보 검색 | PARTIAL + NEW-API-PROPOSED | **권리·발행 검증된 지식 RAG/벡터 API는 미확인**. AIHub 원문 서비스 RAG 권한 BLOCKED |
| `analyze_reference_media` | 전용 통합 챗봇 이미지·영상 입력 HTTP 스키마 없음 | NEW-API-PROPOSED | 사용자가 직접 제공한 미디어의 동의/전달/삭제/구간 출처 계약 필수 |
| `get_consented_skin_profile` | `store/skinProfileStore.ts`의 기기 프로필과 분석·설문 | NEW-API-PROPOSED (챗봇 연동) | 별도 접근 동의 후 구조화 결과만 전달, `experimental_unvalidated` 유지 |
| `retrieve_previous_conversation` / `write_preference` | 현재 `store/chatConversationStore.ts`의 앱 대화방, Redis 짧은 세션 | NEW-API-PROPOSED | 다른 대화방은 명시적 요청 B + 사용자 권한 검증, 장기 기억은 별도 저장 동의 |

### 제외해야 할 오해

- #228 `feat/catalog-option-evidence` 및 #229의 옵션별 실근거 검색은 **Closed·미병합**이므로 위의 실제 API로 표시하지 않는다. 재사용할 때는 새 Tool 계약에 맞게 선별 이식한다.
- `GET /api/products`의 `ids`는 50개 이하로 절단하고, 챗봇 `CatalogClient.search_products`는 입력 `ids`를 6개로 제한하고 후검증한다. 목표 Tool의 배치·결과 제한은 호환성 분석 후 별도 확정한다.
- 현재 `ChatRequest.message`는 문자열 필수, `requestId`는 일부 경로에서만 요구되고 일반 `chat`에서는 AR 관련 입력을 무시한다. 새 `threadId/turnId/requestId` 필수화와 멀티모달 입력은 **기존 요청 계약에 바로 추가 가능한 무해한 필드 변경이라고 가정하지 않는다**. 버전별 어댑터·앱 마이그레이션이 필요하다.

## 2. Tool 호출 봉투: LLM이 지정하지 못하는 실행 문맥

**설계 제안 (내부 Python/Pydantic 타입):**

```python
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class ServerToolContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["v1"] = "v1"
    owner_scope_ref: str           # 서버 인증에서 생성, LLM 제공값 신뢰 금지
    thread_id: str
    turn_id: str
    request_id: str
    plan_id: str
    plan_version: int = Field(ge=1)
    task_id: str
    expected_state_version: int = Field(ge=0)
    trace_id: str
    deadline_at: datetime
    # tool별 접근 허용·데이터 사용 정책은 서버에서 조회한 정책 참조만 전달
    policy_ref: str

class ToolInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_name: str
    arguments: dict[str, Any]  # Tool Registry가 이름별 엄격한 Pydantic 모델 재검증
    tool_call_id: str          # 한 실행 시도 ID
    context: ServerToolContext # 서버 주입, 에이전트가 작성한 임의 context 금지

class ToolError(BaseModel):
    code: Literal[
        "INVALID_ARGUMENT", "NOT_FOUND", "AUTH_REQUIRED", "FORBIDDEN",
        "RIGHTS_BLOCKED", "EVIDENCE_PENDING", "UNKNOWN_DATA", "STALE_CONTEXT",
        "CONFLICT", "RATE_LIMITED", "TIMEOUT", "UPSTREAM_ERROR",
        "ACTION_UNKNOWN", "UNSUPPORTED"
    ]
    retryable: bool = False
    safe_message: str

class EvidencePointer(BaseModel):
    source_system: str
    source_id: str
    product_id: str | None = None
    shade_id: str | None = None
    option_id: str | None = None
    evidence_id: str | None = None
    source_version: str | None = None
    review_status: str | None = None
    rights_status: str | None = None
    publication_status: str | None = None
    retrieved_at: datetime
    limitations: list[str] = Field(default_factory=list)

class ToolOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_call_id: str
    task_id: str
    plan_version: int
    status: Literal[
        "SUCCESS", "PARTIAL", "CLARIFICATION", "UNKNOWN",
        "BLOCKED", "ERROR"
    ]
    data: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidencePointer] = Field(default_factory=list)
    checked_scope: dict[str, Any] = Field(default_factory=dict)
    error: ToolError | None = None
```

이 코드는 **목표 내부 계약 초안**이다. 실제 코드에서는 `arguments` 및 `data`를 단일 자유 `dict`로 둔 채 운영하지 말고 `ProductSearchArgs`, `IngredientCheckArgs` 등 도구별 타입으로 검증해야 한다. 반환 시 `status`와 `error`의 합법적 조합도 모델 검증기로 강제한다. 네트워크에 공개하는 입력에는 `owner_scope_ref/policy_ref`를 노출하지 않고 서버 주입한다.

## 3. Product Tool: 개발 가능한 입출력 명세

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class ProductSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str | None = Field(default=None, max_length=80)
    category: str | None = None
    candidate_ids: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    max_reference_price_krw: int | None = Field(default=None, ge=0)
    limit: int = Field(default=6, ge=1, le=20)

class ProductFact(BaseModel):
    product_id: str
    brand: str
    name: str
    category: str
    shade_ids: list[str] = Field(default_factory=list)
    price_krw: int | None = None
    price_kind: Literal["catalog_reference", "collected", "verified_current", "unknown"]
    price_checked_at: str | None = None
    stock_status: Literal["available", "unavailable", "unknown"] = "unknown"

class ProductSearchData(BaseModel):
    results: list[ProductFact]
    total_returned: int = Field(ge=0)
    checked_candidate_count: int = Field(ge=0)
    truncated: bool = False
    unverified_filters: list[str] = Field(default_factory=list)
```

**어댑터 경계:** `GET /api/products`는 `q/category/ids/concerns`를 지원한다. 기존 `Product.priceKRW`는 카탈로그 필드로 읽고 `price_kind="catalog_reference"`로 표시한다. `max_reference_price_krw`는 참조가 비교되도록 명시된 경우에만 후처리하고, 이를 "실시간 판매가 2만 원 이하" 조건 충족으로 승격하지 않는다. `stock_status="unknown"`을 기본으로 유지한다. "현재가/현재 재고"와 복합 옵션 단위 조건은 **NEW-API-PROPOSED**이며 구 #228 설계의 재검토 대상이다.

**검증 게이트:** product.id 중복/누락 불가, 셰이드 ID는 해당 제품의 `shades[].id`에 반드시 존재, 외부 ID와 내부 ID 구분, `hex`가 추정/placeholder면 실제 발색 증명 금지, 결과 집합 `resultSetId` 및 제품 순서 고정 후 "두 번째" 참조. 사용자 계정별 카탈로그 공개 범위 외 사용자 보유 제품은 별도 권한 확인.

## 4. Ingredient Tool: 기존 HTTP 계약 그대로 보존

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class IngredientCheckArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: str = Field(min_length=1, max_length=128)
    shade_id: str | None = Field(default=None, max_length=128)
    option_id: str | None = Field(default=None, max_length=128)
    ingredient_name: str = Field(min_length=1, max_length=500)
    operator: Literal["includes", "excludes"]

class IngredientCheckData(BaseModel):
    product_id: str
    shade_id: str | None
    option_id: str | None
    operator: Literal["includes", "excludes"]
    ingredient_name: str
    verdict: Literal["MATCH", "NOT_MATCH", "UNKNOWN", "ERROR"]
    reason: str
    ingredient_coverage: Literal["full", "partial", "unknown"]
    review_status: Literal["verified", "unreviewed", "rejected"]
    source_version: str | None
    evidence_id: str | None
    synthetic: bool
    # 상태와 완전성 판단 결과는 검증기에 의해 도출
    verified: bool
    complete: bool
```

**기존 HTTP**: `GET /api/products/{product_id}/ingredients`와 `shadeId/optionId/ingredientName/operator`, 실제 `IngredientReadResult` 타입 사용. 근거 `evidenceId`와 `sourceVersion`은 선택 필드이고 비어 있을 수 있다. `status="ok"`만으로 성분 근거가 검증됐다는 뜻이 아니며 기존 챗봇 `CatalogIngredients.verified/complete`에 해당하는 조건을 **서버 측에서 재검사**한다. 특히 absence 판정은 full + 정상화 검증 + 옵션 귀속 + 식약처 동일성·검수·순서/버전 요건을 만족해야 한다.

| 조건 | `MATCH` 의미 | `NOT_MATCH` 의미 |
| --- | --- | --- |
| `operator="includes"` | 성분이 있음이 검증됨 | 성분이 없다는 조건 미충족의 검증 판정 |
| `operator="excludes"` | 성분이 없음이 검증됨 | 제외 조건 위반: 성분이 존재함이 검증됨 |

**주의:** `MATCH/NOT_MATCH`는 질문한 조건의 참/거짓이지 "성분 존재 여부"의 고정 코드가 아니다. 실제 판단은 `IngredientService.evaluate_ingredient`와 `CatalogClient.get_ingredients`의 세부 정합성 검증을 보존한다. `synthetic`은 실사용 검증으로 승격하지 않는다. `UNKNOWN`은 자료 미확인, `ERROR`은 조회 실패를 뜻하므로 조건 필터에서 서로 다르게 취급한다.

**권리·발행 분리:** 제품 전성분 확인과 특정 성분의 효능·안전성에 관한 지식은 별도 Tool/검수 경로다. 전성분 결과만으로 의학적 효능이나 부작용을 단정하지 않는다.

## 5. Style·Shade·AR Tool과 실제 경로

| 계약 항목 | 현재 방식 | 상세 목표·검증 |
| --- | --- | --- |
| `GetLookArgs(kind, lookId, recipeVersion?)` | `GET /api/looks/{id}` (catalog) 또는 `GET /api/style-looks` 목록에서 동일 ID 찾기 (video) | kind+lookId 네임스페이스·중복 ID/버전 검증. 관찰 정보의 출처 범위와 영상 기법의 검수 여부 구분 |
| `StyleRecipeData` | 챗봇 `StyleRecipe`에 `basis=reviewed_recipe/catalog_settings/video_metadata`, `reviewStatus` 등 존재 | `reviewed_recipe`일 때만 확인된 영상 순서·기법 설명 가능, 영상 `StyleLook` API 레시피 제공 미확인 |
| `SimilarShadeArgs(productId, shadeId, limit)` | `GET /api/shades/similar` | `limit 1~20`, source·matches·products 각각 검증, ΔE는 공식 색상 근접성 수치이며 AR 실착 유사도 아님 |
| `ARProposal` | `POST /api/chat`의 `requestType=ar_command`, `arContext`, `requestId` → `arResult.status=proposed` | `actionProposal`은 실제 적용 전 제안, 앱이 대상 product/shade, expectedStateVersion, supportedActions 재검증 |
| `ARAck` | `POST /api/chat/acks` + `ArAckRequest(requestId,commandId,sessionId,status,actualStateVersion)` | 실제 렌더 결과에서만 `APPLIED/NO_CHANGE/REJECTED/FAILED/UNKNOWN` 확정. 중복 전송은 같은 ID·같은 결과 재사용 |
| `ARUndo/Restore` | 일부 앱 `revertZone`/복원 코드 존재 | 자연어 Undo, 적용·취소·복원 분리, 영속 Action Ledger·Outbox를 AR 담당과 2-6에서 확정 |

기존 `ChatRequest`의 `requestId`는 `ar_command`에서 요구되지만 일반 `chat`은 동일한 방식으로 보존하지 않는다. 통합 LangGraph 요청 스키마의 `threadId,turnId,requestId,actionId`는 버전 호환 계층이 필요하다. 현재 `chat_service.py`는 운영에서 `ar_requests_unavailable` 503을 반환할 수 있으므로 운영 AR 실행 완료 표기 금지.

## 6. Knowledge·Graph·Vector·Media·Memory 계약

**Graph Tool (현재):** `backend/chatbot/app/repositories/graph_repository.py`의 `find_products(terms,limit=6)`는 관계 그래프에서 상품 후보를 읽는다. 관계 탐색이 존재한다고 해서 지식 QA, 근거 승인, 텍스트 임베딩 검색이 구현됐다는 뜻은 아니다.

**Knowledge Tool (제안):** `KnowledgeQueryArgs`는 `query, allowedSourceScopes, desiredEvidenceTypes, maximumDocuments` 등을 가질 수 있다. 그러나 권한 정책·출처 범위는 서버 생성 `policy_ref`로 추가 제한한다. 반환 `KnowledgeEvidence`에는 `sourceId, revision, rightsStatus, publicationStatus, supportStatus, exactClaim, limitations, checkedAt`이 포함되어야 한다. 실제 필드·벡터 인덱스·API는 3단계 설계·팀 승인 전 **미구현**.

**검색 순서:** 사용자 권한·문서 권리·검수/발행 상태 사전 필터 → PostgreSQL 원본/Catalog API·Neo4j 관계·Vector 검색 중 필요한 도구 선택 → 후보와 출처 버전 수집 → 권리·발행·원본 버전 재검증 → 검증 가능한 사실만 구조화 응답. 검색 전에 권리 미승인 자료를 색인/외부 모델에 노출해서는 안 된다. 캐시된 근거가 철회되면 조회·재응답을 차단한다.

**Media Tool (제안):** 서버 주입된 `mediaRef`, `purpose`, `grantedScope`, `expiresAt`, `mediaType`, `analysisRange`, `sourceFrameRanges`, `modelVersion`을 사용한다. 사용자 미디어 원본을 일반 Graph State/LLM trace에 넣지 않고 업로드·처리·제3자 제공·삭제·기억 재사용 동의를 구분한다.

**Skin Tool (제안):** `profileRef`/`consentRef`로 접근하고 `captureSource`, `modelVersion`, `validationStatus=experimental_unvalidated`, 설문·자기보고를 분리한 구조화 결과를 제공한다. 이를 확정 진단으로 전환하는 Tool은 허용하지 않는다.

**Memory Tool (제안):** `retrieve_previous_conversation`은 현재 정책 B에 따라 사용자의 명시적 요청이 필요. 서버에서 `threadOwner` 검증, 삭제·보관 정책 및 대상 접근 허가를 적용한다. 향후 C 자동 검색을 위한 Retriever 인터페이스는 유지하되 현재 자율 호출 금지. `write_preference`는 동의한 장기 저장 행위여서 읽기 전용 Tool과 분리하여 권한·감사·삭제 계약을 가진다.

## 7. 검증과 오류 정규화

기존 FastAPI `ApiError`는 `{"error":"...","code":"..."}` 형태이며 별도의 `http_status`를 반환한다. 새 Tool은 이 코드를 보존한 채 내부 `ToolError.code`로 매핑한다.

| 현재 상태/오류 근거 | Tool 결과 해석 | 재시도 |
| --- | --- | --- |
| `400 invalid_category / invalid_concern / invalid_ingredient` | `INVALID_ARGUMENT`, 입력 재해석 또는 질문 | 동일 입력 자동 재시도 금지 |
| `401 unauthorized / 403 forbidden` | `AUTH_REQUIRED/FORBIDDEN`, 권한 확인 | 재인증/동의 없이 금지 |
| `404 not_found / shade_not_found` | `NOT_FOUND`, 대상·호수 다시 확인 | 같은 ID 무한 재시도 금지 |
| `409 chat_session_conflict / chat_request_conflict` | `CONFLICT`, 최신 stateVersion/기존 request 재조회 | 새 논리 요청 ID로 중복 실행 금지 |
| `410 chat_session_expired` | `STALE_CONTEXT`, 현재 상품/결과 집합 재조회 | 유효성 확인 후 새 작업 |
| `429 rate_limited` | `RATE_LIMITED`, 사용자 안내·백오프 | 제한 내 읽기 작업만 |
| `502 upstream_error` | `UPSTREAM_ERROR`, 서비스 오류 | 제한된 읽기 작업 재시도 |
| `503 ingredient_lookup_failed / ingredient_alias_approvals_invalid` | `UPSTREAM_ERROR` 또는 `EVIDENCE_PENDING`으로 단정 금지. 실제 자료 조회 실패 | 판정 ERROR 또는 응답 불가, 자료 부재로 표현 금지 |
| `503 ar_requests_unavailable` | `UNSUPPORTED`/`UPSTREAM_ERROR`: 운영 AR 실행 불가 | 적용 시도/성공으로 표시 금지 |
| HTTP 200 + `verdict=UNKNOWN` | `UNKNOWN_DATA` | 권한 있는 다른 근거 탐색, 부재 확정 금지 |
| 권리·발행 미승인 | `RIGHTS_BLOCKED/EVIDENCE_PENDING` | 원문 색인·외부 LLM 전송 차단 |
| ACK 유실·작업 결과 불명확 | `ACTION_UNKNOWN` | 같은 actionId 상태 조회, 명령 재실행 금지 |

`UNKNOWN_DATA`와 `UPSTREAM_ERROR`는 다른 결과다. `403` 인증 오류를 `UNKNOWN`으로 바꾸지 않는다. 네트워크 타임아웃 후 외부 상태 변경이 이미 발생했을 수 있으므로 읽기 Tool과 쓰기 Action은 재시도 정책을 분리한다.

## 8. 테스트 케이스와 완료 기준 (개발 전 제출할 검증 명세)

| ID | 사전 조건 | 실행 | 확인할 불변조건 |
| --- | --- | --- | --- |
| TC-01 | catalog product A·shade A-1 | `get_product_detail(A)` | 실제 Product.id가 A이고 shade A-1이 같은 제품에 귀속 |
| TC-02 | product A만 유효 | 존재하지 않는 ID 상세 조회 | 404 → `NOT_FOUND`, 가짜 상품/호수 생성 금지 |
| TC-03 | 참조가만 존재 | "현재 2만원 이하" 조건 검색 | 현재 판매가로 확정하지 않고 검증 부족 표시 |
| TC-04 | 제품 가격·옵션의 수집 시점 상이 | 같은 모델 내 서로 다른 shade | 서로 다른 옵션의 가격·성분 혼용 금지 |
| TC-05 | 성분 원문 불완전 | `operator=excludes` 검색 | 없음 `MATCH`로 확정 금지; `UNKNOWN` |
| TC-06 | 검수된 성분 존재 | `operator=excludes` 질의 | `NOT_MATCH`로 제외 조건 위반 인식 |
| TC-07 | 검수·완전 전성분에서 부재 | `operator=includes` 질의 | `NOT_MATCH`일 수 있으나 근거 ID·버전/완전성 필요 |
| TC-08 | 서로 다른 옵션 | 성분 응답의 shade/option ID 변경 주입 | 선택 불일치 시 결과 폐기 |
| TC-09 | sourceVersion 변경/승인 철회 | 이전 결과 재사용 | 재검증 후 확정 판정 캐시 재사용 금지 |
| TC-10 | 권리 미승인 AIHub 문서 | Knowledge 검색 | 검색 단계/외부 LLM 공급 전에 차단 |
| TC-11 | metadata만 있는 영상 | 영상 화장법 질문 | 실제 관찰한 영상 기법처럼 설명하지 않음 |
| TC-12 | 검수된 룩·옵션 있음 | `get_style_recipe` | kind/lookId/version/evidence/제품 매핑 일치 |
| TC-13 | 다른 사용자의 대화방 | 이전 대화 조회 | 소유권 `FORBIDDEN`, 히스토리 노출 금지 |
| TC-14 | 명시적 과거 대화 조회 | 현재 요청 B | 과거 후보 참조 후 Catalog 최신 재검증 |
| TC-15 | 미디어 동의 철회 | Visual Tool 호출 | 전송·분석 차단, 참조/파생 데이터 삭제 정책 적용 |
| TC-16 | AR 명령 제안만 생성 | `arResult.status=proposed` | 앱 적용 성공 메시지 금지 |
| TC-17 | 렌더 성공 후 ACK 유실 | ACK 재전송 | 동일 commandId·status, 명령은 재실행하지 않음 |
| TC-18 | 동일 요청 재전송 | 동일 requestId + 같은 payload | 중복 처리/부작용 방지, 기존 결과 확인 |
| TC-19 | 동일 ID로 다른 payload | Tool/Action 호출 | 충돌로 거부 |
| TC-20 | 사용자가 목표 변경 | 오래된 planVersion 결과 도착 | 현재 선택·AR 상태 덮어쓰기 금지 |
| TC-21 | Neo4j/Vector 검색 결과의 상품 ID가 폐기됨 | Graph/RAG 후보 재조회 | Catalog 최신 검증 불일치면 카드 반환 금지 |
| TC-22-I18N-FOLLOWUP | `en/ja/zh` UI 번역·Chat 로케일 타입 존재 | **후속 확장 평가**에서 각 언어의 동일 사실 질의·AR·음성 확인 | **1차 필수 한국어 평가에서 제외**. 시점·통과 기준 OPEN-LANG-01, [07](07-ko-first-language-and-evaluation.md) |
| TC-KO-STRUCTURE-01 | 1차 한국어 Tool 실행·API 계약 | 한국어 발화·동일 식별자·스키마 상태·근거·가격·성분 값 검증 | **1차 필수 검사 계획**: 결과 구조·식별자와 근거 상태가 응답 언어에 종속되지 않음. 다국어 품질 통과 주장이 아님 |

이 표는 **시험 계획**이고 실행 통과 증빙이 아니다. 테스트용 `synthetic` 식별자·근거를 실데이터로 승격하지 않는다. 실제 Catalog 옵션·성분·레시피 표본·권한 있는 지식의 확보 여부는 3단계 데이터 실사 후 확정한다.

### 1차/후속 언어 평가 분리

- **VAI-D-013 (ACCEPTED-USER)**: 한국어(`ko`)가 1차 AI 구현·평가 언어. Tool 요청·응답·DB ID/상태/근거 스키마에는 `ko` 문자열을 식별키로 사용하지 않는다.
- 예전 **TC-22를 TC-22-I18N-FOLLOWUP으로 이관**해 `en/ja/zh` AI/STT/TTS 품질은 1차 합격 조건에서 제외한다. 한국어 자체의 구조 불변 검사는 `TC-KO-STRUCTURE-01`로 별도 계획한다. 테스트를 실행한 것은 아니다.
- 미지원 AI 언어의 앱 안내·한국어 상담으로의 선택적 진입은 [07](07-ko-first-language-and-evaluation.md)의 **OPEN-LANG-02 (PROPOSED)** 정책을 따른다. 자동으로 앱 전체 언어를 전환하지 않는다.
- 1차 `ko`를 우선하지만 `inputLanguage/responseLocale/sourceLanguage`는 필요시 구분하고 각 Tool·Agent의 표준 필드는 언어 중립으로 유지한다.

## 9. 결정·담당자 합의가 필요한 기술 선택

| ID | 선택지와 판단 근거 | 권장 검토 시점 |
| --- | --- | --- |
| OPEN-T01 | **옵션 복합 검색**: 기존 GET을 챗봇이 순차 호출·후처리 vs #228을 선별 이식한 일괄 옵션 검색 API. 정확한 옵션별 조건·검색 범위·지연 측정이 후자에 유리할 수 있으나 소유/테스트/마이그레이션 검증이 필요 | 2-5 / Catalog 담당 |
| OPEN-T02 | **지식 벡터 검색 엔진**: pgvector vs 독립 VectorDB. 권리 메타데이터·갱신/철회·재현성/비용/성능으로 비교 | 3단계 |
| OPEN-T03 | **증거 데이터 표준**: 현재 IngredientReadResult 필드 그대로 vs 공통 EvidenceEnvelope 및 원본 필드 혼용. 호환성 확보를 위해 어댑터 도입 우선 검토 | 2-5 |
| OPEN-T04 | **Tool 호출 API 진화**: 현행 `/api/chat` 유지·버전 어댑터 vs 신규 버전 라우트. 구형 앱, requestId 정책, STT/미디어 요청 범위 영향 확인 | 2-6 |
| OPEN-T05 | **운영 지식 출처/권리**: AIHub 별도 승인 확보 vs 공개·라이선스 검증된 대체 자료 구축, 서비스 색인/외부 모델 제공 가능성 별도 판정 | 3단계 |
| OPEN-T06 | **성능/시간 제한**: Catalog·Neo4j·Vector/멀티모달의 타임아웃/부분 결과/최대 병렬 범위. 사용자 경험과 실제 지연·실패 관측 필요 | 2-7 / 평가 |
| OPEN-T07 | **Tool별 권한**: 앱 사용자 JWT, guest, 챗봇→Catalog 서비스 자격, media/skin/previous conversation 권한 범위 검증 | 2-5 / 보안·API |

**현재 사용자에게 즉시 요청할 새로운 결정 없음.** 위 항목은 구체적인 대안과 영향·확인 근거를 정리한 뒤 사용자/담당자에게 확정 요청한다.

## 10. 2-5 검토 종료 조건

1. 실제 기존 API 계약·응답 필드·오류 코드와 목표 Tool이 **1:1로 추적** 가능.
2. 추가 필요한 새 API/Adapter의 범위·담당·호환성·권한·idempotency 계약 명시.
3. 상품·호수·성분 검증 불변조건과 권리 차단 근거 및 최소 테스트 명시.
4. 지식/Vector/Neo4j의 정본과 인덱스 책임, 색인·철회·검증 시퀀스 확정.
5. 승인된 사용자 목표·미승인 기술 선택·구현/테스트 근거를 분리.
6. AR Action Ledger·STT/TTS는 2-6, 저장소 물리 배치·평가 지표는 2-7·3~4단계로 인계.

2-5 상세 계약의 **검토·합의가 끝난 뒤에만** Issue·PR 단위의 작업 명세로 전환한다.

## 11. 2026-11-15 변경 기록

- 1차 평가 한국어(`ko`) 확정에 따라 기존 TC-22의 네 언어 동시 검증을 후속 TC-22-I18N-FOLLOWUP으로 이동. 한국어 구조 불변조건 TC-KO-STRUCTURE-01 추가.
- 14개 능력·12개 시나리오, Tool의 기존 API 경로·판정 계약·검수 조건은 변경하지 않음.
- 실제 옵션별 검색·원본/그래프/벡터 동기화 검토는 [08 옵션·근거·색인 계약](08-option-search-evidence-and-sync.md)에 별도 기록. 기술 선택·테스트 결과는 아직 PROPOSED.
