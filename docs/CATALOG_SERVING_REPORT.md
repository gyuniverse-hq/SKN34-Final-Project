# Catalog Serving Report — 스킨케어 적재

앱 서빙 `products` 테이블에 올리브영 스킨케어·선케어를 적재한 결과와 측정값입니다.
`docs/DATA.md` 의 카탈로그 규칙과 `scripts/data/oliveyoung/README.md` 의 (6)~(10)단계에
해당합니다.

- 측정일: 2026-11-03
- 대상: 데이터 담당 로컬 PostgreSQL `vishue_v29`, 공용 Supabase `products`
- 재현: `backend/api` 에서 `uv run python -m app.jobs.export_oy_catalog`

## 1. 적재 결과

| 카테고리 | 이전 | 현재 | 증감 |
| --- | ---: | ---: | ---: |
| `skincare` | 0 | **4,919** | +4,919 |
| `suncare` | 0 | **786** | +786 |
| `lip` | 916 | 908 | -8 |
| `eye` | 559 | 559 | 0 |
| `base` | 321 | 319 | -2 |
| `cheek` | 199 | 197 | -2 |
| 합계 | 1,995 | **7,688** | +5,693 |

`shades` 10,181 -> 10,160. AR 시착 가능 상품 1,308건. 가격 미보유 탈락 0건, 미매핑 탈락 0건.

적재 전 공용 `products` 는 1,995건으로 `seed/catalog.json` 과 정확히 일치했습니다. 공용은
커밋된 seed 를 단일 출처로 적재된 상태입니다.

## 2. 기존 상품 회귀 검사 — 없음

유지되는 1,983건을 id 단위로 대조했습니다.

| 필드 | 변경 건수 |
| --- | ---: |
| `imageUrl` | 3 |
| `category`, `makeupZone`, `texture`, `priceKRW`, `tags`, `name`, `brand`, `volume` | **0** |

메이크업 1,983건 중 `texture` 가 `null` 인 것은 0건입니다. 스킨케어·선케어는 5,705건 중
5,704건이 `null` 입니다. 마이그레이션 0010 이 `products.texture` 를 nullable 로 바꾼 뒤
제형 규칙이 없는 카테고리에 제형을 만들어 넣지 않기로 한 것에 따랐습니다.

## 3. 사라진 상품 12건

`raw_oy_product` 에 해당 `goods_no` 가 **존재하지 않습니다.** 단종 표시(`delisted_at`)가
아니라 수집본 자체에 없습니다. 현재 `seed/catalog.json` 을 만든 CSV 스냅샷과 지금 DB가
같은 수집본이 아니기 때문이며, DB 로는 사라진 사유를 확인할 수 없습니다.

| 카테고리 | goods_no | 이름 |
| --- | --- | --- |
| base | A000000131582 | 홀리카홀리카 하드커버 글로우 쿠션EX리필기획 |
| base | A000000131644 | 홀리카홀리카 하드커버 퍼펙 쿠션 단품 (태닝에디션) 06 아몬드 |
| lip | A000000144360 | 쌍빠 어딕트 에센셜 더블링 립밤 3종 택1 |
| lip | A000000183569 | 스킨푸드 아보카도 & 올리브 립 밤 12g |
| cheek | A000000224847 | 어퓨 실리콘 립 앤 치크 브러쉬 |
| lip | A000000253430 | 데이지크 프루티 립잼 4g 11 캐슈넛잼 |
| lip | A000000260009 | 어퓨 과즙팡 젤리 틴트 3.5g 01 피치젤리 |
| lip | A000000269086 | 어퓨 과즙팡 틴트 3.5g PK01 플라이베리 (온) |
| cheek | A000000269121 | 퓌 포켓 치크팔레트 CP03 포멜로&피치 9.6g |
| lip | A000001003682 | 에크멀 논 섹션 글로이 틴트 |
| lip | A000001003692 | 에크멀 익스트림 립 글라시 |
| lip | A000001003694 | 에크멀 블러리 립앤치크 4.5g 102 덜셋 드림 |

`어퓨 실리콘 립 앤 치크 브러쉬` 는 도구이고 화장품이 아닙니다.

## 4. FK 안전성 — 확인됨

`replace_catalog()` 는 한 트랜잭션에서 `skincare_serving`, `look_items`, `looks`,
`shades`, `products`, `stores` 를 지우고 다시 넣습니다. `look_products.product_id` 는
`products.id` 를 가리키지만 **삭제 목록에 없고 `ondelete` 도 없습니다.** 사라지는 상품을
참조하는 행이 있으면 적재가 FK 위반으로 실패합니다.

| 대상 | `look_products` 의 `product_id` 참조 | 깨지는 참조 |
| --- | ---: | ---: |
| 로컬 | 0 | 0 |
| 공용 | 0 | 0 |

현재는 양쪽 모두 참조가 없어 안전합니다. 아이돌룩 상품 매핑이 적재된 뒤에는 카탈로그를
교체하기 전에 이 검사가 다시 필요합니다.

## 5. 서빙 동작 확인

`/api/recommendations` 는 `skincare`/`suncare` 상품을 케어 태그로만 매칭합니다.

| 피부 고민 | 태그 | 매칭 상품 |
| --- | --- | ---: |
| `dryness` | `hydrating` | 945 |
| `sensitivity` | `soothing` | 832 |
| `wrinkles` | `firming` | 554 |
| `pigmentation` | `brightening` | 522 |
| `pores` | `pore-care` | 398 |
| `blemish` | `blemish-care` | 257 |
| `oiliness` | `oil-control` | 253 |

7개 고민 전부 결과가 나옵니다. 검색은 `토너` 406건, `세럼` 737건, `선크림` 315건,
`클렌징` 630건입니다.

## 6. 케어 태그 커버리지와 오탐 측정

케어 상품 5,705건 중 태그 1개 이상 보유가 **3,024건(53.0%)** 입니다. 2,681건은 태그가
없어 고민 추천에 포함되지 않습니다. 태그는 `CARE_KEYWORDS` 의 상품명 키워드로만 붙습니다.

측정된 오탐입니다. 아래는 사실 기록이며 수정 방향은 정해지지 않았습니다.

| 키워드 | 태그 | 해당 건수 | 확인된 오탐 |
| --- | --- | ---: | --- |
| `피지` | `oil-control` | 217 | `피지오겔`(Physiogel)은 건성·민감성 브랜드인데 부분일치로 `oil-control` 이 붙습니다 |
| `콜라겐` | `firming` | `firming` 554건에 포함 | `메디필 그린 시카 콜라겐 클리어 젤 클렌저`, `콜라겐 미스트` 등 씻어내는 클렌저에 탄력 태그가 붙습니다 |
| `톤업` | `brightening` | 235 | 톤업 선크림은 물리적 발색이며 미백 기능성과 다릅니다 |
| `지성` | `oil-control` | 17 | `한스킨 클렌징오일 (민감성/건성/지성)` 처럼 피부타입 3종 묶음에 지성 태그가 붙습니다 |
| `pore` | `pore-care` | **0** | 영문 키워드가 한 건도 매칭되지 않습니다 |
| `firm` | `firming` | **0** | 영문 키워드가 한 건도 매칭되지 않습니다 |

`CARE_KEYWORDS` 와 `CONCERN_TAGS` 대응표는 `docs/DATA.md` 에 있고 코드에서는
`app/schemas/oy_catalog.py` 와 `app/services/catalog_service.py` 한 곳씩에 있습니다.

### 기능성 고시 값을 태그 출처로 쓸 경우

`raw_oy_skincare_attr.functional_types` 는 식약처 기능성 신고 항목입니다. 보강 효과를
측정했습니다.

| 안 | 태그 보유 | 순증 |
| --- | ---: | ---: |
| 현재 (상품명 키워드만) | 3,024 / 5,705 (53.0%) | — |
| `functional_types` 추가, 아토피 제외 | 3,060 / 5,705 (53.6%) | +36 |
| `functional_types` 추가, 아토피 포함 | 3,093 / 5,705 (54.2%) | +69 |

| 고시값 | 보유 | 이미 태그 있음 | 순증 |
| --- | ---: | ---: | ---: |
| 자외선차단 | 648 | 356 | 0 (7개 고민축에 대응값 없음) |
| 미백 | 165 | 147 | 18 |
| 피부장벽(아토피) | 102 | 69 | 33 |
| 주름개선 | 89 | 62 | 27 |
| 여드름완화 | 37 | 34 | 3 |

순증이 작은 주된 이유는 **`is_functional = 'Y'` 인데 `functional_types` 가 빈 값인 것이
1,978건** 이기 때문입니다. 기능성 화장품인 것은 수집되었으나 어떤 기능인지가 수집되지
않았습니다. 수집기 쪽 공백입니다.

`피부장벽(아토피)` 102건은 질환명이며, `CARE_KEYWORDS` 주석의 `Not medical claims` 와
충돌합니다.

## 7. 분류 체계가 두 개입니다

같은 원본에서 서빙 카탈로그를 만드는 경로가 두 개이고 분류 기준이 다릅니다.

| | `app.jobs.export_oy_catalog` | `scripts/data/oliveyoung/build_catalog.py` |
| --- | --- | --- |
| 분류 기준 | `raw_oy_category.category_name` (사이트 잎 이름) | `raw_oy_product.std_category_code` |
| 매핑표 | `ZONE_BY_CATEGORY` 14종 | `CATEGORY` 22종 + `oy_catalog_category_rule` |
| 메이크업 범위 | 12종 | 22종 |
| 스킨케어 | 지원 | 매핑표에 없음 |
| 쿠션 AR zone | `foundation` | `null` |
| shade 메타 | 없음 | `measureMethod`, `colorSource`, `colorConfidence` |

`scripts/data/oliveyoung/README.md` 의 (6)단계는 `build_catalog.py` 를 가리키지만, 커밋된
`seed/catalog.json` 의 shade 에는 `measureMethod` 등이 없어 `export_oy_catalog` 계열로
만들어진 것으로 보입니다. 이번 적재도 `export_oy_catalog` 로 했습니다.

측정된 차이입니다.

- `build_catalog.py` 의 매핑표에만 있는 메이크업 **527건**: 프라이머/베이스 145,
  파우더/팩트 93, 하이라이터 71, 컨실러 70, BB/CC 67, 쉐이딩 41, 메이크업 픽서 39,
  컬러립밤 1. 공용 `products` 에도 원래 없습니다.
- 로컬 `products` 는 적재 전 2,051건이었고 `base` 698 = `ZONE` 경로 319 + 위 4종(145+93+71+70)
  입니다. 로컬은 `build_catalog.py` 로 적재된 상태였습니다.
- 마이그레이션 0010 의 `oy_catalog_category_rule` 에는 메이크업 21종만 등록되어 있습니다.
  0010 주석은 `Agreed with the AR team on 2026-10-30` 입니다.
- 케어 상품 5,705건은 **전부 `std_category_code` 가 채워져 있습니다** (비어 있음 0건).
  코드는 `에센스` 937, `크림` 728, `시트팩` 595, `선블록` 573, `클렌징폼` 543,
  `스킨/토너` 373 등 케어 전용으로 정리되어 있습니다.
- 두 체계가 어긋나는 상품: `바디클렌저` 2건(얼굴 스킨케어가 아님), `BB/CC`·`메이크업 픽서`·
  `마스카라`·`프라이머/베이스` 각 1건이 이번 적재에서 케어로 분류되었습니다. 합 6건.
- `선블록` 573 과 이번 적재의 선케어 집계 `선크림` 578 은 5건 차이입니다.

## 8. 미결 쟁점

1. **케어 태그 오탐 수정 범위.** `CARE_KEYWORDS` 는 `docs/DATA.md` 에 근거를 둔 공용
   로직이며 메이크업 쪽 태그에도 영향이 있습니다. `톤업` 을 미백으로 볼지는 기획 판단이
   필요합니다.
2. **기능성 고시 값을 태그 출처로 쓸지.** 순증 36~69건이고 아토피 포함 여부가 걸립니다.
3. **`is_functional = 'Y'` 인데 기능 종류가 없는 1,978건** 을 재수집할지.
4. **분류 체계 단일화.** 어느 경로를 정본으로 할지, 메이크업 527건을 서빙에 넣을지,
   쿠션 AR zone 을 `foundation` 과 `null` 중 무엇으로 할지. 아이돌룩 AR 쪽과 함께
   정해야 합니다.
5. **카탈로그 교체 전 FK 검사 절차.** `look_products` 에 상품 매핑이 적재된 뒤에는
   `replace_catalog()` 가 FK 위반으로 실패할 수 있습니다.
6. **사라진 12건** 을 서빙에서 빼도 되는지. DB 로는 사유를 확인할 수 없습니다.
