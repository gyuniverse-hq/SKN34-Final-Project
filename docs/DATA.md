# 카탈로그 데이터 관리 (데이터 담당자용)

제품, 룩, 매장 데이터를 넣고 고치는 방법입니다. 시드 파일을 직접 편집할 때는 DB 접속 권한이 필요하지 않습니다. 원본 DB에서 시드를 생성하는 스크립트는 원본 DB 읽기 권한이 필요합니다. **서빙 데이터는 Git으로 관리하고, 배포가 DB에 넣습니다.**

## 한눈에 보기

```
backend/api/seed/catalog.json 수정
        ↓ PR (develop 대상)
CI가 형식·무결성 자동 검사  ── 문제가 있으면 PR에서 실패로 표시
        ↓ 병합
GitHub Actions(dev-data)가 Supabase에 교체 → 챗봇 DB(AuraDB)에 복사
        ↓
앱(dev 서버)과 Supabase 대시보드에서 확인
```

### 올리브영 v29 원본에서 상품 카탈로그 만들기

- `public.oy_catalog_category_rule`의 21개 표준 카테고리별로 `requires_texture`와 `requires_color`를 관리합니다. 초기값은 AR 담당 팀원과 2026-10-30에 합의한 기준이며, `0010_oy_catalog_category_rules.py` 마이그레이션에 들어 있습니다. 원본 `raw_oy_category`의 카테고리명과 표준 카테고리는 일대일이 아니므로 별도 규칙 표를 사용합니다.
- 범위 밖 상품, 필수 제형이 없는 상품, 그리고 색상 필수 카테고리에서 호수 옵션 중 색상 HEX가 하나라도 없는 상품을 제외합니다. 원본 또는 규칙이 바뀌면 결과 수를 다시 검증해야 합니다.
- `scripts/data/oliveyoung/build_catalog.py`는 원본 DB를 **읽기만** 하고, 현재 시드의 올리브영 상품만 교체한 로컬 검토 파일을 만듭니다. 기존 비올리브영 상품·룩·매장은 보존합니다. v29에서 확인된 홀리카홀리카 단독 구성품 옵션 4개는 카탈로그 호수에서만 제외하며 raw 원본은 보존합니다. 실행 위치는 `backend/api`입니다.

```bash
uv run python ../../scripts/data/oliveyoung/build_catalog.py --expect-source 2512 --output ../../tmp/catalog-v29-review.json
```

상품별 대표 썸네일 URL만 `products.image_url`에 넣습니다. 옵션·색상칩·상세 설명 이미지는 앱 카탈로그에 넣지 않으며 이미지 파일 자체도 저장하지 않습니다. 리뷰 원문과 검수되지 않은 주요 성분·피부 효능 태그도 제외합니다. 추출한 색은 `measureMethod: estimated`와 추출 출처·신뢰도를 함께 보관합니다. 실제 발색 측정값으로 취급하지 않으며 AR 사용 전 출처와 적합성을 검토합니다. 출처 활용 범위를 확인한 뒤 검토 파일을 `backend/api/seed/catalog.json`에 반영하고 PR을 올립니다. 시드가 교체 적재되면 `raw_oy_product.is_in_catalog`도 같은 트랜잭션에서 갱신됩니다.

## 1. 파일 형식

`backend/api/seed/catalog.json` 하나에 세 목록이 들어갑니다. 각 항목의 모양은 앱의 [`types/index.ts`](../types/index.ts)에 있는 `Product`, `CelebLook`, `Store`와 같습니다.

```json
{
  "products": [
    {
      "id": "romand-juicy-tint",
      "brand": "rom&nd",
      "name": "Juicy Lasting Tint",
      "nameKo": "쥬시 래스팅 틴트",
      "category": "lip",
      "makeupZone": "lip",
      "texture": "glossy",
      "priceKRW": 13000,
      "volume": "5.5g",
      "shades": [{ "id": "06", "name": "06 Figfig", "hex": "#B5555E" }],
      "description": "Glassy lip tint",
      "keyIngredients": ["Shea Butter"],
      "tags": ["bestseller"],
      "imageUrl": "https://…",
      "searchKeyword": "롬앤 쥬시 래스팅 틴트"
    }
  ],
  "looks": [],
  "stores": []
}
```

| 항목 | 규칙 |
| --- | --- |
| `id` | 영어 소문자와 `-`만. 한 번 정하면 바꾸지 않습니다(장바구니와 룩이 이 값을 가리킴) |
| `category` | `lip`, `cheek`, `eye`, `base`, `skincare`, `suncare` 중 하나 |
| `makeupZone` | AR로 발라 볼 수 있는 제품만 `lip`, `blush`, `eyeshadow`. 아니면 `null` |
| `texture` | `matte`, `velvet`, `glossy`, `satin`, `sheer`, `cream`, `shimmer` 중 하나. 제형 미확인 상품은 `null`; AR 체험 상품은 제형이 있어야 합니다 |
| `shades[].hex` | `#` + 16진수 6자리 (예: `#B5555E`) |
| `searchKeyword` | 네이버 쇼핑에서 이 제품이 잘 찾아지는 한국어 검색어 (판매처·이미지 검색에 씀) |
| `imageUrl` | `raw_oy_image`에서 상품별 대표 `thumbnail` URL을 사용합니다. 이미지 파일 자체는 저장하지 않으며 URL이 없거나 로드에 실패하면 앱이 중립 이미지를 보여 줍니다 |
| `tags` (피부 고민) | 앱의 피부 고민 필터는 아래 케어 태그로 제품을 찾습니다. 해당하는 제품에만 붙이고, 효능을 단정하는 태그는 만들지 않습니다 |

| 피부 고민 코드 | 제품 태그 |
| --- | --- |
| `dryness` | `hydrating` |
| `oiliness` | `oil-control` |
| `sensitivity` | `soothing` |
| `blemish` | `blemish-care` |
| `pores` | `pore-care` |
| `pigmentation` | `brightening` |
| `wrinkles` | `firming` |

대응표는 `backend/api/app/services/catalog_service.py`의 `CONCERN_TAGS` 한 곳에만 있습니다. 바꿀 때는 이 표도 함께 고칩니다.
| 매장 `lat`, `lng` | 한국 안의 좌표 (위도 33~39, 경도 124~132) |

## 2. 자동으로 걸러지는 오류

PR을 올리면 CI의 `backend` 검사가 아래를 확인합니다. 하나라도 걸리면 PR에 실패로 표시되고 병합할 수 없습니다.

- 필드 누락, 잘못된 카테고리·질감 값, 잘못된 색상 코드
- 같은 `id` 중복 (제품, 룩, 매장, 한 제품 안의 셰이드)
- 한국어 이름이 비었거나 가격이 0원 이하
- AR 체험 제품(`makeupZone`이 있는 제품)에 셰이드가 없음
- AR 체험 제품에 제형이 없음
- 룩이 존재하지 않는 제품이나 셰이드를 가리킴
- 매장 좌표가 한국 밖

PR 전에 내 PC에서 미리 확인하려면 다음을 실행합니다. Python 도구 `uv`가 필요합니다.

```bash
cd backend/api
uv run pytest tests/test_seed_catalog.py
```

## 3. 반영 확인

- **진행 상황**: GitHub → Actions → `dev-data` 실행 결과가 초록색이면 반영된 것입니다. 빨간색이면 로그에 이유가 나옵니다.
- **앱**: 병합 후 몇 분 뒤 dev 서버를 쓰는 앱에서 보입니다.
- **Supabase 대시보드**: Table Editor의 `products`, `shades`, `looks`, `look_items`, `stores` 표에서 볼 수 있습니다.
- **챗봇**: 같은 워크플로가 Supabase에 넣은 뒤 바로 챗봇 DB로 복사하고, 그 뒤로도 12시간마다 다시 맞춥니다.
- 다시 돌리고 싶으면 Actions에서 지난 `dev-data` 실행을 열고 **Re-run all jobs**를 누릅니다. `main`에 첫 병합이 된 뒤부터는 Actions → `dev-data` → **Run workflow**(Branch: `develop`)도 쓸 수 있습니다.

## 3-1. 로컬 시연 데이터

`seed/catalog.json`이 비어 있는 동안 화면을 확인하려면, 내 PC의 로컬 DB에만 가상 카탈로그를 넣습니다. 브랜드는 모두 `VISHUE Demo`이고 실제 제품이 아닙니다.

```bash
cd backend/api
uv run python -m app.jobs.seed_catalog fixtures/demo_catalog.json
```

`fixtures/`는 `dev-data` 워크플로가 읽지 않으므로 dev·운영 DB에는 들어가지 않습니다. 실데이터를 넣으면 같은 명령에 `seed/catalog.json`을 쓰면 되고, 화면 코드는 바꾸지 않습니다.

## 4. 하지 말 것

- **Supabase 화면에서 표를 직접 고치지 않습니다.** 다음에 시드가 돌 때 Git 파일 내용으로 다시 덮어써지고, 그사이에는 검사와 챗봇 복사도 일어나지 않습니다.
- `auth`로 시작하는 표는 로그인 회원 정보입니다. 보기만 하고 건드리지 않습니다.
- 운영(prod) DB에는 Git 병합만으로 데이터가 들어가지 않습니다. 운영 반영은 백엔드 담당자와 일정을 맞춰 진행합니다.

## 5. 크롤링 데이터

크롤러가 위 형식의 JSON을 만들어 주면 같은 흐름으로 들어갑니다. 크롤러는 사이트 이용약관과 `robots.txt`를 지키고, 요청 사이에 간격을 둡니다. 데이터가 커져서 파일 하나로 관리하기 어려워지면 백엔드 담당자와 가져오기 방식을 따로 정합니다.

## 6. 피부 분석·설문 기반 추천 v1

`POST /api/recommendations/skin`은 기존 `products`의 케어 태그를 사용하므로 새 DB 테이블이나
학습 모델이 필요하지 않습니다. 실제 상품 적재 전에도 가짜 저장소로 API·순위·빈 결과를 검증합니다.

- 입력 흐름: 저장된 피부 분석·설문 → 기기에서 고민 코드 제안 → 사용자가 확인·수정 → 추천 요청.
- 여드름 이진 결과는 `blemish`, 모공·색소침착·주름은 기존 화면의 최고 부위 등급 3 이상일 때
  각각 `pores`, `pigmentation`, `wrinkles`를 제안합니다. 등급은 실험값이며 가중치로 사용하지 않습니다.
- 설문의 당김·유분·민감도가 2이면 각각 `dryness`, `oiliness`, `sensitivity`를 제안합니다.
  0·1·`unknown`은 자동 제안하지 않으며 사용자가 추가·제거할 수 있습니다. 수분 추론값은 사용하지 않습니다.
- 요청은 `{ "concerns": ["dryness", "pores"], "limit": 8 }`입니다. `limit`은 1–20이며 기본값은 8입니다.
  사진·원본 등급·설문 답변·분석 메타데이터를 보내지 않으며 추가 필드는 오류로 거절합니다.
- 후보는 `skincare`, `suncare`만 사용합니다. 위 고민–태그 대응표로 일치한 **고민 수**를 계산하고
  내림차순, 동점은 상품 ID 오름차순으로 정렬합니다. 중복 태그·고민은 점수를 늘리지 않습니다.
- 응답은 `strategyVersion: "skin-concern-v1"`, `concerns`, `status`, `matches`를 포함합니다.
  각 match는 `product`, `matchedConcerns`, `score`를 포함합니다. 점수는 효능·확률·중증도가 아닙니다.
- 상태는 `ok`, `no_concerns`, `empty_catalog`, `no_matches`입니다. 무관한 상품으로 빈 결과를 채우지 않습니다.
  추천 응답은 `Cache-Control: no-store`이며 DB에 개인 입력·추천 이력을 저장하지 않습니다.
- 이미지·가격 외부 API와 LLM은 호출하지 않습니다. 상품의 `imageUrl`을 사용하고 없으면 기존 플레이스홀더를 표시합니다.

실데이터 연결 시 안정적인 상품 ID·카테고리·케어 태그를 우선 검수합니다. 원본 수집 테이블을 API가
직접 읽도록 바꾸지 않습니다. 실제 제품 적합성·태그 정확도·추천 품질은 별도의 검증이 필요합니다.

DB 없이 확인: `backend/api`에서 `uv run pytest tests/test_recommendations.py`.
로컬 화면 시연은 위 데모 카탈로그 적재 방법을 사용하며, 실데이터 시드에 가상 상품을 섞지 않습니다.

## Supabase 권한

프로젝트 관리자가 Supabase → Organization → Team에서 초대하고, 데이터 담당자에게는 **Developer** 역할을 줍니다(표 보기와 SQL 실행 가능, 결제·팀원 관리는 불가). 위 규칙대로 대시보드는 확인용으로만 씁니다.
