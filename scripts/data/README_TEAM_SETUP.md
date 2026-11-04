# 로컬 DB 구축 안내 (팀원용)

데이터 담당이 준 덤프로 각자 PC 에 같은 DB 를 만드는 절차입니다. 2026-11-04 에
`vishue_db` 를 복제해 실제로 검증한 순서입니다.

공용 Supabase 는 용량 한도에 닿아 더 쓰지 않습니다. 추후에 AWS 한국 리전으로 옮길
때까지 각자 로컬 PostgreSQL 을 쓰고, 데이터가 바뀌면 데이터 담당이 덤프를 다시
공유합니다.

## 미리 필요한 것

| | |
| --- | --- |
| Docker Desktop | 실행 중이어야 합니다 |
| Python 3.12 + `uv` | alembic 과 적재 스크립트 실행용 |
| 덤프 파일 | 데이터 담당이 전달. `vishue_db_YYYYMMDD.dump` (약 19MB) |
| AI-Hub 원본 | **AI-Hub 작업을 하는 사람만.** 각자 본인 계정으로 내려받습니다 |

AI-Hub 원본은 덤프에 **들어 있지 않습니다.** 이용정책에 승인받지 않은 제3자에게
제공하거나 열람하게 할 수 없다는 조항이 있어 팀원 간에 주고받지 않습니다. 테이블
구조는 Git 으로 공유하고 데이터는 각자 받습니다. 자세한 내용은
`docs/AIHUB_DATA_RIGHTS.md` 에 있습니다.

## 빠른 설치

**모든 명령은 저장소 루트에서 실행합니다.**

```powershell
git switch develop
```

```powershell
git pull
```

```powershell
scripts\data\setup_local_db.cmd C:\받은\경로\vishue_db_20261104.dump
```

경로는 본인이 덤프를 받은 위치로 바꿔 주세요. 컨테이너 기동부터 검증까지 7단계가
순서대로 돌고, 마지막에 이런 표가 나오면 성공입니다.

```
        item        | actual | expected | result
--------------------+--------+----------+--------
 products           |   7688 |     7688 | OK
 shades             |  10160 |    10160 | OK
 aihub_skin_concern |     13 |       13 | OK
 aihub_skin_type    |      4 |        4 | OK
 public tables      |     57 |       57 | OK
```

한 줄이라도 `MISMATCH` 면 스크립트가 실패로 끝냅니다. 그때는 아래 "막혔을 때" 를
보고, 안 되면 데이터 담당에게 알려 주세요.

그다음 전체 스택을 올립니다.

```powershell
docker compose -f infra/compose/compose.yaml --env-file .env up -d --build
```

첫 실행은 이미지를 받고 만드느라 몇 분 걸립니다. 자세한 실행 방법은
`docs/DEPLOYMENT.md` 에 있습니다.

## AI-Hub 적재 (해당자만)

AI-Hub 에서 「문제성 피부 메이크업 추천 데이터」(datasetSn 71961)를 본인 계정으로
내려받습니다. 압축을 풀면 `3.개방데이터\1.데이터` 폴더가 생깁니다.

```powershell
cd backend\api
```

```powershell
set DATA=C:\받은\경로\02.문제성 피부 메이크업 추천 데이터\3.개방데이터\1.데이터
```

```powershell
uv run python ..\..\scripts\data\aihub\load_all.py --data-dir "%DATA%"
```

```powershell
uv run python ..\..\scripts\data\aihub\load_all.py --data-dir "%DATA%" --apply
```

`--apply` 없이 먼저 돌려 수치를 확인하고, 맞으면 `--apply` 로 적재합니다. 5단계가
순서대로 돌고 비밀번호는 한 번만 묻습니다. 적재 후 기대값입니다.

| 테이블 | 행 수 |
| --- | ---: |
| `aihub_qa_case_raw` | 9,031 |
| `aihub_qa_case` | 9,031 |
| `aihub_qa_source_link` | 9,181 |
| `aihub_knowledge_document` | 3,108 |
| `aihub_knowledge_document_file` | 6,245 |
| `aihub_ingredient_mention` | 18,062 |
| `aihub_dataset_release` | 1 |

로컬이 아닌 host 를 지정하면 적재 스크립트가 거부합니다. 의도된 동작입니다.

## 수동 설치

`setup_local_db.cmd` 가 하는 일을 한 단계씩 직접 하거나, 중간에서 실패한 지점만
다시 할 때 쓰는 절차입니다. 빠른 설치가 됐으면 읽지 않아도 됩니다.

### 1. 환경 파일

환경 파일은 두 개입니다. 루트 쪽은 compose 가 읽고, `backend/api` 쪽은 alembic 과
스크립트가 읽습니다.

```powershell
copy .env.example .env
```

```powershell
copy backend\api\.env.example backend\api\.env
```

`backend/api/.env` 의 `DATABASE_URL` 이 `...@localhost:15432/vishue_db` 인지 확인합니다.
루트 `.env` 에는 DB 주소가 없고 외부 API 키만 있으니, 담당 영역에 필요한 값만 채우면
됩니다. DB 비밀번호를 기본값(`vishue`) 말고 다른 값으로 쓸 거면 루트 `.env` 에
`POSTGRES_PASSWORD` 를 추가하고 `backend/api/.env` 의 주소에도 같은 값을 넣습니다.

### 2. PostgreSQL 컨테이너만 올리기

```powershell
docker compose -f infra/compose/compose.yaml --env-file .env up -d postgres
```

`postgres` 만 올리는 것이 중요합니다. 전체 스택을 올리면 `migrate` 가 먼저 돌아 빈
DB 에 테이블을 만들어 버리고, 그 뒤 덤프 복원이 "이미 있다" 로 실패합니다.

`vishue_db` 는 컨테이너가 처음 뜰 때 자동으로 만들어집니다. 따로 만들 필요가 없습니다.

### 3. 확장 설치

```powershell
docker compose -f infra/compose/compose.yaml exec postgres psql -P pager=off -U vishue -d vishue_db -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

**건너뛰면 다음 단계가 실패합니다.** `products.search_text` 와
`raw_oy_ingredient.ingredient_name` 에 트라이그램 인덱스가 걸려 있는데 덤프에는 확장
정의가 들어 있지 않아, 확장이 없으면 복원 중 인덱스 생성이 깨집니다. 이미 있으면
그냥 넘어갑니다.

### 4. 덤프 복원

```powershell
docker compose -f infra/compose/compose.yaml cp C:\받은\경로\vishue_db_20261104.dump postgres:/tmp/team.dump
```

```powershell
docker compose -f infra/compose/compose.yaml exec postgres pg_restore -U vishue -d vishue_db --no-owner --no-privileges /tmp/team.dump
```

`--no-owner --no-privileges` 는 덤프를 만든 쪽의 계정 정보를 쓰지 않겠다는 뜻입니다.
검증 때는 아무 메시지 없이 끝났습니다. `FATAL` 이나 `could not` 이 나오면 멈추고
데이터 담당에게 알려 주세요.

### 5. AI-Hub 빈 테이블 만들기

덤프에는 버전 기록이 `0014` 로 들어 있지만 `aihub_*` 테이블은 빠져 있습니다. 그래서
`alembic upgrade head` 만 돌리면 "이미 최신" 이라며 아무것도 하지 않습니다. 기록을
하나 되돌린 뒤 다시 올려야 합니다.

```powershell
cd backend\api
```

```powershell
uv run alembic stamp 0013
```

```powershell
uv run alembic upgrade head
```

```powershell
uv run alembic check
```

`alembic` 은 DB 구조 변경 이력을 번호 순서로 관리하는 도구입니다. `stamp` 는 기록된
번호만 바꾸고 SQL 은 실행하지 않아서, 이미 복원된 테이블을 건드리지 않습니다. 그
다음 `upgrade` 가 `aihub_*` 10개와 분류 축 2종(피부 고민 13종, 피부 타입 4종)을
만듭니다.

`alembic check` 가 `No new upgrade operations detected.` 로 끝나야 합니다.

`alembic downgrade 0013` 은 쓰지 마세요. 없는 테이블을 지우려 해서 실패합니다.

### 6. 검증

```powershell
cd ..\..
```

```powershell
docker compose -f infra/compose/compose.yaml exec -T postgres psql -P pager=off -v ON_ERROR_STOP=1 -U vishue -d vishue_db < scripts\data\verify_local_db.sql
```

빠른 설치와 같은 표가 나오고, 모두 `OK` 여야 합니다. 그 밖의 `aihub_*` 8개는 0건이
정상입니다. 데이터는 위 "AI-Hub 적재" 에서 각자 넣습니다.

## 이미 로컬 환경이 있던 경우

2026-11-04 에 DB 이름이 `vishue` 에서 `vishue_db` 로 바뀌었습니다. 기존 볼륨을 쓰고
있으면 `postgres` 컨테이너의 상태검사가 `vishue_db` 를 찾지 못해 계속 unhealthy 로
남고 `api` 도 뜨지 않습니다. 이름만 바꾸려면 이렇게 합니다.

```powershell
docker compose -f infra/compose/compose.yaml exec postgres psql -P pager=off -U vishue -d postgres -c "ALTER DATABASE vishue RENAME TO vishue_db;"
```

기존 DB 에 남길 데이터가 없다면 볼륨째 지우고 빠른 설치를 다시 합니다.

```powershell
docker compose -f infra/compose/compose.yaml down -v
```

## 막혔을 때

| 증상 | 원인과 조치 |
| --- | --- |
| `docker not found on PATH` | Docker Desktop 이 꺼져 있거나 설치가 안 된 상태입니다 |
| `postgres` 가 `Restarting (255)`, 로그에 `exec format error` | alpine 이미지 문제입니다. 아래 "alpine postgres 이미지가 안 뜰 때" 참조 |
| `postgres did not become ready` | 대개 DB 이름 불일치. 위 "이미 로컬 환경이 있던 경우" 참조 |
| `vishue_db already has N tables` | 이미 설치됐거나 전체 스택이 먼저 돌았습니다. 스크립트가 알려 주는 초기화 명령을 쓰세요 |
| 복원 중 `gin_trgm_ops` 관련 오류 | 확장이 없는 상태입니다. 수동 설치 3번을 하고 4번부터 다시 |
| `alembic upgrade head` 가 아무것도 안 함 | 정상입니다. 수동 설치 5번의 `stamp 0013` 을 먼저 하세요 |
| `alembic check` 가 변경을 보고함 | `git pull` 이 최신인지 확인하고, 그래도 나오면 데이터 담당에게 알려 주세요 |
| 검증에서 `products` 가 0 | 덤프 복원이 안 된 상태입니다. 수동 설치 4번을 확인하세요 |

## alpine postgres 이미지가 안 뜰 때

일부 PC 에서 `postgres` 컨테이너가 기동 직후 `Restarting (255)` 로 반복되고 로그가
이렇게 나옵니다.

```
exec /usr/local/bin/docker-entrypoint.sh: exec format error
```

이 PC 에서 2026-11-04 에 발생했고, 10월에도 한 번 있었습니다. 원인은 Docker Desktop 이
alpine postgres 이미지의 레이어를 풀 때 **파일 내용을 쓰지 못하고 0바이트 파일을
남기는 것**입니다. 이미지를 지우고 다시 받아도, Docker Desktop 과 WSL 을 재시작해도
같습니다. 아키텍처 문제가 아니고 디스크 공간 문제도 아닙니다.

확인하는 명령입니다. 크기가 `0` 으로 나오면 이 증상입니다.

```powershell
docker run --rm --entrypoint sh postgres:17-alpine -c "ls -l /usr/local/bin/postgres"
```

데비안 기반 `postgres:17` 은 영향을 받지 않습니다. 저장소 루트에
`infra/compose/compose.local.yaml` 을 만들고 아래 내용을 넣으세요. 이 파일은
`.gitignore` 에 등록돼 있어 커밋되지 않습니다.

```yaml
services:
  postgres:
    image: postgres:17
```

`setup_local_db.cmd` 는 이 파일이 있으면 자동으로 함께 사용합니다. 손으로 compose
명령을 칠 때는 `-f` 를 두 개 줘야 하고, 빼먹으면 컨테이너가 다시 alpine 으로
만들어져 같은 증상이 재발합니다.

```powershell
docker compose -f infra/compose/compose.yaml -f infra/compose/compose.local.yaml up -d postgres
```

PGDATA 를 alpine(musl)으로 만든 뒤 데비안(glibc)으로 띄우면 `collation version
mismatch` 경고가 나올 수 있습니다. 경고 자체는 무해하지만, 문자열 정렬에 쓰이는
인덱스를 한 번 다시 만들어 두면 깔끔합니다.

```powershell
docker compose -f infra/compose/compose.yaml -f infra/compose/compose.local.yaml exec postgres psql -P pager=off -U vishue -d vishue_db -c "REINDEX DATABASE vishue_db;"
```

## 덤프를 다시 받을 때

데이터가 갱신되면 데이터 담당이 새 덤프를 공유합니다. 기존 데이터를 비우고 빠른
설치를 다시 하면 됩니다.

```powershell
docker compose -f infra/compose/compose.yaml exec postgres psql -P pager=off -U vishue -d vishue_db -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
```

AI-Hub 데이터도 같이 지워지므로 "AI-Hub 적재" 를 다시 해야 합니다.
