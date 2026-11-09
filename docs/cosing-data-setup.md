# CosIng 추천 데이터 수집·마이그레이션·적재 가이드

로컬 개발 환경에서 CosIng 기능 태그를 수집하거나 전달받은 CSV로 추천을 재현하는 절차다. 이미 검수된 CSV 두 개를 받았다면 수집은 건너뛰고 마이그레이션부터 진행한다.

```text
식약처 성분 스냅샷 → CosIng 조회 → CSV 2개
                                      ↓
로컬 PostgreSQL → develop 기준 Alembic 0018 → CSV 검증·적재 → 추천 발행 → API 확인
```

## 준비물과 전달 파일

- `uv`, Docker, 로컬 PostgreSQL이 필요하다. 아래 PowerShell 7 명령은 저장소 루트에서 `Set-Location backend/api`를 실행한 뒤 입력한다. 이 디렉터리에서 `uv sync --group data`로 수집기에 필요한 `requests`까지 설치한다.
- 수집 대상은 `raw_mfds_ingredient`의 현재 행이다. 다른 로컬 DB에 적재할 경우에도 수집 당시와 같은 식약처 성분 집합, ID, 한글명, 영문명, CAS 값이 필요하다.
- 제품 추천 발행에는 제품·옵션·옵션별 성분·판매 정보와 `oy_mfds_ingredient_map` 연결도 필요하다. 로컬 카탈로그가 없는 환경은 팀의 DB 구축 절차로 먼저 준비한다.

| 파일 | 전달 방법 | 역할 |
| --- | --- | --- |
| `scripts/data/recommendation/cosing_collect.py` | Git | 식약처 성분 조회, CosIng 검색, CSV 내보내기 |
| `scripts/data/recommendation/cosing_query_compare.py` | Git | 수집기가 쓰는 검색 주소, 요청 생성과 이름 비교 함수 제공 |
| `scripts/data/recommendation/load_cosing.py` | Git | CSV 검증, 적재 미리보기 및 적용 |
| `backend/api/alembic/versions/`와 `backend/api/seed/recommendation_v03/identity.json` | Git | develop 마이그레이션 이력 + CosIng `0018`, 발행 출처 정책 |
| `cosing_ingredients.csv`, `cosing_function_tags.csv` | 같은 버전의 검수본을 별도 전달 | 성분별 조회 결과 및 기능 태그별 고민 분류 |

수집 CSV, 체크포인트, 보고서, 로컬 덤프, 발행용 JSON은 `tmp/` 등 Git에 올리지 않는 위치에 보관한다.

## 1. CosIng 데이터 수집

수집기는 `docker exec`와 `psql`로 로컬 컨테이너의 식약처 데이터를 읽는다. 기본 컨테이너는 `vishue-postgres-1`, DB는 `vishue_db`, 사용자는 `vishue`다. 수집 SQL은 읽기 전용이다. CosIng 검색 API 키가 필요하며, 사용 조건과 요청 제한을 확인한 뒤 실행한다.

```powershell
$env:COSING_SEARCH_API_KEY = Read-Host 'CosIng 검색 API 키' -MaskInput
uv run --group data python ../../scripts/data/recommendation/cosing_collect.py --output-dir ../../tmp/cosing --delay 2
```

- 대상 환경이 다르면 `--container`, `--database`, `--user`를 지정한다. `--delay`는 최소 2초다.
- 첫 실행에는 새 출력 디렉터리를 지정한다. 재개할 때는 같은 `--output-dir`을 사용한다. 기존 `cosing_checkpoint.sqlite3`에서 미처리 성분부터 이어서 수집한다. 식약처 스냅샷을 바꿔 다시 수집하려면 새 디렉터리를 사용한다.
- `401`, `403`, `429` 응답에서는 수집을 멈춘다. 원인을 확인하고 해소한 뒤 재개한다. 수집 도중에도 CSV가 생성되므로 `cosing_report.md`에서 미처리 건이 남지 않았는지 확인한다.
- 조회는 성분명과 출처, 단일 후보 여부를 확인한다. 기능 태그가 있는 `accepted` 결과가 성분–기능 연결에 사용된다. 식물 학명에 붙은 괄호 속 일반명으로 일치하지 않을 때는 제한적으로 정규화해 재조회한다.

### CSV 검수

- `cosing_ingredients.csv`에는 전체 성분의 조회 상태와 기능 목록이 들어간다. 미일치 행도 포함해야 전체 식약처 성분 집합을 검증할 수 있다.
- `cosing_function_tags.csv`는 `functionName`, `ingredient_count`와 다음 7개 고민 컬럼을 사용한다. 한 태그가 여러 고민에 해당하면 여러 컬럼에 `1`을 넣는다.

| CSV 컬럼 | DB 고민 코드 |
| --- | --- |
| 수분 | `dryness` |
| 유분 | `oiliness` |
| 민감진정 케어 | `sensitivity` |
| 톤잡티 케어 | `pigmentation` |
| 주름 케어 | `wrinkles` |
| 트러블 케어 | `blemish` |
| 모공 케어 | `pores` |

수집기가 기본 분류를 채운다. 분류를 조정할 때는 고민 컬럼만 `0` 또는 `1`로 검수하고 두 CSV를 한 쌍으로 보관한다. 같은 출력 디렉터리에서 내보낼 때는 기존 태그의 검수값이 유지된다.

## 2. 로컬 DB 마이그레이션

**개발 중 사용한 별도 `0019` DB에는 이 명령을 실행하지 않는다.** 과거 브랜치의
`0015`~`0018`과 develop의 같은 번호는 내용이 다르다. 파일명 변경이나 `alembic stamp 0018`은
스키마를 변환하지 않는다. 기존 로컬 DB·덤프는 보존하고 develop 기준의 별도 DB에서 아래 절차를
진행한다. 기존 DB 전환은 실제 스키마와 데이터를 대조한 별도 작업으로 처리한다.

`DATABASE_URL`을 대상 로컬 DB로 설정한다. 아래는 기본 Docker 호스트 포트 기준 예시다. 비밀번호에는 실제 로컬 값을 URL 인코딩해 사용하고 키와 접속 문자열은 Git에 올리지 않는다.

```powershell
$env:DATABASE_URL = 'postgresql+asyncpg://vishue:<URL_ENCODED_PASSWORD>@127.0.0.1:15432/vishue_db'
uv run alembic current
uv run alembic heads
```

| 리비전 | 역할 |
| --- | --- |
| `0015` | develop의 YouTube 상품 테이블 |
| `0016` | develop의 검증된 추천 규칙 스키마 및 기존 데이터 보관소 |
| `0017` | develop의 룩 AR geometry 컬럼 |
| `0018` | `cosing_ingredient_lookup`, `cosing_function`, `ingredient_function`, `function_concern` 생성 및 누락된 7개 고민 코드 보충 |

신규 DB 또는 develop 이력의 DB에서 다음을 실행한다. 이미 develop `0017`이면 새 `0018`만 적용된다.
`0018`은 기존 고민 문구·연구 매핑·발행본을 교체하지 않는다. `0016` 이전 DB라면 develop의
`0016` 자체가 기존 연구 데이터를 보관소로 옮기고 이전 발행본을 비우므로 전체 백업 후 적용한다.

```powershell
uv run alembic upgrade 0018
uv run alembic current
```

신규 `0018`에는 연구 매핑 교체 옵션이나 연구 데이터 시드가 필요하지 않다. CosIng 적재에는
대상 DB의 `raw_mfds_ingredient`와 CSV의 성분 ID·이름이 일치해야 하며, 추천 발행에는 기존
올리브영 상품·옵션·성분 연결 데이터도 필요하다. 스키마만 생성하면 원천 데이터가 채워지는 것은 아니다.
`0018` downgrade는 CosIng 테이블 4개만 삭제하고 공유 고민 코드는 보존한다.
현재 리비전이 `0018`임을 확인한 뒤 적재로 넘어간다.

## 3. CSV 미리보기와 적재

두 CSV를 `../../tmp/cosing`에 넣거나 `--input-dir`을 실제 경로로 바꾼다. 적재기는 로컬 PostgreSQL 주소만 허용한다.

```powershell
uv run python ../../scripts/data/recommendation/load_cosing.py --input-dir ../../tmp/cosing
uv run python ../../scripts/data/recommendation/load_cosing.py --input-dir ../../tmp/cosing --apply
```

첫 명령에서 기능 태그 수, 조회 결과 수, 성분–기능 연결 수, 기능–고민 연결 수와 대상 테이블의 기존 행 수를 확인한다. 그 결과가 의도와 맞고 네 대상 테이블이 모두 비어 있으면 두 번째 명령을 실행한다. 적재 성공 시 `Import committed`가 출력된다.

식약처 행 불일치, 다른 버전의 CSV 혼용, 잘못된 고민 컬럼 값이 있으면 오류가 난다. 대상 테이블이 이미 채워져 있으면 기존 행을 보존하고 종료한다. 기존 적재본을 갱신해야 할 경우에는 먼저 교체 범위를 확인한다.

## 4. 추천 발행과 확인

로컬 API의 자동 갱신이 켜져 있으면 다음 주기에 추천 발행본이 갱신된다. 수동으로 검토하고 발행할 때는 같은 DB 설정을 사용해 아래 순서로 실행한다. `../../tmp`가 없다면 먼저 만든다.

```powershell
uv run python -m app.jobs.review_skincare
uv run python ../../scripts/data/oliveyoung/build_skincare.py skincare_manifest.json ../../tmp/skincare-serving.json
uv run python -m app.jobs.publish_skincare ../../tmp/skincare-serving.json
uv run python -m app.jobs.publish_skincare ../../tmp/skincare-serving.json --apply
```

`review_skincare`에서 고민별 후보를 확인한다. `build_skincare.py`는 검토용 JSON을 만들고, `publish_skincare`는 `--apply`를 붙였을 때 현재 데이터와 번들이 일치하면 발행한다. 번들이 오래되었다는 오류가 나면 다시 만든 뒤 검토한다.

기본 로컬 게이트웨이 포트에서 다음 예시 요청으로 확인한다. 포트를 변경했다면 주소를 맞춘다.

```powershell
$body = @{ primaryGoal = 'pores' } | ConvertTo-Json -Compress
$result = Invoke-RestMethod -Method Post `
  -Uri 'http://localhost:8080/api/recommendations/skincare/v2' `
  -ContentType 'application/json' -Body $body
$result.dataVersion
$result.coverage
$result.byConcern.pores | ForEach-Object { $_.reasons.evidenceSources }
```

발행 버전이 있고 해당 고민에 후보가 있으면 `coverage`가 `ok`이며 추천 이유의 출처에 `cosing_function`이 나온다. 후보가 없다면 `review_skincare` 결과와 식약처 성분–판매 옵션 연결을 확인한다.
