# 피부 분석·설문·상품 데이터 현황

작성일: 2026-11-05. 현재 저장소 코드와 로컬 `vishue_db` 조회를 기준으로 한다. 수치는 조회 시점의 로컬 데이터이며 운영 DB 수치가 아니다.

## 1. 피부 분석 모델 출력

현재 모바일 v4 (`skin-analysis-mobile-v4`)는 모공, 색소침착, 주름, 피부 타입을 분석한다. 현재 v4의 아홉 개 부위별 상태는 0(양호), 1(유의) 이진값이다. `grade`라는 기존 필드 이름은 그대로 사용하지만 0~4등급을 뜻하지 않는다.

| 항목 | 부위 | 출력 |
| --- | --- | --- |
| 모공 | 이미지 기준 왼쪽 볼·오른쪽 볼 | 부위별 sigmoid 점수와 이진값 2개 |
| 색소침착 | 이마·이미지 기준 왼쪽 볼·오른쪽 볼 | 부위별 sigmoid 점수와 이진값 3개 |
| 주름 | 이마·미간·이미지 기준 왼쪽 눈가·오른쪽 눈가 | 부위별 sigmoid 점수와 이진값 4개 |
| 피부 타입 | 이마·양 볼 | 세 부위의 softmax 결과를 평균한 `dry`, `balanced`, `oily` 점수와 최댓값 라벨 |

각 모공·색소·주름 모델은 부위마다 logit을 출력하고 `sigmoid(logit)`으로 0~1 점수 `cautionProbabilities`를 만든다. **0.5 이상이면 1, 미만이면 0**이다. 예를 들어 0.42는 0, 0.68은 1이다. 점수가 높을수록 모델의 유의 클래스 출력이 높다는 뜻이지만, 이 값은 보정되지 않은 모델 점수로 임상적 신뢰도나 검증된 심각도 척도가 아니다. 각 타입의 3개 점수도 보정되지 않은 클래스 점수다.

피부 타입은 각 부위의 softmax를 평균한다. 점수 배열 순서는 `[dry, balanced, oily]`이며 값이 가장 높은 타입을 선택한다. 얼굴 전체에서 단일 수치를 직접 측정하는 모델은 아니다. 모공·색소·주름 리포트는 해당 부위 이진값 중 최댓값을 대표 상태로 사용한다. 현재 모바일 v4에는 여드름 모델 출력이 없으며 해당 항목은 `unknown`이다. 수분량·유분량의 연속 실측치도 없다. 건조·유분 관리 상태는 피부 타입 및 설문에서 파생된다.

### 출력 예시

현재 확인한 저장소에는 공유 가능한 **실제 사용자 추론 결과 1~2건이 확인되지 않았다**. 아래는 필드와 판정의 이해를 돕기 위한 **가상 예시**이며 실제 추론 기록이 아니다. 실제 결과 객체에는 `roiMethod`, `validationStatus`, `timing` 등도 포함된다.

```json
{
  "schema": "skin-analysis-mobile-v4",
  "features": {
    "pore_grade_cheek_image_left": 0,
    "pore_grade_cheek_image_right": 1,
    "pigmentation_grade_forehead": 0,
    "pigmentation_grade_cheek_image_left": 0,
    "pigmentation_grade_cheek_image_right": 1,
    "wrinkle_grade_forehead": 0,
    "wrinkle_grade_glabella": 0,
    "wrinkle_grade_eye_image_left": 1,
    "wrinkle_grade_eye_image_right": 0
  },
  "cautionProbabilities": {
    "pore_grade_cheek_image_left": 0.42,
    "pore_grade_cheek_image_right": 0.68,
    "pigmentation_grade_forehead": 0.30,
    "pigmentation_grade_cheek_image_left": 0.40,
    "pigmentation_grade_cheek_image_right": 0.51,
    "wrinkle_grade_forehead": 0.21,
    "wrinkle_grade_glabella": 0.33,
    "wrinkle_grade_eye_image_left": 0.72,
    "wrinkle_grade_eye_image_right": 0.12
  },
  "skinType": {
    "label": "oily",
    "probabilities": [0.20, 0.30, 0.50],
    "roiCount": 3,
    "scoreType": "mean_uncalibrated_softmax"
  }
}
```

이 예시에서는 양 볼의 모공값이 0과 1이므로 모공 대표 상태는 1이다. `0.68`은 유의 클래스 모델 점수이며 심각도 68점이라는 의미가 아니다.

이전 `mobile-v3` 등은 모공·색소 0~5, 주름 0~6 등급을 쓰므로 v4와 혼합하지 않아야 한다. 별도의 과거 서버 여드름 결과 형식도 존재하지만 현재 모바일 v4의 아홉 부위 출력과 구분한다. 근거: `types/skin.ts`, `modules/skin-analysis/android/src/main/java/expo/modules/skinanalysis/SkinEngine.kt`, `SkinDecoding.kt`, `lib/skinReport.ts`.

## 2. 설문 보정과 최종 결과

현재 `skin-support-1` 설문은 세안 후 당김, 오후 T존 유분, 볼 상태, 유분이 느껴지는 시점, 화장품 사용 후 반응, 최우선 관리 목표를 묻는다. 원본 선택지와 버전은 `constants/skinSurvey.ts`에 있다.

v4 프로필은 분석 결과와 설문으로 `fuseSupportSkinType`을 호출하고 `fusion.type`을 최종 타입으로 보관한다. **모공·색소·주름의 이진 결과나 점수 자체를 설문으로 다시 계산하지 않는다.** 민감 반응은 별도 설문 신호로 사용한다.

`support-dry-oily-v1`의 현재 초기 규칙은 다음과 같다.

1. 건조 신호 = 세안 후 당김 점수 × 0.60 + 볼이 건조한지 여부 × 0.40.
2. T존 신호 = 오후 유분 점수와 유분 시작 시점 점수의 평균. 유분 신호 = T존 신호 × 0.75 + 볼이 유분 상태인지 여부 × 0.25.
3. 한 신호가 0.60 이상이고 다른 신호가 0.30 이하여야 건성 또는 지성 방향을 선택한다. 양쪽 모두 높거나 응답이 모호하면 보정하지 않는다.
4. 모델 상위 두 점수 차이가 0.10 이내이고 보정 대상과 최고 점수 차이도 0.10 이내일 때만 혼합한다. 보정 가중치는 `0.10 × |건조 신호 − 유분 신호|`로 최대 0.10이다.
5. 보정 결과의 최댓값이 `fusion.type`이다. 모델이 없으면 `unknown`, 설문이 없거나 조건에 맞지 않으면 모델의 기존 라벨을 유지한다.

이 공식은 **검증되지 않은 초기 휴리스틱**이며 정확도 개선이나 임상적 의미가 입증된 보정은 아니다. 버전 2의 과거 SOS 기반 보정과 버전 3의 보정 없는 모델 라벨은 별도 경로다. 근거: `lib/skinSupportFusion.ts`, `hooks/useSkinAnalysis.ts`, `lib/skinSurvey.ts`, `lib/skinReport.ts`.

현재 추천 요청은 `primaryGoal`, `secondaryGoals`, `skinType`, `irritationSignal`, `goalPolicyVersion`, `limit`을 보낸다. 원본 설문·모델 점수·얼굴 이미지가 추천 API 입력에 포함되지는 않는다. 모델 점수로 제품의 효능 가중치를 계산하는 기능은 현재 없다. 근거: `lib/skincare.ts`, `backend/api/app/schemas/skincare.py`.

## 3. 제품 DB 구조와 실제 데이터

2026-11-05 로컬 DB 조회 결과 `products` 7,688건, `raw_oy_product_option` 21,951건, `raw_oy_ingredient` 9,185건, `raw_oy_option_ingredient` 715,482행이다. 성분 연결이 하나 이상인 옵션은 18,980개다. 연결 행이 있는 것만으로 전성분이 완전하다고 단정할 수 없다.

| 테이블 | 주요 연결과 역할 |
| --- | --- |
| `raw_oy_product` | `goods_no` 상품 ID와 `std_category_code` 원천 세부분류 |
| `raw_oy_product_option` | `option_id` 옵션 ID와 `goods_no` 상품 연결 |
| `raw_oy_product_notice` | 상품별 `ingredients_raw` 원천 전성분 문자열 등 상품 고시 정보 |
| `raw_oy_ingredient` | `ingredient_id`, 성분 이름과 정규화 이름 |
| `raw_oy_option_ingredient` | `(option_id, ingredient_id)` 연결 및 원문 표기 순서 `seq` |
| `products` | 앱 카탈로그. 기존 빌더는 상품 ID `oy-` + 소문자 `goods_no`로 원천 상품과 연결 |
| `rec_ingredient_link` | 추천 성분 코드와 수집 성분 ID의 연결. 수동 연결에는 검수자와 날짜가 필요 |
| `rec_mapping_ingredient` / `rec_concern_match` | 매핑별 구성 성분과 옵션 단위 일치 결과 |

실제 로컬 예시로 `A000000002839` 바이오더마 센시비오 토너는 `스킨/토너`, 옵션 `A000000002839-001`에 성분 연결 14개가 있다. `A000000002848` 바이오더마 세비엄 포어 리파이너는 원천 분류 `크림`, 옵션 `A000000002848-001`에 연결 33개가 있다. 이 수는 DB 연결 행 수다.

`raw_oy_option_ingredient`에는 별도의 성분 함량·농도·배합비 컬럼이 없다. `seq`는 전성분 표기 순서로 함량값이 아니다. 성분명 텍스트 중 `%` 또는 `ppm`이 들어 있는 이름은 284개지만, 이는 문자열에 표시가 있다는 뜻일 뿐 제품별 확정 농도나 배합비로 사용할 수 없다. `raw_oy_product_notice.ingredients_raw`에도 원문이 보관되나 구조화된 검증 농도는 아니다.

원천 세부분류는 `std_category_code`에 있고 현재 카탈로그 대상 중 `스킨/토너` 373건, `에센스` 937건, `로션` 140건, `크림` 728건이다. 숫자는 원천 상품 기준이다. 현재 서빙 manifest는 `에센스`를 `essence`로 분류하며 원천 분류만으로 모든 세럼·앰플을 별도 구분한다고 볼 수 없다. 이름 기반 세트·기획 제외 규칙은 추가 검수가 필요하다. `skincare_serving`은 상품별 행이 아니라 추천용 옵션과 매핑을 한 행의 JSONB `payload`로 발행한다.

## 4. Neo4j와 PostgreSQL의 현재 경계

현재 PostgreSQL이 상품·옵션·성분·검수 매핑의 원본이다. `skincare_serving`을 기초 추천 API가 사용한다. Neo4j는 챗봇의 상품·대표 성분·태그·룩 관계 사본이며, 현재 동기화는 상품과 룩 API를 읽는다. 옵션별 전성분 전체와 `rec_*` 매핑·논문 근거가 그래프에 동기화된 상태라고 가정하면 안 된다.

Neo4j로 관계 탐색을 확장한다면 고민 → 검수된 매핑 → 정규화 성분 → 상품 옵션 → 상품 및 논문 근거를 ID와 버전으로 보존하는 동기화 계약이 별도로 필요하다. 조합은 같은 옵션의 구성 성분 전체 일치를 확인하고, 승인·재검수·운영 플래그와 출처를 함께 전달해야 한다. 현재 자료만으로 함량·임상 효능 점수나 개인 심각도 가중치를 산출할 수 없다. 근거: `docs/ARCHITECTURE.md`, `docs/recommendation-data-requirements-v0.3.md`, `backend/chatbot/app/services/graph_sync_service.py`.
