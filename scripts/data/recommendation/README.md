# 피부 고민별 성분 추천 규칙 v0.3

## 현재 앱의 CosIng 추천 경로

현재 앱의 추천은 CosIng 성분 기능만 사용한다. develop의 `0017` 이후
`0018_cosing_functions.py`로 CosIng 테이블 4개와 누락된 고민 코드만 추가한다.
기존 연구 매핑은 보존되지만 추천 후보와 점수에는 포함하지 않는다.
수집 CSV 적재·발행 절차는 [CosIng 데이터 설정 가이드](../../../docs/cosing-data-setup.md)를 따른다.
아래 연구 데이터 관리 도구는 기존 DB 관리용이며 CosIng 적재의 선행 단계가 아니다.

검증된 성분–고민 규칙과 논문별 근거를 먼저 등록합니다. 새 상품은 기존의 재현 가능한 성분 연결 규칙으로 자동 계산합니다. 확인되지 않은 성분에는 효능 규칙을 부여하지 않습니다.

## 테이블

| 운영 테이블 | 역할 |
| --- | --- |
| `rec_concern` | 7개 고민 코드와 사용자 문구 |
| `rec_evidence` | 연구의 서지 정보와 연구 유형 |
| `rec_ingredient_dictionary` | 표준 추천 성분 코드 |
| `rec_mapping` | 검증된 성분 구성, 고민, 적용 범위, 운영 스위치 |
| `rec_mapping_ingredient` | 규칙별 성분 구성 |
| `rec_mapping_evidence` | 규칙별 연구 결과 지표와 해당 연구 조건 |
| `rec_ingredient_link` | 표준 ID·정확한 이름·검증된 별칭/성분군 규칙으로 연결된 현재 원천 ID |
| `rec_concern_match` | 한 옵션이 규칙의 성분 구성을 전부 포함하는지 계산한 결과 |

`recommendation_legacy_archive`는 0016 마이그레이션 전 원본을 보존하는 감사용 보관소이며 추천 운영 테이블에 포함하지 않습니다.

## 입력 파일

`~/Downloads/VISHUE_Recommendation_v0_3`에 다음 CSV를 둡니다.

- `recommendation_reason.csv`: `target_concern,display_label,recommendation_reason`
- `evidence_sources.csv`: `evidence_id,pmid,title,source_url,study_limit,study_type,publication_year`
- `ingredient_dictionary.csv`: `ingredient_code,name_ko,inci_name`
- `recommendation_mapping.csv`: `mapping_id,mapping_type,target_concern,applicability_scope,runtime_enabled`
- `mapping_ingredients.csv`: `mapping_id,ingredient_code,component_order`
- `mapping_evidence.csv`: `mapping_id,evidence_id,supported_endpoint,study_conditions,applicability_note`

매핑 파일에는 승인 대기·검수자·AI 승인 상태를 넣지 않습니다. 입력 전 검증을 통과한 규칙만 넣습니다. 각 매핑에는 논문별 근거 연결이 한 건 이상 있어야 하며, `study_conditions`는 실제 논문에서 확인한 JSON 객체만 기록합니다. 동일 고민·적용 범위·성분 구성 규칙은 하나로 합치고 관련 근거를 모두 연결합니다.

## 연결 규칙 파일

- `ingredient_alias_rules.csv`: `ingredient_code,oy_ingredient_name,rule_version,source_ref`
- `ingredient_group_members.csv`: `ingredient_code,member_name,rule_version,source_ref,applicability_conditions`

두 파일의 규칙은 명시적으로 검증된 것만 넣습니다. 현재 파일은 헤더만 있는 빈 템플릿입니다. 문자열 유사도나 LLM 추론만으로 연결하지 않습니다. 파일 내용의 SHA-256은 발행 스냅샷의 출처 정보에 기록됩니다.

## 실행 순서

`backend/api`에서 실행합니다. 모든 명령은 기본 미리보기이며 실제 기록은 `--apply`가 필요합니다.

1. 검증된 표준 규칙 적재: `uv run python ..\..\scripts\data\recommendation\load_mapping.py --database vishue_db --port 15432`
2. 성분 링크 재구축: `uv run python ..\..\scripts\data\recommendation\link_ingredients.py --database vishue_db --port 15432`
3. 옵션 성분 구성 재계산: `uv run python ..\..\scripts\data\recommendation\compute_matches.py --database vishue_db --port 15432`
4. 새 DB 매핑과 근거를 읽어 스킨케어 발행 파일 생성: `uv run python ..\..\scripts\data\oliveyoung\build_skincare.py <category-label-manifest.json> <serving-bundle.json>`
5. 후보 건수와 고민별 커버리지를 확인한 뒤 `publish_skincare.py`로 발행

공용 DB 쓰기에는 공유 접속 옵션과 `--apply --execute-shared`가 모두 필요합니다. 공용 DB보다 로컬 DB에서 먼저 검증합니다.

## 운영 기준

- `runtime_enabled = true AND applicability_scope = 'ingredient_level'`인 규칙만 일반 자동 추천에 사용합니다.
- `formula_specific`은 논문에서 시험한 특정 제형에만 해당하므로 현재 상품 추천에서는 제외합니다.
- 조합 매핑은 한 상품 옵션 안에서 모든 구성 성분이 확인되어야 일치합니다.
- `rec_concern_match`는 전성분 구성 일치만 뜻하며 제품 효능의 임상 입증을 뜻하지 않습니다.
- `runtime_enabled`는 승인 상태가 아니라 오류 발견 시 규칙을 즉시 끄는 킬 스위치입니다.
- 새로운 매핑 적재 시 기존 스위치가 꺼져 있던 동일 ID는 자동으로 다시 켜지지 않습니다.
- 매핑·성분·링크가 바뀌면 일치 결과를 전량 재계산하고, 확인 후 서빙 스냅샷을 발행합니다.
