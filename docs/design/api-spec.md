# API 명세

## 0. 범위와 판정

2026-10-28 작업 트리의 `backend/api/app/routers/`, `backend/chatbot/app/routers/`, `app/api/`를 정적으로 조사했다. 표의 **PARTIAL**은 코드가 있으나 이번 조사에서 실서비스·의존성·종단 간 동작을 확인하지 않은 상태다. 실제 배포, DB 마이그레이션, 외부 API 키와 운영 응답은 **UNKNOWN**이다. 특히 결제 파일은 작성 시점의 미커밋 사용자 작업이며 배포된 기능이라고 단정하지 않는다. 응답 모델의 모든 필드는 `backend/*/app/schemas/` 및 `types/index.ts`를 최종 계약으로 확인한다.

기본 진입점은 환경별 Gateway이며, 일반 JSON은 camelCase다. `GET /healthz`, `GET /readyz`는 서비스별 내부 probe로 같은 경로를 각 서비스에 직접 사용한다. 오류는 보통 `{ "error": "...", "code": "..." }`이고 code는 선택적이다 (`backend/*/app/core/errors.py`). 요청 검증 실패 400 `invalid_request`, 찾지 못함 404 `not_found`, 예기치 않은 오류 500 `internal`; 아래 표의 오류는 해당 경로에서 특별히 확인되는 예다. 외부 시스템이나 DB 오류 전체를 망라한 보장은 아니다.

## 1. 공개 API

| Method · endpoint | 인증 | 입력 | 성공 응답 | 주요 오류 | 모듈 · 상태 |
|---|---|---|---|---|---|
| GET `/api/health` | 없음 | 없음 | `{ok, integrations}` | 500 | `api/routers/health.py` · PARTIAL |
| GET `/api/products` | 없음 | `q`, `category`, `ids` 쉼표 구분 최대 50개, `concerns` | `{products: Product[]}` | 400 `invalid_category`, `invalid_concern` | `catalog.py`, `catalog_service.py` · PARTIAL |
| GET `/api/products/{product_id}` | 없음 | 경로 id | `{product: Product}` | 404 `not_found` | catalog · PARTIAL |
| GET `/api/products/{product_id}/offers` | 없음 | 경로 id | `{configured, offers}` (`schemas/external.py`) | 404 `not_found`, 502 `upstream_error` | catalog, `offer_service.py`, Naver client · PARTIAL |
| GET `/api/looks` | 없음 | 없음 | `{looks: CelebLook[]}` | 공통 | catalog · PARTIAL |
| GET `/api/looks/{look_id}` | 없음 | 경로 id | `{look, products}` | 404 `not_found` | catalog · PARTIAL |
| GET `/api/stores` | 없음 | 없음 | `{stores: Store[]}` | 공통 | catalog · PARTIAL |
| GET `/api/idol-looks` | 없음 | 없음 | `{looks: IdolLook[]}` | 공통 | `idol_looks.py`, `idol_look_service.py` · PARTIAL |
| GET `/api/idol-looks/{look_id}` | 없음 | 경로 id | `{look, products}` | 404 `not_found` | idol looks · PARTIAL |
| POST `/api/shades/recommend` | 없음 | `{skin:{ita?:number,mst:1..10,undertone?:cool\|neutral\|warm},limit?:1..20}` | `{skinHex, matches}`; 각 후보에 productId, shadeId, 색상, deltaE 등 | 400 `invalid_request` | `shades.py`, `shade_service.py` · PARTIAL |
| GET `/api/shades/similar` | 없음 | `productId`, `shadeId`, `limit` 1..20 | `{source, matches, products}` | 400/404 등 서비스 검증 | shades · PARTIAL |
| GET `/api/youtube/search` | 없음 | `q`, `max` (1..12, 기본 8) | `{configured, videos}`; 미설정 시 빈 목록 | 400 `missing_query`, 429 `rate_limited`, 502 `upstream_error` | `tutorials.py`, `tutorial_service.py` · PARTIAL |
| GET `/api/me` | Supabase Bearer | 없음 | `{user, terms:{version, agreedVersion?, agreedAt?}}` | 401 `unauthorized`, 503 `auth_unavailable` | `members.py`, `member_service.py`, `core/auth.py` · PARTIAL |
| POST `/api/me/terms` | Supabase Bearer | `{version:1..32자}` | `{version, agreedVersion, agreedAt}` | 400 `invalid_request`, 401, 409 `terms_outdated` | `members.py`, `member_service.py` · PARTIAL |
| DELETE `/api/me` | Supabase Bearer | 없음 | 204 | 401, 502 `account_upstream`/`account_deletion_failed`, 503 `account_deletion_unavailable` | `members.py`, `member_service.py`, `supabase_admin_client.py` · PARTIAL |
| POST `/api/chat` | 유효 Bearer 또는 32–128자 임의 `X-Vishue-Anonymous-Id` | `{message:1..1000자,locale?:en\|ko\|ja\|zh,skin?:{mst,undertone}}` | `{answer, products}` | 400 `invalid_request`, 429 `rate_limited`, 502 `upstream_error`, 503 `chatbot_unavailable` | `chatbot/routers/chat.py` · PARTIAL |
| POST `/api/payments/orders` | Supabase Bearer | `{lines:[{productId,shadeId?,quantity:1..20}]}` 1..30개 | `{orderId,amount,checkoutUrl}` | 400 `invalid_order`, 401, 503 `payment_unavailable` | 미커밋 `payments.py`, `payment_service.py` · PARTIAL |
| POST `/api/payments/confirm` | Bearer 대신 주문 checkoutToken 검증 | `{orderId,paymentKey,amount,checkoutToken}` | `{orderId,status:"paid",returnUrl}` | 404 `not_found`, 400 `invalid_payment`/`payment_failed`, 502 `payment_upstream`, 503 `payment_unavailable` | 미커밋 payments · PARTIAL |
| GET `/pay/{order_id}?token=...` | checkoutToken 검증 | 주문 id, token | Toss 결제 위젯 HTML | 404 `not_found` | 미커밋 payments · PARTIAL |
| GET `/pay/success`, `/pay/fail` | 없음 | 결제 제공자 redirect 값 | 승인 요청 또는 앱으로 이동하는 HTML | 승인 경로 오류 | 미커밋 payments · PARTIAL |

`Product`는 id, brand, name, nameKo, category, makeupZone, texture, priceKRW, volume, shades, description, keyIngredients, tags, imageUrl, searchKeyword를 포함한다. `IdolLook`은 video, products, arSettings와 검증 상태를 포함하며 `verified_used`, `unverified`, `similar`를 구분한다. 응답의 제품 목록은 챗봇이 검색한 후보이며 답변 텍스트에 언급된 제품만을 사후 검증한 결과는 아니다.

### 1.1 요청 예

```json
{"skin":{"ita":35.0,"mst":4,"undertone":"neutral"},"limit":5}
```

위 객체는 `POST /api/shades/recommend`의 요청 예시이며 측정 결과나 진단이 아니다. 사진과 영상 전송은 허용된 계약에 포함되지 않는다.

## 2. 내부·개발 전용

| Method · endpoint | 용도와 응답 | 인증·상태 |
|---|---|---|
| GET `/healthz` | 각 프로세스 생존 `{ok:true}` | 인프라 probe · PARTIAL |
| GET `/readyz` | api는 database/redis, chatbot은 graph/redis 검사; 200 또는 503 | 인프라 probe · PARTIAL |
| GET/POST `/api/dev/nia/{action}` | 로컬 연구 프로세스 프록시. GET은 status/job/export/sample, POST는 load/infer/evaluate/profile; body 최대 18 MiB, 제한 query는 id/format/index | 개발 전용 · PARTIAL; `NODE_ENV=development`와 서버 토큰 필요; 미설정·타임아웃 503 `nia_unavailable`, 미허용 경로 404, 초과 413 `upload_limit` |
| GET `/health` | 별도 데스크톱 피부 추론 서버의 모델 및 GPU 상태 | Bearer · PARTIAL; `server/nia/api.py` |
| POST `/analyze` | 별도 데스크톱 피부 추론 서버의 JPEG/PNG 분석 코드와 feature 응답 | Bearer · PARTIAL; 401 `UNAUTHORIZED`, 422 `INVALID_IMAGE` 등, 503 `SERVER_BUSY`; 현재 사용자 지시의 얼굴 이미지 전송 금지와 충돌하므로 허용 기능으로 간주하지 않음 |

`chatbot/app/jobs/sync_graph.py`는 내부 배치 진입점이지 HTTP 엔드포인트가 아니다. api의 제품·룩 GET 계약을 읽어 Neo4j 사본을 갱신한다. 문서에 없는 제안 API는 현재 존재하는 경로로 간주하지 않는다.

## 3. 인증, 재시도와 장애

Bearer JWT 검증은 `backend/*/app/core/auth.py`의 Supabase JWKS 검증 또는 호환 경로를 사용한다. 앱은 `lib/api.ts`에서 토큰을 첨부한다. 챗봇 익명 ID는 제한 키로 해시되며 인증된 사용자 식별자로 취급하지 않는다. 네이버·YouTube·LLM 키는 서버 설정에만 둔다. 일부 응답은 `cache_for`로 공개 캐시를 설정하며 값은 각 라우터가 권위다. 외부 요청의 실제 재시도·타임아웃은 클라이언트별 구현이 다르므로 일괄 정책으로 간주하지 않는다. 결제 재시도는 제공자 성공 후 DB 기록 실패 등 불확실한 결과를 재조정하도록 설계·시험해야 한다. 이는 **PROPOSED**다.
