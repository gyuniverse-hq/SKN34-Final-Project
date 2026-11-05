# 추천 시스템 데이터 요구사항 정의서 v0.3

- 기준: `추천_시스템_데이터_요구사항_정의서_v0.2.md`, `VISHUE_Recommendation_Schema.md`, 현재 API·DB 연동 코드
- 범위: 기초 화장품 성분 기반 추천(`/api/recommendations/skincare`)
- 상태: DB 테이블 계약과 추천 입력·출력 정의. 실제 DB의 최신 행 값과 운영 활성 상태는 별도 확인한다.

## 1. v0.2에서 갱신한 내용

v0.2는 피부 모델 등급, 피부 타입 설문, 리뷰 응답 비율 등을 추천 입력 피처 후보로 정의했지만, 현재 추천 API가 실제로 받거나 순위에 사용하는 데이터와 구분되어 있지 않았다. v0.3은 **현재 구현 계약**과 **향후 입력 후보**를 나누고, 실제 DB의 `rec_*` 스키마를 성분 추천의 기준으로 삼는다.

피부 영상·이미지·모델 원점수는 이 API로 보내지 않는다. 현재 API 입력은 사용자가 선택한 주·보조 관리 목표, 선택적 피부 타입과 자극 신호, 정책 버전, 결과 개수다. 피부 분석·설문은 기기 안에서 목적을 제안하는 데 활용할 수 있지만 서버 전송 필드가 아니다.

## 2. 데이터 흐름

1. 앱이 선택한 주목표와 선택적 보조 목표·피부 타입·자극 신호를 API에 보낸다.
2. 서버는 `skincare_serving`의 검증된 발행본을 읽는다.
3. 발행본은 현재 DB의 추천 매핑·성분 연결·옵션 일치 테이블과 카탈로그·가격·리뷰 원천에서 생성한다.
4. 추천 서비스가 적격 매핑 및 일치 상품 옵션을 필터링하고 순위를 정한다.
5. 응답은 저장하지 않으며 `Cache-Control: no-store`를 설정한다.

```text
rec_mapping ─┬─ rec_mapping_ingredient ─┐
rec_evidence ┘                           ├─ skincare_serving ─ 추천 API
rec_ingredient_link ─ 옵션 성분 ─────────┤
rec_concern_match ─ 옵션 일치 결과 ──────┤
raw_oy_* + 검수 manifest ─ 상품·가격·분류┘
```

## 3. 요청 데이터 계약

`POST /api/recommendations/skincare`

| 필드 | 형식 | 필수 | 의미 |
|---|---|---:|---|
| `primaryGoal` | enum | 예 | 주목표: `dryness`, `sensitivity`, `pigmentation`, `wrinkles`, `pores`, `oiliness`, `blemish` |
| `secondaryGoals` | enum 배열, 최대 6 | 아니요 | 보조목표. 주목표 중복을 제거하고 표준 목표 순서로 정규화 |
| `skinType` | enum | 아니요 | `dry`, `balanced`, `oily`, `unknown`; 미지정은 `unknown` |
| `irritationSignal` | enum | 아니요 | `caution`, `none`, `unknown`; 미지정은 `unknown` |
| `goalPolicyVersion` | 문자열 | 예 | 현재 허용값 `care-goals-v1` |
| `limit` | 정수 1~20 | 아니요 | 반환 상한, 기본 8 |
| `includeTrace` | bool | 아니요 | local/development/test 환경에서만 개발 추적을 응답 |

알 수 없는 필드는 거부한다. 사용자 자유 응답, 얼굴 이미지·영상, 피부 분석 원점수, 상세 설문 답변, 사용자 식별자는 요청에 포함하지 않는다.

## 4. DB 테이블 요구사항

### 추천 규칙과 근거

| 테이블 | 추천 사용 컬럼 | 요구사항 |
|---|---|---|
| `rec_concern` | `target_concern`, `display_label`, `recommendation_reason` | 허용 고민 코드와 표시 문구를 관리한다. |
| `rec_mapping` | `mapping_id`, `mapping_type`, `target_concern`, `mapping_status`, `human_mapping_review`, `ai_paper_review`, `re_review_required`, `runtime_enabled`, `requirements_scope` | 승인·등급·운영 활성 상태를 원본 그대로 보존한다. |
| `rec_mapping_ingredient` | `mapping_id`, `ingredient_code`, `component_order` | 매핑 구성 성분의 정규화 기준이다. `rec_mapping.ingredient_codes` 원문을 파싱해 대체하지 않는다. |
| `rec_evidence` | `evidence_id`, `pmid`, `title`, `source_url`, `ai_paper_review`, `study_limit` | 근거와 연구 한계를 발행본에 보존한다. 근거가 없는 매핑은 노출하지 않는다. |
| `rec_ingredient_dictionary` | `ingredient_code`, `name_ko`, `inci_name`, `source_match_status` | 성분 코드 사전 및 출처 확인용이다. |
| `rec_manual_review_candidate` | `ingredient_code`, `source_name`, `review_reason`, `approved` | 검수 전 후보 기록이다. 승인된 성분 연결로 간주하지 않는다. |

### 성분 연결과 옵션 단위 일치

| 테이블 | 추천 사용 컬럼 | 요구사항 |
|---|---|---|
| `rec_ingredient_link` | `ingredient_code`, `oy_ingredient_id`, `link_method`, `reviewed_by`, `reviewed_at`, `note` | 추천 성분 코드와 현재 수집 DB 성분을 연결한다. `exact_name` 외 연결은 검수자와 날짜를 요구한다. 코드 하나가 여러 수집 성분에 연결될 수 있다. |
| `rec_concern_match` | `mapping_id`, `option_id`, `computed_at` | 매핑의 구성 성분을 모두 포함하는 상품 **옵션**만 기록한다. 행이 없는 옵션은 불일치다. |

상품 정보는 `products`와 `shades`에서 읽고, 올리브영 상품번호로 원천 옵션·가격·리뷰와 연결한다. 옵션별 추천 매핑을 적용한 결과는 `skincare_serving`에 발행한다.

## 5. 매핑 노출 조건

다음 조건을 모두 만족한 매핑만 순위 계산에 사용할 수 있다.

- `mapping_type = single`이고 정규화 구성 성분이 한 종류다.
- `target_concern`이 지원 목표 중 하나다.
- `runtime_enabled = true`다.
- `mapping_status = candidate_after_match`다.
- `human_mapping_review = 승인`, `ai_paper_review = 승인`이다.
- `re_review_required = false`다.
- 구성 성분 코드가 모두 검수된 성분 연결 및 근거 정보와 이어진다.
- 후보 상품 옵션이 해당 매핑의 `rec_concern_match` 행을 갖고, 옵션 성분도 구성 성분을 전부 포함한다.

조합 매핑은 DB와 발행본에 보존할 수 있으나, 현재 추천 노출은 단일 성분 매핑만 지원한다. 매칭 여부는 옵션 단위로 판단한다. 상품으로 합칠 때는 일치한 옵션을 대표로 사용하며, 다른 옵션의 성분을 합쳐 일치로 보지 않는다.

`runtime_enabled`는 검수된 매핑의 운영 노출 여부다. 적재·번들 생성·발행 과정은 이 값을 자동으로 켜거나 검수 상태를 변경하지 않는다. 운영자가 승인된 값을 DB에 반영한 뒤 재생성·발행한다.

## 6. 상품 후보와 랭킹

1. 검수 manifest에서 허용한 올리브영 세부분류(`toner`, `essence`, `serum`, `ampoule`, `lotion`, `cream`)와 연결되는 상품을 사용한다. 세트·마스크·선케어·세정제는 범위 밖이다.
2. `is_in_catalog = true`, 미삭제 상품·옵션, 검수된 판매중 상태, 품절 아님, 양수 판매가, 상품명·브랜드가 있는 후보만 남긴다.
3. 주목표 일치 매핑을 먼저 둔다. 다음으로 보조 목표 일치 수를 비교한다.
4. 사용자가 자극 주의를 표시했으면, 출처가 확인된 제조사 민감 피부 표기를 보조 순위에 반영한다. 사용자 피부 타입과 출처가 확인된 제조사 피부 타입 표기도 보조 기준이다.
5. 리뷰는 상품별 한 번만 반영한다. 유효 리뷰가 있으면 베이지안 보정 평점(`REVIEW_PRIOR=20`)과 리뷰 수를 순위 보조값으로 사용한다. 피부 타입·자극·고민별 리뷰 응답 비율은 문항별 응답자 수가 없어 사용하지 않는다.
6. 동률은 상품 ID와 옵션 ID로 안정적으로 정렬한다. 옵션 중복 상품은 한 건으로 반환하고 결과 수를 `limit`로 제한한다.

순위는 제품 효능이나 임상적 효과 점수를 뜻하지 않는다. 초기 정렬 규칙은 검증된 효능 비교 모델이 아니라 결정적 휴리스틱이다.

## 7. 발행용 데이터와 품질 검사

발행 데이터는 `skincare_serving`의 단일 JSONB 스냅샷으로 유지한다. 최소 구성은 다음과 같다.

- `dataVersion`, `sourceManifest`
- `mappings`: 고민, 매핑 유형, 구성 성분, 근거 ID, 검수·등급·운영 상태
- `evidence`: 논문 출처와 `study_limit`
- `ingredientProvenance`: 성분 연결 출처와 검수 근거
- `options`: 상품·옵션, 가격·판매 상태, 성분 코드, 피부 타입 표기, 리뷰 및 `matchedMappingIds`

발행 전 검증 기준:

- 매핑 ID·옵션 ID 중복 없음, 각 매핑에 정규화 구성 성분이 있음.
- 매핑이 참조하는 근거·성분 코드가 존재하며, 미연결 코드는 매핑을 비활성 검수 상태로 유지한다.
- `exact_name`이 아닌 링크에는 검수자와 날짜가 있다.
- `matchedMappingIds`는 실제 발행 매핑 ID만 참조한다.
- `rec_concern_match`의 조합 결과가 같은 옵션의 성분 전체 포함과 일치한다.
- 상품·옵션 원천, 분류 manifest, 매핑 데이터 버전과 해시를 기록한다.
- 기존 스냅샷은 전체 생성이 성공한 뒤 한 트랜잭션으로 교체한다. `--apply` 전에는 미리보기만 한다.

제안 실행 순서:

```powershell
uv run python ../../scripts/data/oliveyoung/build_skincare.py reviewed-manifest.json reviewed-bundle.json
uv run python -m app.jobs.publish_skincare reviewed-bundle.json
uv run python -m app.jobs.publish_skincare reviewed-bundle.json --apply
```

첫째 명령은 DB에서 일관된 읽기 전용 스냅샷을 만들며 지정한 번들 파일만 쓴다. 둘째는 검증 결과를 출력한다. 셋째는 게시 데이터를 DB에 반영한다. 마이그레이션은 기존 배포 절차로 별도 적용한다.

## 8. API 응답과 빈 결과 사유

응답은 `dataVersion`, `coverage`, `matches`를 제공한다. 개발 추적은 개발 환경에서만 제공한다. 응답은 `no-store`이며 서버는 사용자별 추천 요청이나 이력을 저장하지 않는다.

| coverage 상태 | 의미 |
|---|---|
| `mapping_unavailable` | 요청 목표에 적격 운영 매핑이 없다. 운영 비활성, 검수·등급 조건 미통과, 구성 성분 미연결, 근거 부재가 원인일 수 있다. |
| `no_matches` | 적격 매핑은 있으나 현재 게시 스냅샷에 일치하는 판매 가능 옵션이 없다. |
| `ok` | 적격 매핑으로 후보 상품을 찾았다. |

빈 결과만으로 어느 DB 컬럼이나 검수 플래그가 원인인지 단정하지 않는다. 개발 추적 또는 DB 점검으로 매핑 제외 이유를 확인한다.

`oiliness`, `blemish`도 요청할 수 있지만, 적격한 검수 매핑이 없는 동안에는 `mapping_unavailable`이다. 매핑 승인 상태는 요청 범위 확장으로 변경하지 않는다.

## 9. 이번 버전의 미포함 항목

- 피부 모델 등급과 모델 점수로 서버에서 고민을 자동 선택하는 기능
- 설문 원응답이나 개인별 자극·고민 리뷰 비율을 전송·저장하는 기능
- 성분의 함량·전성분 나열 순서를 이용한 효능 판단
- 조합 매핑의 부분 일치 점수
- 임상적 효과·안전성 진단·효능 보장
- DB 검수 상태나 `runtime_enabled` 값을 코드가 자동 변경하는 기능

해당 범위를 추가할 때는 실제 데이터 근거, 개인정보 전달 범위, 검수 주체와 API 계약을 다시 정의한다.
