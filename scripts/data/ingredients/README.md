# 성분 매칭 (올리브영 → 식약처)

올리브영 원문에서 수집한 성분명을 식약처 성분사전의 현행 표준명에 연결합니다. 결과는
`public.oy_mfds_ingredient_map`에 쌓입니다. 올리브영 성분 하나에 식약처 성분 하나가
붙으며(`oy_ingredient_id`가 기본키), 한 번 기록된 매핑은 다시 실행해도 덮어쓰지 않습니다.

- `match_oy_mfds.py`: 매처
- `ingredient_aliases.csv`: 사람이 검수해 승인한 유사어 (현재 159행)

조각으로 잘린 성분을 먼저 복구해야 합니다. 수집·적재와 복구 순서는
`scripts/data/oliveyoung/README.md`의 "적재 후 성분 정리"에 있습니다.

## 실행

`backend/api`에서 실행합니다. 미리보기가 기본이며 `--apply`로만 기록합니다. 비밀번호는
명령어나 `.env`에 적지 않고 프롬프트에 입력합니다.

미리보기:

```powershell
uv run python ..\..\scripts\data\ingredients\match_oy_mfds.py --target local --database vishue_v29 --port 15432
```

기록:

```powershell
uv run python ..\..\scripts\data\ingredients\match_oy_mfds.py --target local --database vishue_v29 --port 15432 --apply
```

매칭되지 않거나 후보가 여러 개인 이름은 `--report-dir`(기본값
`~/Downloads/ingredient-mapping-review`)에 검토용 CSV로 남습니다. DB에는 넣지 않습니다.

공용 DB에서는 `--target shared`와 Session pooler 접속 정보, `--project-ref`,
`--ssl-ca-file`이 필요하고 실제 쓰기에는 `--apply --execute-shared`가 모두 필요합니다.
공용 DB에 쓰기 전에 같은 수집본으로 로컬에서 먼저 확인합니다.

## 매칭 규칙 순서

앞 규칙이 성립하면 뒤 규칙은 보지 않습니다. `match_method` 열에 어느 규칙으로 붙었는지
남습니다.

| 순서 | `match_method` | 근거 |
| --- | --- | --- |
| 1 | `exact_name` | 식약처 현행 표준명과 이름이 같다 |
| 2 | `official_synonym` | 식약처가 제공하는 이명과 같고 후보가 하나다 |
| 3 | `amount_suffix_exact` | 끝의 함량 표기를 떼면 표준명과 같다 |
| 4 | `amount_suffix_synonym` | 끝의 함량 표기를 떼면 이명과 같고 후보가 하나다 |
| 5 | `manual` | 위 규칙으로 안 붙은 이름 중 `ingredient_aliases.csv`에 승인된 것 |

1~4는 규칙이라 `rule_version`이 남습니다(현재 `v2`). 5는 사람이 판단한 것이라
`reviewed_by`와 `reviewed_at`이 남습니다. 표의 CHECK 제약이 둘 중 하나를 반드시 요구합니다.

후보가 둘 이상인 이명은 자동으로 붙이지 않고 검토 CSV로 보냅니다.

## 이름 비교 기준

비교는 `name_key()`로 정규화한 값끼리 합니다. NFKC 정규화와 연속 공백 정리만 합니다.

- 공백을 지우지 않습니다
- 대소문자를 합치지 않습니다

즉 `비타민 C`와 `비타민C`는 다른 이름으로 봅니다. 표기가 이 정도만 달라서 안 붙는 경우가
유사어 파일에 들어가는 주된 사유입니다.

## 유사어 승인 파일

`ingredient_aliases.csv`에 승인된 쌍만 `manual`로 기록됩니다.

| 열 | 내용 |
| --- | --- |
| `oy_name` | 올리브영 원문의 성분명 (원문 그대로) |
| `mfds_name` | 연결할 식약처 현행 표준명 |
| `reviewed_by` | 승인한 사람 |
| `reviewed_at` | 승인한 날짜 |
| `review_note` | 승인 근거 |

`oy_name`에 쉼표가 들어가면 (`1,2-헥산다이올`) 반드시 따옴표로 감쌉니다. 따옴표를 빼면
열이 하나 밀립니다.

`review_note`에는 왜 같은 성분이라고 판단했는지 남깁니다. 현재 쓰인 근거는 대한화장품협회
성분사전 성분코드, 영문명 일치, 후행 기호 제거, 공백 차이, 함량·별표 표기, 하이픈 유무,
`디/다이`·`알콜/알코올` 같은 표기 차이입니다. 성분코드처럼 출처를 특정할 수 있는 근거는
코드를 적습니다.

`mfds_name`이 식약처 현행 표준명에 없으면 그 행은 기록되지 않고 검토 CSV에
`alias_target_missing`으로 남습니다.

## 넣지 말 것

- **영문명으로 자동 매칭.** 식약처 자료에서 `Water`의 영문명을 따라가면 `탄산수`가 나옵니다.
  정답은 `정제수`입니다. 영문명은 사람이 확인한 뒤 유사어 파일에 한 쌍씩 넣습니다.
- **같은 계열이라는 이유로 묶기.** 성분명이 비슷해 보여도 다른 물질입니다.
- **추측.** 근거를 `review_note`에 쓸 수 없으면 승인하지 않고 미매칭으로 둡니다.

## 미매칭의 의미

**미매칭은 "성분이 없다"가 아니라 "식약처 표준명을 모른다"입니다.** 성분은 원문에 있고
`raw_oy_ingredient`에 있습니다. 식약처 표준명에 연결되지 않은 것뿐입니다.

이 표를 쓰는 화면이나 API는 미매칭 성분을 빠뜨리지 말고 원문 표기 그대로 보여주어야
합니다. 숨기면 전성분 표기가 실제 제품과 달라집니다.

## 하지 않기로 한 것

**색조 성분명의 호수 접두 제거.** `21 로즈베이지 정제수`처럼 호수명이 성분명 앞에 붙는
경우가 있으나 접두를 떼지 않습니다. 사유는 (1) 접두를 떼다가 성분명 일부까지 떼낼
위험이 있고, (2) 제품마다 호수 표기 방식이 달라 한 규칙으로 처리할 수 없고, (3) 색조
제품의 성분 정보는 스킨케어만큼 중요하게 쓰이지 않기 때문입니다. 색조 쪽 미매칭이
스킨케어보다 많은 이유의 일부입니다.

**색소 레이크의 식약처 매핑.** 색소 레이크 12쌍은 알루미늄 함유 구분을 남기기 위해 의도적으로
매핑하지 않습니다. 원표기를 유지합니다.

## 매칭률과 커버리지

두 숫자는 세는 단위가 다릅니다. 섞어 쓰면 안 됩니다.

| 지표 | 단위 | 뜻 |
| --- | --- | --- |
| 매칭률 | 성분 종류 | 올리브영 성분 몇 종이 식약처에 연결되었나 |
| 커버리지 | 상품-성분 조합 | 전성분 표기 칸 중 몇 칸이 연결된 이름으로 채워지나 |

커버리지가 더 높은 것은 자주 쓰이는 성분이 대체로 먼저 연결되기 때문입니다. 미매칭으로
남은 것은 한두 상품에만 나오는 이름이 많습니다.

공용 DB 기준 (2026-11-03):

| 항목 | 값 |
| --- | --- |
| 올리브영 성분 | 9,185종 |
| 매핑됨 | 4,801종 (52.27%) |
| 그중 `manual` | 151 |
| 미매칭 상품사용 | 6,316건 |
| 커버리지 | 97.95% |

집계 쿼리:

```sql
WITH usage AS (
  SELECT oi.ingredient_id, COUNT(DISTINCT po.goods_no) AS product_count
  FROM public.raw_oy_option_ingredient oi
  JOIN public.raw_oy_product_option po ON po.option_id = oi.option_id
  GROUP BY oi.ingredient_id
)
SELECT
  (SELECT COUNT(*) FROM public.raw_oy_ingredient) AS oy_total,
  (SELECT COUNT(*) FROM public.oy_mfds_ingredient_map) AS mapped,
  (SELECT COUNT(*) FROM public.oy_mfds_ingredient_map WHERE match_method = 'manual') AS manual_rows,
  (SELECT COALESCE(SUM(product_count), 0) FROM usage) AS all_uses,
  (SELECT COALESCE(SUM(u.product_count), 0) FROM usage u
     WHERE NOT EXISTS (SELECT 1 FROM public.oy_mfds_ingredient_map m
                       WHERE m.oy_ingredient_id = u.ingredient_id)) AS unmatched_uses;
```

`매칭률 = mapped / oy_total`, `커버리지 = (all_uses - unmatched_uses) / all_uses` 입니다.

## 표 제약

`public.oy_mfds_ingredient_map` (마이그레이션 0007, 0011):

- 기본키 `oy_ingredient_id` — 올리브영 성분 하나에 식약처 성분 하나
- `raw_oy_ingredient`, `raw_mfds_ingredient`로 외래키
- `match_method`는 위 표의 다섯 값만 허용
- `manual`이면 `reviewed_by`·`reviewed_at`이 필수, 규칙이면 `rule_version`이 필수

현재 이 표를 읽는 API·서비스 코드는 없습니다. 앱 서빙 테이블(`products`, `shades`)은 이
표를 참조하지 않습니다.
