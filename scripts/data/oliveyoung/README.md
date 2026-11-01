# 올리브영 원본 수집·적재

메이크업은 기존 v30, 스킨케어는 v1의 22개 소분류를 유지하면서 v30의 성분 파서를 적용한 v2를 사용합니다. 디바이스는 수집하지 않습니다. 두 실행 파일은 같은 방식으로 동작합니다.

- `collect_load_skincare.py`: 스킨케어 v2 수집·적재
- `collect_load_makeup.py`: 메이크업 v30 수집·적재

현재 상품정보 수집·활용 문의의 답변이 오지 않았습니다. 새 실수집과 공용 DB 적재는 허용 범위를 확인한 뒤 진행합니다. 로컬 검증에는 합성 테스트 자료를 사용할 수 있습니다.

## 실행 순서

`backend/api`에서 `uv sync --group data`로 수집 전용 `requests`와 `Pillow`를 설치합니다. 비밀번호는 명령어나 `.env`에 적지 않고 프롬프트에 입력합니다. `--snapshot-dir`은 저장소 밖의 새 폴더를 지정합니다.

동시 상품 수집 작업자의 기본값은 기존 수집기와 같은 10입니다. 요청 속도를 조절할 때만 `--workers`를 지정합니다.

한 번에 실행하려면 `--phase run`을 사용합니다. 수집본 CSV와 `manifest.json`을 저장한 뒤, 완전한 수집본만 DB에 연결합니다. 적재 트랜잭션 안에서 CSV 형식과 참조를 검사하고 통과하면 반영합니다. 중단된 수집은 같은 명령과 폴더로 재실행할 수 있습니다.

```powershell
uv run --group data python ..\..\scripts\data\oliveyoung\collect_load_skincare.py --phase run --mode full --snapshot-dir "C:\Users\Playdata\Downloads\oy-skincare-run-YYYYMMDD" --database vishue_v29 --port 15432
```

공용 DB에서도 `--phase run`을 사용할 수 있지만, `--target shared`와 접속 정보, CA 인증서, `--execute-shared`가 필요합니다. 검수 후 적재하려면 아래처럼 단계를 나누어 실행합니다.

```powershell
uv run --group data python ..\..\scripts\data\oliveyoung\collect_load_skincare.py --phase collect --mode full --snapshot-dir "C:\Users\Playdata\Downloads\oy-skincare-run-YYYYMMDD"
```

중단된 수집은 같은 명령과 폴더로 다시 실행합니다. 상품 목록 조회나 상세 수집이 하나라도 실패하면 `manifest.json`의 `complete`가 `false`이며 적재를 거부합니다. `ingredient_parse_review` 로그가 있는 상품은 옵션별 성분 연결을 검토합니다.

전처리 규칙이 바뀐 수집본은 `skincare-v2.1-db` 또는 `makeup-v30.1-db`로 기록합니다. 이전 버전의 완료 폴더를 다시 지정해도 재수집되지 않으므로, 새 규칙으로 수집할 때는 새 `--snapshot-dir`을 사용합니다. 재개 중인 수집본과 현재 스크립트의 버전이 다르면 이어 수집하지 않습니다.

로컬 DB에서 별도로 사전 확인 후 적재:

```powershell
uv run python ..\..\scripts\data\oliveyoung\collect_load_skincare.py --phase preflight --snapshot-dir "C:\Users\Playdata\Downloads\oy-skincare-run-YYYYMMDD" --database vishue_v29 --port 15432
```

```powershell
uv run python ..\..\scripts\data\oliveyoung\collect_load_skincare.py --phase apply --snapshot-dir "C:\Users\Playdata\Downloads\oy-skincare-run-YYYYMMDD" --database vishue_v29 --port 15432
```

메이크업은 실행 파일명만 `collect_load_makeup.py`로 바꿉니다. 공용 Supabase DB의 경우 `--target shared`, `--project-ref`, Connect의 Session pooler `--host`/`--port`/`--database`/`--user`, `--ssl-ca-file`을 지정합니다. 실제 쓰기에는 `--phase apply --execute-shared`가 모두 필요합니다. 먼저 같은 인자로 `--phase preflight`를 실행합니다.

## 동작 및 주의

- 수집 단계는 DB에 연결하지 않고 CSV·`manifest.json`을 남깁니다. CSV의 숫자 ID는 이 폴더 안에서만 유효합니다. 적재 시 기존 DB의 성분 ID를 이름 키로 다시 찾고, 색상 근거 이미지 ID도 DB 이미지 ID로 다시 연결합니다.
- 같은 수집본의 재적재는 중복 상품·옵션·가격·이미지·성분 연결을 만들지 않습니다. 기존 옵션의 성분 연결과 `is_in_catalog` 값은 보존합니다. 옵션 전성분이 바뀐 경우에는 기존 연결을 자동 교체하지 않으므로 검토 후 별도 정정이 필요합니다. 올리브영 원본 적재는 앱 서빙 `products`/`shades`와 `seed/catalog.json`을 변경하지 않습니다.
- 스킨케어 목록에 메이크업 상품이 함께 나타나면 기존 메이크업 상품·옵션 값은 보존하고 `raw_oy_skincare_attr`만 갱신합니다.
- `■■■호수■■■` 표시가 있는 성분 원문은 구획을 먼저 파싱합니다. 실제 옵션과 1:1로 확인되지 않는 묶음 구성이나 구획은 자동 연결하지 않고 검토 로그에 남깁니다. DB에 들어가는 문자열에서 `■`를 제거하며, 로컬 원문 CSV는 검토를 위해 유지합니다.
- 깨진 글자가 포함된 성분 토큰과 검증된 독립 제목·안내문은 성분 연결에서 제외하고 검토 로그에 남깁니다. 성분명과 붙어 있는 제목은 추측해 분리하지 않습니다. 스킨케어 기능성 여부는 `|N`과 `■ 무`만 추가로 `N`으로 판정하며 원문은 보존합니다. `SPF 5ml` 같은 용량 표기는 SPF 값으로 취급하지 않습니다.
- `--mode full`은 완전한 목록을 기준으로 이전 완료 수집에서 사라진 상품과 옵션에 `delisted_at`을 기록합니다. 첫 완료 수집에는 비교할 과거 목록이 없으므로 기존 v29 상품의 판매 중단 여부를 추정하지 않습니다.
- `--mode incremental`은 새 가격·리뷰·색상 이력을 쌓고 상품·옵션을 갱신하지만 목록에서 사라진 항목은 표시하지 않습니다. 목록 API에서 신뢰할 만한 변경 시점을 받지 못하므로 **증분 모드도 모든 목록 상품의 상세 정보를 다시 조회**합니다. 호출량 절감 최적화는 변경 신호가 확인된 뒤 별도로 구현해야 합니다.
- 공용 DB 적재 전에 로컬 DB에서 같은 수집본으로 사전 확인·적재·재적재를 검증합니다. 실제 새 수집은 사이트 이용 조건과 허용 범위를 확인한 뒤 진행합니다.
