# 기초 화장품 추천 v1

기기에서 목적을 결정하고 `POST /api/recommendations/skincare`에 파생 정보만 전송한다.
기존 `/skin` API는 별도로 유지한다. 목표는 보습·진정·미백·탄력·모공이며
사용자 목표가 우선이다. v4는 양호/유의 이진 결과이고 이전 등급 결과만 4 이상을 유의로 해석한다.
초기 목적 규칙과 정렬은 검증되지 않은 휴리스틱이다.

## 데이터 발행

0012 마이그레이션의 `skincare_serving`은 개인정보 없는 버전별 JSONB 서빙 projection이다.
작은 매핑 데이터셋을 한 번에 검증·교체하기 위해 옵션·매핑·논문을 한 행으로 발행한다.
상품은 동일 트랜잭션에서 upsert하며 기존 상품과 룩은 삭제하지 않는다.
전체 카탈로그를 교체하는 기존 seed 명령은 오래된 projection을 무효화한다. 이후 다시 발행한다.

검수 manifest는 실제 운영 DB 확인 후 작성한다. 아래 값은 형식 예시이며 실제 코드·ID가 아니다.

```json
{
  "version": "reviewed-data-version",
  "reviewedBy": "reviewer",
  "availableSaleStatuses": ["운영 DB에서 확인한 판매중 코드"],
  "categories": {"검수된 세럼 표준분류 코드": "serum"},
  "ingredients": {
    "NIACINAMIDE": {"mfdsIds": [123], "reviewedBy": "reviewer", "source": "검수 근거"}
  },
  "labels": {
    "상품번호": {"skinTypes": ["dry"], "sensitive": false, "source": "제조사 표기 출처"}
  }
}
```

허용 세부분류는 toner/essence/serum/ampoule/lotion/cream뿐이다.
세트·마스크·선케어·세정제는 분류 manifest에 포함하지 않는다.
MFDS ID는 CSV 정수가 아니라 운영 `oy_mfds_ingredient_map`으로 확인한다.
미연결 성분은 사용하지 않으며 이름·함량·성분 표기 순서로 효과를 추측하지 않는다.

`backend/api`의 uv 환경에서 실행한다. 첫 두 단계는 운영 DB를 변경하지 않는다.

```powershell
uv run python ../../scripts/data/oliveyoung/build_skincare.py mapping.zip reviewed-manifest.json reviewed-bundle.json
uv run python -m app.jobs.publish_skincare reviewed-bundle.json
uv run python -m app.jobs.publish_skincare reviewed-bundle.json --apply
```

DB URL은 backend 환경의 DATABASE_URL을 사용한다. 마이그레이션은 기존 배포 절차로 적용한다.
원본 ZIP의 runtime_enabled=0을 변환 코드에서 변경하지 않는다. 운영 사용 승인은 검수 담당자가
매핑 데이터에 명시적으로 반영한 후 다시 발행한다. 진정·모공은 승인 매핑 부재로 준비 중일 수 있다.

## 동작과 추적

주목적 일치 → 보조 목적 수 → 제조사 민감 피부 표기(자극 신호 시) → 제조사 피부 타입 일치
→ 리뷰 보조값 → 리뷰 수 → 상품·옵션 ID로 정렬한다. 리뷰 prior는 20이며 현재 순위의
효능이나 정확도를 의미하지 않는다. 복합 성분은 동일 옵션 포함 여부만 개발 추적에 남긴다.
리뷰 문항별 응답자 수가 없어 피부 타입·자극 리뷰 비율은 순위에 쓰지 않는다.

요청은 primaryGoal/secondaryGoals/skinType/irritationSignal/goalPolicyVersion/limit이다.
원본 설문·모델 점수·사진 필드는 거부한다. 목적별 mapping_unavailable/no_matches/ok를 반환한다.
includeTrace=true는 서버 env가 local/development/test일 때만 처리한다.
개발용 최신 기록은 기기 AsyncStorage에 1건만 저장하며 일반 리포트에는 표시하지 않는다.
서버는 개인 요청·추천 이력을 저장하지 않고 응답은 no-store다.
