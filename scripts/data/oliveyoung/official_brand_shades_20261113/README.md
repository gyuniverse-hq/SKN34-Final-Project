# 공식몰 립 제품 호수 보강 자료 (2026-11-13)

맥 립 제품 2종과 에스티로더 립 제품 1종의 공식몰 호수 57개를 정리한 스냅샷이다.
앱에는 기존 호수 22개를 유지하고 35개를 추가했다. 공식몰 호수 중 36개는
올리브영 원본 옵션과 연결되고 21개는 공식몰 전용이다.

| 파일 | 내용 |
| --- | --- |
| `official_products.csv` | 공식 상품과 기존 올영·앱 상품 연결 |
| `official_options.csv` | 공식몰 호수명과 공식 SKU |
| `official_option_colors.csv` | 공식몰 HEX와 최종 채택 HEX, 출처 |
| `official_product_textures.csv` | 제품별 제형과 판단 근거 |
| `serving_shades_preview.csv` | 기존 앱 호수 보존 및 추가 계획 |
| `serving_products_preview.csv` | 앱 상품 제형·부위 보강 계획 |

570 시그니처 무브 `#BA634F`, 946 비즈니스 캐주얼 `#B83A48`,
185 멜티드 메이플 `#AC4B4A`는 사용자가 검수한 컬러칩의 최종 HEX다.
이미지 파일·바이너리·파일 해시는 이 스냅샷과 최종 DB에 저장하지 않는다.
`selected_source=user_reviewed_chip`은 이 세 값의 결정 근거를 나타낸다.

마이그레이션 `0021`은 기존 4개 테이블을 생성하고, `0022`는
상품·호수 2개 테이블로 데이터를 합쳐 PNG 바이너리를 폐기한다.
최종 데이터는 `raw_official_product`(상품·제형)와
`raw_official_product_option`(호수·HEX)에 보관된다.
올리브영 원본 `raw_oy_*`는 수정하지 않는다.

`load_official_brand_shades.py`는 기본 실행 시 읽기 전용 사전 검사를 수행하고
`--apply`에서 두 원본 테이블과 앱 `products`/`shades`를 한 트랜잭션으로
반영한다. 앱 카탈로그를 전체 재적재한 경우에는 이 로더를 다시 실행해야
공식몰 호수가 앱에 유지된다.
