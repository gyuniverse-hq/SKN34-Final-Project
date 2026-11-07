# 하이라이터·쉐딩 내 얼굴 맞춤 + 유튜브 화장법 연결 — 계획과 진행 상황 (Cursor 인수인계용)

> 작성 2026-11-04 · 브랜치 `feat/ar-highlighter-contour-face-fit` (`origin/develop` 5da5f48에서 분기, 커밋 없음)
> 이 문서는 커밋하지 않는 작업 메모다. 진행하면서 "진행 상황" 절을 갱신한다.

## 0. 먼저 읽을 것
- `CLAUDE.md` → `AGENTS.md`: 원칙, 레이어 규칙, 검사 명령(`npm run check`)
- `docs/AR_SPEC.md` 1장(절대 원칙), 6-5-4(부위별), `docs/AR_ZONES.md`, `docs/AR_PROGRESS.md`
- `CONTRIBUTING.md` v1.3: 브랜치 `<type>/<설명>` 번호 없음, 커밋 `<type>: <한국어>` Scope 없음, PR 필수 항목 **변경 사항·영향 범위**, `develop`에 직접 푸시 금지
- 계획 원본: `C:\Users\playdata2\.claude\plans\expressive-sniffing-hollerith.md`

## 1. 목표
1. **일반 AR:** 내 얼굴 측정값(비율·볼륨)으로 하이라이터(볼륨)와 쉐딩(음영)의 위치·모양을 부위별·스타일별로 정해 바른다.
2. **룩:** 유튜브 화장법을 **레시피(의도)** 로 저장하고 내 얼굴에 펼쳐 씌운다.
3. 하이라이터·쉐딩에서 검증되면 같은 파이프라인에 나머지 부위(아이라인→블러셔→아이섀도→립→아이브로우→파운데이션)를 연결한다.

## 2. 지켜야 할 원칙
- 얼굴 영상·사진은 기기 밖으로 보내지 않는다(1-4). 서버에는 숫자만.
- 얼굴형 보정·피부 밝히기 금지(1-3). 제품 색을 정해진 자리에 얹을 뿐이다. **색 값(hex)은 바꾸지 않는다.**
- Expo Go 범위: 새 네이티브 모듈 금지. 앱 **런타임에서 LLM 호출 금지**(속도, 1-4).
- 새 동작은 `TUNING` 스위치로 켜고 끈다. 끄면 기존 렌더와 **픽셀 동일**(20쌍 립 + 90장 4부위 오프라인 렌더로 확인).
- 측정하지 않은 값은 "미측정". 추정·실측을 구분해 적는다.
- `components/ar/faceTrackerHtml.ts`는 템플릿 문자열이다: 백틱과 `${`를 새로 넣지 않는다. 고친 뒤 `npx jest __tests__/faceTracker.test.ts`.
- 영어 문구에 아포스트로피(`can't`)를 작은따옴표 문자열 안에 쓰지 않는다. UI 문구는 `lib/i18n` 4개 언어(en, ko, ja, zh) 모두에.
- **커밋·푸시는 사용자가 요청할 때만.** 요청 시 CONTRIBUTING.md 규칙을 따른다.
- **커밋에 넣지 않는 파일:** `scripts/data/vishue_db_20261104.dump`(DB 덤프), `docs/AR_EVALUATION_AUDIT.md`, `docs/VISHUE_AR_평가지표_v2.1_근거기반.pdf`, `research/eval_matrix/`, 이 문서.

## 3. LLM이 들어가는 위치
| 단계 | 역할 | 위치 |
|---|---|---|
| 3단계 레시피 추출(핵심) | Gemini가 유튜브 영상을 보고 시점·부위·스타일·세기·제품 계열을 구조화 JSON으로 추출, 3회 다수결 | 백엔드 배치(`backend/api/app/jobs/`), 팀 검수 후 저장 |
| 6단계 대화형 조정 | 자유로운 말 → `geometry` | 챗봇 백엔드(`llm_client.py`) |
| 4단계 평가 | 직접 쓰지 않음, 추출 결과를 YouMakeup 정답과 비교 | `research/` |

## 4. 사용자 결정 (11-04)
1. 유튜브 추출: **백엔드 배치 + Gemini**. 검수 후 기존 룩 테이블에 저장, 앱은 저장된 레시피만 읽는다.
2. 제품 데이터: **올리브영 원천 데이터에서 하이라이터·쉐딩을 찾아 부위 태깅**, 색이 부족하면 데모 팔레트 색(추정·데모 표시).
3. 얼굴 측정 결과: 얼굴형 이름은 쓰지 않고 **바르는 위치 추천 문구**만 보여 준다.
   - **11-06 변경(사용자):** 쉐딩 패널에 한해 얼굴형 이름(확률 없음)을 보여 준다. 분석 중 "기본 쉐딩 · 얼굴형 분석 중", 실패 시 "기본 쉐딩 유지". 하이라이터는 그대로 위치 문구만. 근거·한계는 `docs/AR_SPEC.md` 6-5-4 11-06 단락.
4. 원천 데이터 확인 방법: **Docker를 켜고 DB 덤프에서 확인**(임시 컨테이너, 확인 후 삭제).

## 5. 단계 계획
| 단계 | 내용 | 합격 기준 |
|---|---|---|
| **0. 데이터·스키마** | ① 카탈로그 부위 태깅(하이라이터·쉐딩) ② `types/index.ts` `ZoneGeometry`에 `hlStyle`·`contourStyle` ③ `look_ar_settings`에 `geometry` JSON 열(Alembic `0015`, 모델 `backend/api/app/models/idol_look.py`) ④ `docs/AR_SPEC.md` 6-5-4·`docs/AR_ZONES.md` | 두 부위에 실제 제품 칩. 백엔드 `ruff`·`lint-imports`·`pytest`·`alembic upgrade head`+`check` 통과 |
| **1. 얼굴 측정 + 템플릿** | `faceTrackerHtml.ts`에 `measureFaceShape()`(랜드마크 비율, 세션 안정화 후 고정), 템플릿 해석, `paintMasks()`의 `highlight`·`contour`·`area*` 레이어(약 804~913행)를 템플릿·측정값으로 그림. `TUNING.faceFit`(기본 끔). `lib/arFacePalette.ts` 영역 토글→스타일 칩, `app/(tabs)/ar.tsx` 칩·추천 문구, `lib/i18n` 4개 언어 | 끄면 픽셀 동일, 영역이 기준 랜드마크에 붙음(차이 지도), 고개 30° 영상에서 떨림이 립 수준 이하 |
| **2. 볼륨 반영** | 정점 법선·곡률로 진하기 조절, `uLightConf`로 빛 방향 영향 제한. `TUNING.hlContourVolume`(기본 끔) | 전후 FPS 비교, 끄면 픽셀 동일 |
| **3. 유튜브 레시피 추출** | `gemini_client.py`, `look_recipe_service.py`, `extract_look_recipe.py`. 기존 `youtube_client.py`·`match_video_products.py` 재사용. 3회 다수결, `unreviewed`로 저장 → 검수 후 공개. 계약은 `backend/chatbot/app/schemas/style_recipe.py`(`RecipeStep`·`Zone`)와 맞춤. 앱은 `lib/idolLooks.ts` `idolLookAsCelebLook`이 `arSettings.geometry`를 넘기게 | 스키마·다수결·검수 전 비공개 단위 테스트, 실제 영상 5개 수동 확인 |
| **4. 추출 정확도 평가** | YouMakeup 표본으로 부위·순서 일치율(합격선은 측정 후) | 결과는 `research/` 아래에만 |
| **5. 다른 부위 연결** | 공통 파이프라인 + 부위별 번역기(영상 표현→`geometry`) | 부위별 정확도 따로 측정. **코드 연결 완료(11-04)** — 추출 정확도는 4단계 정답이 있을 때 |
| **6. 대화형 조정** | `lib/arChatAdjust.ts` 규칙 확장, 챗봇 `ar_command_service.py`를 `set_geometry`로 확장 | 로컬 표현 50개+ 통과. **챗봇 set_geometry는 미완** |

## 6. 스타일 템플릿(데이터) 초안
- 하이라이터: 내추럴 광대, 물광 C존, 콧대·코끝, 애교살, 큐피드 활, 이마 중앙
- 쉐딩: 내추럴, 광대 쉐딩, 코 쉐딩, 턱선, 헤어라인
- 각 템플릿 = 기준 랜드마크·방향·길이·폭·부드러움·세기 배수. 측정값으로 길이·각도·위치만 조정. `lib/linerLooks.ts`의 `LINER_LOOKS` 패턴을 따른다.

## 7. 진행 상황 (갱신 대상)

### 끝난 것
- [x] 계획 승인(11-04), 브랜치 `feat/ar-highlighter-contour-face-fit` 생성(`origin/develop` 5da5f48). 이 브랜치는 `develop`을 추적하도록 설정돼 있어 푸시할 때 `git push -u origin feat/ar-highlighter-contour-face-fit`로 이름을 명시한다.
- [x] 코드 읽기:
  - 하이라이터·쉐딩 마스크는 `components/ar/faceTrackerHtml.ts` `paintMasks()`에 UV 마스크로 한 번 그림(약 804~913행). 영역 4개(`areaForehead/Nose/Under/Chin`)는 `geometry.areas`, 세기는 `geometry.intensity`.
  - `types/index.ts` `ZoneGeometry`(139행)에 `areas`·`intensity`만 있고 스타일 필드 없음.
  - `look_ar_settings`(`backend/api/app/models/idol_look.py`)는 `hex`·`intensity`·`texture`만 저장 → 스타일 저장 불가.
  - 챗봇 레시피 계약 `backend/chatbot/app/schemas/style_recipe.py`는 이미 9개 부위 `Zone`을 가진다.

### 발견한 사실 (0단계 ①)
- **현재 `backend/api/seed/catalog.json`(7,688개)의 원천 카테고리(`tags[1]`)에는 하이라이터·쉐딩·컨투어 카테고리가 없다.** 메이크업은 쿠션·파운데이션·블러셔·마스카라·아이섀도우·아이브로우·아이라이너·립류뿐이다.
- 부위 매핑 표 `ZONE_BY_CATEGORY`(`backend/api/app/schemas/oy_catalog.py`)에도 하이라이터·쉐딩이 없어서, 원천에 그 카테고리가 있어도 `skipped_unknown_category`로 버려진다(`backend/api/app/services/oy_catalog.py` `build_oy_catalog`).
- 옛 스크립트 `scripts/data/oliveyoung/build_catalog.py`는 `"하이라이터"`, `"쉐이딩"`을 `("cheek", None)`으로 매핑한다 → 원천(제품 유형 소분류)에는 있었을 가능성이 크다. 수집기 `collectors/oliveyoung_color_poc16.py`의 중분류는 립/베이스/아이 메이크업 3개.
- 이름에 하이라이터·쉐딩·컨투어가 들어간 제품은 19개뿐이고 대부분 블러셔·파운데이션으로 분류돼 있다.
- 원천 CSV는 이 PC에 없다. DB 덤프 `scripts/data/vishue_db_20261104.dump`(19MB, `raw_oy_*` 포함)만 있다. 수집 허용 범위 문의 답변이 아직 없어서 새 수집은 하지 않는다(`scripts/data/oliveyoung/README.md`).

### 덤프 확인 결과 (11-04, 완료. 임시 컨테이너는 삭제함)
임시 `postgres:17-alpine` 컨테이너에 덤프의 `raw_oy_*`·`oy_catalog_category_rule`만 복원해 읽었다. (덤프 소유자 역할 `vishue`가 없어서 `CREATE ROLE vishue` 후 `pg_restore --no-owner --no-privileges -t <표>`.)
- **원천에 하이라이터·쉐이딩이 이미 수집돼 있다.** `raw_oy_product.std_category_code`(표준 카테고리)가 `하이라이터` 72개, `쉐이딩` 41개. 표시 카테고리도 따로 있다(`뷰티 > 메이크업 > 베이스메이크업 > 하이라이터 / 쉐이딩`). `oy_catalog_category_rule`(21개 규칙)에도 둘 다 등록돼 있다.
- **그런데 서빙 카탈로그에는 하이라이터 1, 쉐이딩 0만 들어갔다**(`is_in_catalog`). 이유: `ZONE_BY_CATEGORY`(`backend/api/app/schemas/oy_catalog.py`)에 두 이름이 없어 `build_oy_catalog`이 `skipped_unknown_category`로 버린다.
- **색은 충분하다.** HEX 있는 옵션: 하이라이터 253/295(제품 56/72), 쉐이딩 103/126(제품 29/41). 색 출처는 `swatch` 292, `color_chip` 64, `none` 65. → **데모 팔레트 없이 실제 제품 칩을 쓸 수 있다.**
- 부수 발견(범위 밖, 데이터 담당에게 알릴 것): `파우더/팩트` 92개, `컨실러` 72개, `프라이머/베이스` 148개, `BB/CC` 65개, `메이크업 픽서` 40개도 같은 이유로 대부분 카탈로그에 없다.
- 이상치: 하이라이터 표준 코드가 `블러셔` 카테고리 제품 1개에, 쉐이딩 코드가 `컨실러` 카테고리 제품 1개에 붙어 있다. 규칙을 `category_name` 기준으로 할지 `std_category_code` 기준으로 할지 정해야 한다(현재 백엔드는 `category_name` 기준).

### 지금 막힌 곳 / 다음에 할 일
1. (해결됨) 0~5단계 코드, 6단계 로컬 채팅. 4단계 정확도 수치는 팀 gold/YouMakeup이 없어 없음.
2. (해결됨) 챗봇 `set_geometry`: 닫힌 스타일 id만. 립 `set_intensity` 테스트 유지.
3. Expo Go: 하이라이터·쉐딩 스타일 칩·채팅 문구·시연 룩 6선·룩 마스카라(실기기 미검증).
4. 검수 파일 스타일 채우기 → `apply_look_recipe` → 앱에서 룩 적용 확인. 시연 6선 매핑은 사람 검수 전.

## 8. 환경 메모
- 오프라인 평가 도구 `research/lip_reference/*`, `research/data/ar_eval_public/hw01_raw`, 얼굴 모델 파일은 이 브랜치에 없다(커밋 `895bae2`, `final` 원격에 있음). 필요하면 **비어 있는 새 폴더**에 `git archive 895bae2 research/lip_reference research/data/models research/data/ar_eval_public/hw01_raw research/data/ar_eval_public/tools | tar -x -C <새 폴더>`로 풀고 `LIGHT_EVAL_TOOLS_ROOT`를 그 폴더로 지정한다(`research/light_eval/lighteval.py`).
- 조명 추정은 측면 빛의 좌우 각도를 과대 추정한다(합성 60° → 약 80°). 하이라이터의 빛 방향 의존은 `uLightConf`로 제한하고, 조명 개선(`AR_조명추정_개선_지시서.md` 2·3단계)을 먼저 하는 편이 낫다.
- 모든 AR 변경은 실기기(Expo Go) 미검증이 기본값이다. 자연스러움은 오프라인 지표로 판정할 수 없고 설문·실기기가 필요하다.

## 진행 기록 (11-04, 0단계 완료)
- 0①: `ZONE_BY_CATEGORY`에 블러셔·하이라이터·쉐이딩·아이섀도우 추가 + 테스트. 시드(`backend/api/seed/catalog.json`)와 `lib/devCatalog/oyCatalog.json`에 새 제품 112개만 덧붙임(기존 제품 바이트 동일, imageUrl은 시드의 `thumbnails10/` 형태 유지). 하이라이터 55개/쉐딩 28개. `__tests__/demoCatalog.test.ts` 부위 목록에 두 부위 추가.
- 0②: `types/index.ts`에 `HighlighterStyle`·`ContourStyle`, `ZoneGeometry.hlStyle`·`contourStyle`. 백엔드 `ZoneGeometry`에도 같은 필드.
- 0③: Alembic `0015_look_ar_geometry` (`look_ar_settings.geometry` JSON/JSONB, nullable), 모델·저장소가 geometry를 읽어 `ZoneSetting`에 실음. 임시 Postgres에서 upgrade/downgrade/upgrade + `alembic check` 통과(컨테이너 삭제함).
- 0④: `AR_SPEC` 6-5-4(위치 맞춤 ≠ 얼굴형 보정), `AR_ZONES` 수치, `AR_PROGRESS` 한 줄.
- 검증: `npm run check` 통과, 백엔드 ruff·lint-imports·pytest 통과.
- 다음: 1단계(얼굴 측정 + 스타일 템플릿, `TUNING.faceFit` 기본 끔). 커밋은 사용자가 요청할 때만.

## 진행 기록 (11-04, 1단계 1차 구현)
- `faceTrackerHtml.ts`: `HL_TEMPLATES`(6종)·`CONTOUR_TEMPLATES`(사용자 지정 3종: jawline·nose·hairline) 데이터 + `drawTemplate` 해석기, `faceFitFrom`(비율→배수·추천 키), `faceFitStep`(정면 프레임 24개 평균 후 고정, 2.5초 얼굴 없으면 재측정, `face_fit` 메시지로 비율·키만 전송), `repaintHlContour`(mask2 R·G만 다시 그림, 스타일·측정이 바뀔 때만). `TUNING.faceFit: true`이지만 스타일을 고르지 않으면 기존 레이어 그대로(픽셀 동일).
- 앱: `lib/faceFit.ts`(스타일 id, `parseFaceFit`), `ArFaceView(.web).tsx` `onFaceFit`, `app/(tabs)/ar.tsx` 하이라이터·쉐딩 탭에 스타일 칩(기본 + 템플릿)과 추천 문구 한 줄, i18n 4개 언어.
- 사용자 지시: 쉐딩 스타일은 V라인 턱선·콧대 오목·헤어라인 3개만. 효과 문구(갸름·작아 보이게)는 1-3 때문에 쓰지 않음.
- 미검증: 템플릿 랜드마크 위치(오프라인 렌더·실기기 모두 미측정), 측정 기준비(`faceFitRefs`)는 휴리스틱.
- 다음: 오프라인 렌더(LaPa 정면·좌우)로 템플릿 위치 확인 → 실기기 Expo Go 확인 → 2단계(볼륨).
- 11-04 (실기기 피드백 "쉐딩 칩 눌러도 안 보임"): 오프라인 렌더(headless Chrome, hw01 정면 사진, 맨얼굴과 픽셀 차이)로 재현. 원인: 턱선 스트로크가 얼굴 윤곽 위에 있어 가장자리 페이드(`faceEdgeFadePx`)에 지워짐(차이 1픽셀), 콧대·헤어라인은 너무 가늘고 옅음. 수정: `inset`(얼굴 안쪽 점 쪽으로 당김) 도입, 선 굵기·알파 상향. 재측정: 턱선 9,947px·콧대 15,037px·헤어라인 23,568px(차이>8) → 눈으로 보임. 하이라이터 일부(콧대·큐피드 활)는 아직 차이가 거의 0이라 같은 방식으로 손볼 필요(미수정). 렌더 도구는 scratchpad `render_shade.py`.

## 진행 기록 (11-04, 2단계 볼륨)
- `faceTrackerHtml.ts`: `TUNING.hlContourVolume`(기본 끔), `volumeGain [0.6, 0.5]`, `volumeLight 0.7`. 셰이더에 `volFace`(카메라를 향하는 정도 n.z와 빛 방향 dot(n,l)을 `uLightConf*uVolLight`로 섞음) → 쉐딩은 면이 돌아간 곳을 더 진하게(0.6~1.5배), 하이라이터는 앞을 향한 곳을 더 진하게(0.7~1.4배). 끄면 uniform이 0이라 배수가 정확히 1.
- 측정(headless Chrome, hw01 정면 2장, 쉐딩 3종·하이라이터 5종·둘 다): 끈 상태가 2단계 이전 셰이더와 **픽셀 최대 차이 0**. 켠 상태는 턱선·헤어라인 쉐딩이 평균 +10~40% 진해지고(최대 픽셀 차이 12~29), 하이라이터는 정면 사진에서 약간 약해짐. 변화가 작아 정면 사진으로는 "자연스러워졌다"를 판정할 수 없음 → 켤지는 실기기(옆 얼굴·측면 조명)로 결정. 기본은 끔.
- 11-04 (1단계 마무리): 하이라이터 콧대·코끝(`nose_tip`)과 큐피드 활이 거의 안 보이던 것을 크기·진하기 상향으로 수정(밝은 색 기준 달라진 픽셀 3,905→8,822, 136→약 7,000). 큐피드 활은 인중 위 가로 타원. 하이라이터 전체는 원래 은은함(coverage 0.5×혼합 0.35)이라 실기기에서 세기 확인 필요.

## 진행 기록 (11-04, 3단계 유튜브 레시피 추출 — 백엔드 구현)
- `backend/api`: `schemas/look_recipe.py`(zone·style·intensity·시점, 스타일은 부위에 속한 id만 허용, 모르는 값은 버림), `clients/gemini_client.py`(키는 여기서만, 공개 영상 URL+프롬프트만 전송), `services/look_recipe_service.py`(3회 추출 → `vote_recipes` 다수결: 부위는 과반, 스타일은 과반 아니면 비움, 시점·세기는 중앙값 / 승인된 항목만 `apply`), `jobs/extract_look_recipe.py`(검수 파일 `seed/source/look_recipe_review.json`에 unreviewed로 저장, 승인된 항목은 덮어쓰지 않음), `jobs/apply_look_recipe.py`(approved + reviewer + lookId 있는 항목만, 룩에 이미 있는 부위 설정에 `hlStyle`/`contourStyle`/세기만 병합, 색은 만들지 않음), `idol_look_repository.merge_geometry`, 룩 응답이 모든 부위 설정을 싣도록 확장(이전엔 입술·블러셔·섀도만), `.env.example`에 `GEMINI_API_KEY`.
- 테스트: `tests/test_look_recipe.py` 8개(다수결, 부위 밖 스타일 버림, 모르는 부위 거부, 요청에 공개 URL만, 스키마 밖 응답, 키 없음, 승인 규칙, 색 없는 부위 건너뜀). Gemini는 모의. `ruff`·`lint-imports`·`pytest 259` 통과.
- **미실행:** 실제 Gemini 호출은 해 보지 않았음(키 없음). 모델 기본값 `gemini-2.5-flash`는 `GEMINI_MODEL`로 바꿀 수 있고, 현재 사용 가능한 이름인지 확인 필요. 영상이 실제로 맞게 읽히는지, 3회 다수결로 충분한지는 4단계(YouMakeup 정답 비교)에서 측정 예정.
- 앱: `idolLookAsCelebLook`이 `arSettings` 전체(geometry 포함)를 그대로 넘기므로 앱 코드 변경 없이 룩→AR에 적용됨(저장된 스타일이 있을 때).
- 다음: 키가 있으면 실제 영상 5개로 추출 → 검수 → 앱 적용 수동 확인. 그다음 4단계 평가.

## 진행 기록 (11-04, 4단계 평가 — 도구만, 실측 미실시)
- `research/recipe_eval/score_recipes.py`(+ `test_score_recipes.py` 5개 통과): 검수 파일(추출 결과)을 사람이 만든 정답과 비교. 부위 정밀도·재현율·F1, 순서(최장 공통 부분수열 비율), 시점(±초 허용, 기본 10), 스타일 일치(예측 스타일 없음은 오답). 합격선은 숫자가 나온 뒤 정함. 아무것도 외부로 보내지 않음.
- **YouMakeup은 못 받음:** 데이터는 서명한 라이선스 양식을 메일(youmakeupvqa@163.com)로 보내야 링크가 오고, 코드는 MIT지만 데이터 조건은 별도(https://github.com/AIM3-RUC/YouMakeup). 주석 필드명도 저장소 첫 화면에 없어서 변환기는 파일을 받은 뒤 작성해야 함. 상업 이용 가능 여부는 양식으로 확인 필요.
- 지금 가능한 대안: 팀이 영상 5~10개를 직접 보고 gold.json(부위·시점·스타일)을 만들면 같은 도구로 바로 측정 가능. 추출 결과(Gemini 키 필요)와 정답 둘 다 아직 없어 **정확도 수치는 없음.**

## 진행 기록 (11-04, 3단계 A+B: 설명란 규칙 추출 + 팀 검수)
- Gemini 대신 **설명란 챕터 규칙 추출**(A) 추가: `services/description_recipe_service.py`, `jobs/extract_look_recipe.py --source description`(기본, `YOUTUBE_API_KEY`), `--ids-file`. 챕터(타임스탬프 3줄 이상)에서 부위·순서·시점을 뽑고, 스타일은 **같은 챕터 줄에 적혀 있을 때만** 채움(없으면 비움). 챕터가 3줄 미만이면 항목을 만들지 않음. 테스트 5개 추가(`tests/test_description_recipe.py`), 백엔드 264 통과.
- 실행 결과(등록 영상 107개 = `celebrityVideos` 34 + `styleLooks` 73, 공식 API로 설명란만 읽음): **챕터 있는 영상 24개(22%)**, 초안 24건 → `backend/api/seed/source/look_recipe_review.json`(미승인). 쉐딩 20건·하이라이터 16건 포함. **스타일이 채워진 단계는 0개**(챕터가 "쉐딩"처럼 부위만 적음). 83개는 챕터 없어 초안 없음.
- B(팀 검수): `research/recipe_eval/review_links.py`가 쉐딩·하이라이터 단계마다 시점 링크 목록을 출력. 검수자는 링크에서 스타일을 확인해 검수 파일의 `style`, `approved: true`, `reviewer`, `lookId`를 채우고 `app.jobs.apply_look_recipe` 실행. 검수 결과는 그대로 4단계 정답(gold)으로도 변환 가능.
- 한계: 설명란 방식은 영상 속 동작을 보지 못함. 스타일은 사람 몫. 챕터 없는 83개는 Gemini(영상 직접 보기) 또는 사람이 봐야 함. 한 영상(TzwB0xglsAo)은 1단계뿐이라 신뢰도 낮음.

## 진행 기록 (11-04, 5단계 부위 번역 + 6단계 로컬 대화)
- 5단계: `geometry_for_style`이 하이라이터·쉐딩뿐 아니라 아이라인(`LINER_LOOKS`와 같은 숫자)·블러셔 위치·섀도 마무리·립(풀/오버립/중앙)을 geometry로 옮김. 설명란 챕터 단어도 같은 표. Gemini 프롬프트·enum도 맞춤. 색은 여전히 만들지 않음.
- 6단계: `lib/arChatAdjust.ts`가 칠해진 부위에만 geometry·진하기를 적용(색 hex 없음). 표현 50개+ 단위 테스트. 앱이 `patchGeometry`로 반영. i18n 4개 언어.
- 챗봇 `set_geometry`: 스타일 id만 받고 서버가 geometry를 붙임. 앱 스토어·`useArCommand`가 칠해진 부위에 반영. 기존 립 강도 경로 유지.
- 시연 룩 6선: `lib/demoLookAr.ts`가 카탈로그 productId·shadeId로 8부위+마스카라를 칠함. mappingVerified는 그대로. 마스카라는 탐색 칩 없이 룩 카메라만. 영상 SKU에 hex가 없으면 카탈로그 hex가 있는 마스카라 셰이드를 씀.
- 검증: `npx jest __tests__/arChatAdjust.test.ts`, `backend/api` look_recipe·description_recipe 테스트.

## 진행 기록 (11-04, 룩 전용 마스카라)
- 카메라가 룩의 `makeup.mascara`를 칠함. AR 탐색 칩·상품 시착은 마스카라를 고르지 않음.
- 눈썹은 눈 캔버스 A, 마스카라는 G. 시연 6선은 hex가 있는 카탈로그 마스카라만 연결(영상 SKU hex 없음).
- 검증: `npm run check`(73/725). Expo Go 미검증.

## 진행 기록 (11-04, 유튜브 마스카라 모양)
- 프레임을 픽셀 재지는 않고, 영상에서 쓴 마스카라 제품 유형을 닫힌 스타일로 옮김: `lib/mascaraLooks.ts`. 렌더러가 이미 쓰는 `length`·`thickness`·`lower`.
- 시연 6선: 딸기토끼·윈터 `slim`(네오젠 슬림 메탈), 연말 `long`(킬래쉬), 청초 `fine`(파인, 아래속눈썹 없음), 카리나 `volume_skinny`(볼륨 업 스키니), 설윤 `long_curl`(컬픽스).
- 레시피·챗봇·로컬 채팅도 같은 id. hex는 그대로 카탈로그 값.
- Expo Go 미검증. 커밋은 요청 시.

## 진행 기록 (11-04, Gemini 실제 실행)
- 모델: `gemini-2.5-flash`는 신규 사용자 제공 종료(404) → 기본값 `gemini-3.6-flash`(3.7·3.8은 당시 503 혼잡, 3.5도 동작). 503·429는 10/30/60초 재시도(테스트 2개 추가, 백엔드 266 통과).
- 영상 5개 × 3회 다수결(결과는 scratchpad, 저장소에 안 넣음): 4개 성공, 1개(4QR0tre9yBI) 재시도 후에도 503.
  - 성공 4개 모두 **부위 3/3 만장일치**(일관성). temperature 0.2라 회차 간 비슷한 게 당연해서, 만장일치가 정확도를 뜻하지는 않음.
  - 설명란 챕터 시점과 비교: 3개 영상은 대부분 ±10초 안, 1개(duuYlEDy0qU)는 전부 +16~93초 늦음. 챕터와 크게 다른 것(하이라이터 +316초, 섀도 -300초)은 챕터 쪽이 다른 걸 가리켰을 수도 있어 사람 확인 필요.
  - 쉐딩 스타일: nose 3건, jawline 1건 / 하이라이터: nose_tip 2, under_eye_smile 1. 정답 미확인(편향 가능성 있음).
- 결론: Gemini는 부위·순서·대략적 시점은 안정적으로 뽑고 스타일도 채움. 정확도는 팀 정답과 비교해야 판단 가능(4단계 도구 준비됨).
