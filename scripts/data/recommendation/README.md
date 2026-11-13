# 현재 추천 V2 데이터·학습·실행

2026-11-12 정리 후 기준. 과거 단계별 데이터와 비교 전용 코드는 폐기하고 현재 모델과 재학습 자료를 유지한다.
변경 과정·성능·삭제 목록은 [모델·데이터 인계 및 정리 요약](../../../docs/recommendation-v2-artifacts.md)에 있다.

## 로컬 보존 데이터 (Git 미포함)

실행용 모델은 `ml/runs/recommend-cat-v2/bundle/`의 `model.cbm`·`manifest.json`이다.
피부 분석 원본 `ml/runs/skin-analysis-v4/bundle/`과 같은 위치 체계를 사용하며 둘 다 별도 전달한다.
루트 `.env`의 `RECOMMENDATION_MODEL=recommend-cat-v2`로 선택하고 비교 API를 재시작한다.

| 경로 (ml/data/recommendation-v2 아래) | 역할 |
|---|---|
| curated-20261111-service-concerns | 최종 서비스 고민 변환 및 검수 데이터 |
| curated-20261111-user-ingredient-policy | 사용자 확정 성분 규칙·제외·추정 라벨 및 검수 근거 |
| run-20261110-final | 원본 라벨 전처리 스냅샷; 원문 재검토용 |
| split-20261111-target-concern-only | 대상 고민 기준 정답과 원문 추적 자료 |
| model-ready-20261111 | 원래 인코딩과 사용자 제공 x_complete.csv·x_metadata.csv |
| catboost-skin-condition-20261111 | 80성분 인코딩 사전·원문 피부상태 대조 자료 |
| dictionary-20261110.json, knowledge.json | 성분 사전·지식 엑셀 정규화 스냅샷 |

현재 학습에 직접 사용하는 최종 5,289행은
`ml/experiments/recommendation-v2-image-feature-replacement-20261111/{training,validation,test}.jsonl`이다.
분할은 3,702 / 794 / 793행이며 source·original_group_id·image_group_id·group_id가 보존된다.
`protocol.json`에 7개 입력 순서·고정 설정, `folds.json`에 기존 CV 분할이 있다.
폴더 이름의 날짜와 image-feature-replacement는 현재 모델의 출처 이름이지 폐기 표시가 아니다.
`image/model.joblib`은 현재 모델 원본이다. 과거 5입력 대조 모델 `base/`는 폐기했다.

## 고정 분할 재학습

재학습은 이전 튜닝·오버샘플링 실험을 읽지 않는다. 최종 분할·설정으로 학습하며 검증/테스트는 평가에만 사용한다.
실행 환경은 `ml/pyproject.toml`·`ml/uv.lock`. 기존 결과 경로는 덮어쓰지 않는다.

```powershell
uv run --project ml --group recommendation python -m scripts.data.recommendation.train_v2_final --check-only
uv run --project ml --group recommendation python -m scripts.data.recommendation.train_v2_final --output ml/experiments/새-V2-학습
uv run --project ml --group recommendation python scripts/data/recommendation/export_v2_bundle.py --experiment ml/experiments/새-V2-학습 --model-name recommend-cat-v3
```

`tqdm`으로 학습 반복 수를 표시한다. 결과에는 P@5·Recall@5·Precision·Recall·macro-F1 등 지표,
성분별 지표, 검증/테스트 확률, 입력 해시 및 모델 저장 후 예측 검증이 포함된다.
내보내기는 `ml/runs/<model-name>/bundle/`에 저장하며 기존 경로를 덮어쓰지 않는다(`--output`으로 별도 지정 가능).
모델 업데이트를 자동으로 운영에 반영하지 않는다. 현재 `recommend-cat-v2`의 가중치는 기존 모델과 동일하다.
P@5는 성분 정답과의 일치도이며 제품 효능이나 사용 만족의 정확도가 아니다.
이전에도 관찰한 테스트셋이므로 새 독립 평가로 주장하지 않는다.

## 현재 V2 비교

```powershell
uv run --project backend/api --group recommendation python scripts/data/recommendation/run_v2_comparison.py --docker-local
```

상세 입력·리뷰 정책·최종5 로직은 [V2 비교 설계](../../../docs/recommendation-v2-comparison.md)를 따른다.
Git 공유 실행기는 `run_v2_comparison.py`와 모델 변환·최종 재학습 도구다.
페르소나 비교·검수·사전분포 추정 도구와 사례별 결과는 로컬 작업 자료로 보존하며 이번 커밋에는 포함하지 않는다.

## 로컬 전처리 자료 유지 범위 (Git 미포함)

최종 curation_decisions.json 및 원문 스냅샷, 정규화·연령대·서비스 고민·대상 고민 변환·분할·인코딩 코드는 보존한다.
날짜별 중간 폴더 전체 사본은 제거했다. 원본 D: 라벨·엑셀·이미지·DB는 변경하지 않았다.
성분 원문과 확정/추정/제외 구분을 보존하며 클릭·구매를 성분 정답으로 쓰지 않는다.

공유한 평가·최종 재학습 도구의 단위 테스트:

```powershell
uv run --project ml --group recommendation python -m unittest scripts.data.recommendation.test_training scripts.data.recommendation.test_train_v2_final
```

---

## develop의 DB 매핑 관리 도구 (v0.3)

### develop의 룰 기반 CosIng 추천 경로

develop의 룰 기반 추천은 CosIng 성분 기능만 사용한다. develop의 `0017` 이후
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
