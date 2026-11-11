# 검수 근거 기반 성분 상담

I-3은 I-1 #227의 주장·출처 개정본과 I-2 #228의 카탈로그 옵션 API를 사용한다. 기존 #225의 전성분 검증과 Redis 후보 순번을 재사용한다.

## 근거 검수와 발행

- 검수자는 승인할 주장 개정본의 `canonical_text`에 서비스 공개용 설명을 작성한다. 적용 범위 `applicability`에는 검수한 `ingredient: { mfdsIngredientId, sourceHash }`와 필요한 `concerns`, `targets`, `formulations`, `concentrationMinPct`, `concentrationMaxPct`를 기록한다. 변경 시 새 개정본으로 검수한다.
- 검수 완료 및 `approved` 또는 `limited_approved` 상태와 `explain`·`rank`·`avoid` 권한을 확인한다. 제한 승인은 검증 가능한 범위가 있어야 한다. 출처 검수는 해당 개정본을 지지해야 하며 최신 문서 버전과 이용권한을 확인한다. 문서의 최신 버전은 같은 `source_identifier`로 등록된 문서 ID 순서로 결정하므로 개정본은 등록 순서대로 추가한다.
- 명시적인 발행 명령이 승인 설명, 식약처 버전, 서지 정보와 원천 릴리스를 고정한다. 운영용 발행 명령은 테스트 플래그를 받지 않는다. QA와 문서의 연결에서 `local_only` 또는 다른 미허용 권리가 확인되면 발행·조회가 차단된다. QA의 원문·발췌·파일 경로는 서비스 조회 대상에서 제외한다.
- 기존 발행 ID는 새 주장·출처 개정, 승인 변경, 출처 검수 변경 또는 철회 후 다시 활성화되지 않는다. 다시 검수하고 별도의 발행 명령으로 새 ID를 생성한다. 식약처 ID와 버전은 매 조회 시 현재 사전과 대조한다.

격리된 검증 DB에서만 합성 검수 데이터로 아래 명령을 확인한다. 실제 AIHub 릴리스는 현재 `local_only` 상태다.

```text
uv run python -m app.jobs.claim_publication publish --claim-version-id <id> --source-review-id <id> --release-id <id> --ingredient-id <id> --mfds-source-hash <hash> --source-title <title> --source-url <public-citation-url> --publisher <reviewed-publisher>
uv run python -m app.jobs.claim_publication revoke <publication-id>
```

## 서비스 계약

`POST /api/catalog/ingredient-claims/search`는 `use`와 `context` 및 아래 선택자 중 하나를 받는다. 설명과 서지 정보만 반환하며 응답을 캐시하지 않는다.

| 선택자 | 범위 |
| --- | --- |
| `ingredientNames` | 최대 6개. #225의 식약처 표준명·별칭 해석을 사용한다. |
| `ingredients` | 최대 64개 식약처 ID와 원천 해시 쌍. |
| `publicationIds` | 최대 24개. Redis 재응답에서 같은 용도·적용 조건으로 재검증한다. |

발행 근거가 부족하면 `claims: []`, 조회 실패는 HTTP 503이다. 조회는 사전·권리·발행 상태를 함께 평가하며 최대 24건을 반환한다. Redis에 저장된 설명을 다시 반환하기 전 발행이 변경되면 409, 조회 불가면 503으로 응답한다.

`POST /api/chat`은 설명 요청에 `publishedClaims`, `claimStatus`와 빈 상품 목록을 반환한다. 상품 상담은 `optionSearch`에서 확인한 카테고리·페이지 범위·중단 사유·옵션별 판정과 근거 ID를 제공한다. 후보 카드는 같은 상품에 대해 한 옵션을 선택하며, `optionClaimLinks`는 검수된 표기 버전과 식약처 ID·해시가 일치하는 연구 근거를 연결한다. `finishedProductEfficacy`는 `unverified`다. 기존 참고가는 참고가로 표시된다.

- 특정 성분을 피해야 하는지 묻는 설명에는 `avoid` 허용 근거를 사용한다. 옵션 검색의 필수 포함·제외 조건은 사용자의 요청에서 가져온다.
- 전체 카테고리 검색은 페이지당 최대 32개, 최대 4페이지·128개 옵션이다. 이전 결과 범위는 Redis의 정확한 옵션 최대 6개를 재조회한다.
- 카테고리 및 근거 조회는 각각 최대 8초, 옵션 페이지 조회는 합계 최대 20초다. 페이지 한도, 제한 시간, 조회 실패, 응답 범위 불일치에서 중단한다. 카탈로그 페이지에는 공유 스냅샷 토큰이 없어 건수와 옵션 중복을 검사하며 응답은 조회한 범위로 한정한다.
- 현재 판매가와 현재 재고는 현재 근거로 판정한다. 명시적으로 요청한 수집가 기준은 수집 시각·출처와 함께 표시한다. 확정 위반은 다른 조건의 `UNKNOWN`·`ERROR`에도 유지한다.
- 특정 성분의 부재 판정은 검수한 전체 전성분에 한정된다. 표시명 `향료` 한 항목의 부재를 향 성분 전체의 부재로 표시하지 않는다. 옵션별 농도·완제품 효능은 별도의 검수된 제품 근거가 필요하다.

## 격리 검증

- `backend/api`에서 마이그레이션한 전용 테스트 DB를 `TEST_DATABASE_URL`로 지정하고 `uv run pytest tests/test_claim_publication.py`를 실행한다. 합성 발행 데이터는 트랜잭션을 롤백하며 기본 HTTP 조회에서도 제외된다.
- 실제 Catalog HTTP와 챗봇 계약을 같이 검증할 때 `VISHUE_CHATBOT_TEST_PYTHON`에 기존 챗봇 테스트 런타임을 지정한다. `VISHUE_I3_TEST_REDIS_URL`에는 격리 테스트 Redis만 지정한다. 이 검증은 테스트용 질문 해석기를 사용한다.
- 실제 AIHub 복구본과 Catalog 스냅샷은 `VISHUE_I3_ACTUAL_AIHUB_DB_URL`, `TEST_CATALOG_SNAPSHOT_URL`로 지정한다. 두 연결은 읽기 전용이다. AIHub 근거 차단과 실제 옵션의 현재가·수집가·성분 판정을 검증한다.
