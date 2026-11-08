# v0.3 운영 경로

Alembic 0018은 `backend/api/seed/recommendation_v03/`을 사용한다. 0019 적용 후에는
`load_cosing.py`로 별도 전달받은 CosIng CSV를 적재한다. 적재와 발행은
[추천 발행 절차](../../../docs/skincare-recommendations.md)를 따른다.
아래 적재기와 수동 연결 절차는 0017 이하의 구 스키마 전용이다.

# 피부 고민별 성분 추천 매핑

AI 담당이 전달한 매핑 데이터셋을 `rec_*` 테이블에 적재하고, 추천 성분 코드를 수집
성분에 연결한 뒤, 매핑의 성분 구성을 갖춘 상품 옵션을 계산합니다.

전달본: `VISHUE_DB_추천매핑_요구사항정합_v1_2_1` (매핑 32건, 성분 코드 27개, 논문 33건)

## 실행 순서

`backend/api`에서 실행합니다. 세 스크립트 모두 미리보기가 기본이며 `--apply`로만
기록합니다. 비밀번호는 명령어나 `.env`에 적지 않고 프롬프트에 입력합니다.

전달본 적재:

```powershell
uv run python ..\..\scripts\data\recommendation\load_mapping.py --target local --database vishue_db --port 15432 --apply
```

성분 코드를 수집 성분에 연결:

```powershell
uv run python ..\..\scripts\data\recommendation\link_ingredients.py --target local --database vishue_db --port 15432 --apply
```

상품 옵션별 성분 일치 계산:

```powershell
uv run python ..\..\scripts\data\recommendation\compute_matches.py --target local --database vishue_db --port 15432 --apply
```

성분 데이터가 바뀌면(수집·조각 복구·성분 매처 이후) 마지막 단계를 다시 실행합니다.
`compute_matches.py --apply`는 파생 테이블 전체를 다시 계산합니다.

공용 DB에서는 `--target shared`와 Session pooler 접속 정보, `--ssl-ca-file`이 필요하고
실제 쓰기에는 `--apply --execute-shared`가 모두 필요합니다.

## 테이블

전달본 7개 파일 중 6개를 테이블로 옮기고, 2개를 이 저장소에서 만듭니다.

| 테이블 | 출처 | 내용 |
| --- | --- | --- |
| `rec_concern` | `recommendation_reason.csv` | 고민 코드 6종과 사용자에게 보여줄 문구 |
| `rec_evidence` | `evidence_sources.csv` | 근거 논문 33건. `study_limit`에 연구 한계 |
| `rec_ingredient_dictionary` | `ingredient_dictionary.csv` | 성분 코드 27개 |
| `rec_mapping` | `recommendation_mapping.csv` | 매핑 32건과 등급 컬럼 |
| `rec_mapping_ingredient` | `mapping_ingredients.csv` | 매핑별 구성 성분 |
| `rec_manual_review_candidate` | `manual_review_candidates.csv` | 판정 전 연결 금지 후보 2건 |
| `rec_ingredient_link` | 이 저장소 | 성분 코드 ↔ `raw_oy_ingredient` |
| `rec_concern_match` | 이 저장소 | 매핑 ↔ 상품 옵션 (계산 결과) |

## 전달본의 성분 ID는 쓰지 않습니다

전달본 `ingredient_id_bridge.csv`(495행)와 `ingredient_dictionary.csv`의
`ingredient_ids` 열은 구 수집본(`out_skincare_v1`, `out_makeup_v23`) 식별자입니다.
현재 `raw_oy_ingredient`와 번호 체계가 달라 적재하지 않습니다.

495행을 전수 대조한 결과입니다.

| 결과 | 건수 |
| --- | --- |
| 이름 일치 | 0 |
| 그 ID가 현재 DB에 없음 | 318 |
| ID는 있으나 다른 성분 | 177 |

예: `NIACINAMIDE`의 ID 1022는 현재 DB에서 `탄제린추출물(0.1ppb)`입니다. 재현은
`verify_bridge_ids.py`로 합니다.

```powershell
uv run python ..\..\scripts\data\recommendation\verify_bridge_ids.py --target local --database vishue_db --port 15432
```

그래서 연결은 `rec_ingredient_dictionary.name_ko`를 수집기와 같은 정규화로 맞춰
새로 만듭니다. 27개 중 21개가 이름 정확 일치로 연결됩니다.

## 연결되지 않은 성분 코드 6개

| 코드 | 상태 |
| --- | --- |
| `AZELAIC_ACID`, `KINETIN`, `RETINYL_PROPIONATE` | 올리브영 전성분에 해당 성분이 없습니다. 비슷한 이름에 붙이지 않습니다 |
| `4_HEXYLRESORCINOL` | `헥실레조시놀`이 후보이나 동일 INCI 여부 확인 전입니다 |
| `CERAMIDE_COMPLEX`, `TRIGLYCERIDES` | 성분군입니다. 어느 세부 성분까지 포함할지 정해야 합니다 |

성분군은 근거 논문이 어떤 성분을 썼는지에 달려 있어 데이터 담당자가 혼자 정하지
않습니다. 정해지면 `ingredient_links_manual.csv`에 검수자와 날짜를 적어
`link_ingredients.py`가 `manual` 또는 `group_member`로 기록합니다. 검수자와 날짜가
없으면 스크립트와 테이블 제약이 모두 거부합니다.

연결되지 않은 성분 코드를 쓰는 매핑은 계산하지 않고 사유와 함께 건너뜁니다. 일부만
연결된 상태로 계산하면 조합이 실제보다 느슨하게 일치합니다.

## 일치 판정 규칙

성분은 옵션 단위로 달려 있어(색조는 호수별로 다름) 옵션 기준으로 계산합니다. 상품
단위 노출은 옵션 중 하나라도 일치하는지로 판단합니다.

**조합은 한 옵션에 구성 성분이 모두 있어야 일치합니다.** 부분 일치 보너스는 없습니다.

카탈로그 안팎을 가리지 않고 모든 옵션을 계산합니다. 카탈로그는 자주 바뀌지만 성분은
월 1회 바뀌므로, 성분 기준으로 계산해 두고 소비하는 쪽이 `is_in_catalog`로 거릅니다.

## 노출 기준은 소비하는 쪽이 정합니다

전달본 32건을 등급 컬럼과 함께 그대로 적재합니다. 거르지 않는 이유는 어떤 등급을
노출 가능으로 볼지가 아직 합의되지 않았고, 걸러서 넣으면 제외 사유가 남지 않기
때문입니다.

- `runtime_enabled`는 전달본 32건 전부 거짓입니다. 승인 없이 켜지 않습니다.
- `mapping_status`의 `research_only`, `support_only`, `formula_evidence_only`,
  `excluded_*`는 자동 효과 근거로 쓰지 않습니다.
- `re_review_required`가 참인 매핑이 32건 중 20건입니다.
- 모든 조건을 통과한 매핑은 8건이며 전부 단일 성분입니다. 조합 12건 중 통과한 것은
  없습니다.
- `evidence_sources.study_limit`에 연구 한계가 적혀 있습니다. 근거를 과장하지 않으려면
  매핑과 함께 읽어야 합니다.

### 흔한 성분은 추천이 되지 않습니다

`S008`(보습 / 글리세린)은 카탈로그 상품 824개에 걸립니다. 글리세린은 대부분의
화장품에 들어가므로 이 매핑을 켜면 추천이 아니라 전체 목록이 됩니다. 이 매핑은
`re_review_required`가 참입니다.

`S001`, `S002`, `S003`, `S019`는 모두 나이아신아마이드 하나이며 고민만 다릅니다.
사용자가 어떤 고민을 골라도 같은 상품이 나옵니다.

## 상품 데이터와의 경계

`rec_*` 테이블은 `products`, `shades`를 바꾸지 않습니다. 추천 매핑은 상품의 실제
전성분(`raw_oy_option_ingredient`)을 읽기만 합니다. 성분 매칭 규칙과 미매칭의 의미는
`scripts/data/ingredients/README.md`에 있습니다.
