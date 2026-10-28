# 카탈로그 데이터 관리 (데이터 담당자용)

제품, 룩, 매장 데이터를 넣고 고치는 방법입니다. DB 비밀번호나 서버 접속 권한은 필요 없습니다. **데이터는 Git으로 관리하고, 배포가 DB에 넣습니다.**

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
| `texture` | `matte`, `velvet`, `glossy`, `satin`, `sheer`, `cream`, `shimmer` 중 하나 |
| `shades[].hex` | `#` + 16진수 6자리 (예: `#B5555E`) |
| `searchKeyword` | 네이버 쇼핑에서 이 제품이 잘 찾아지는 한국어 검색어 (판매처·이미지 검색에 씀) |
| `imageUrl` | 원본 이미지 주소. 이미지 파일을 복사해 오지 않습니다(저작권). 비어 있거나 로드에 실패하면 앱이 중립 플레이스홀더를 보여 줍니다 |
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

## Supabase 권한

프로젝트 관리자가 Supabase → Organization → Team에서 초대하고, 데이터 담당자에게는 **Developer** 역할을 줍니다(표 보기와 SQL 실행 가능, 결제·팀원 관리는 불가). 위 규칙대로 대시보드는 확인용으로만 씁니다.
