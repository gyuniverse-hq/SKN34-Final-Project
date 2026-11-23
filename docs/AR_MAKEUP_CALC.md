# AR 부위별 메이크업 · 제형 계산 기준

렌더러(`components/ar/faceTrackerHtml.ts`)가 **지금 그리는 방식**을 부위·제형별로 정리한 계산 문서다. 서술·이력은 `docs/AR_ZONES.md`, `docs/AR_SPEC.md` 6-5, `docs/AR_PROGRESS.md`를 본다. **숫자·식이 다르면 이 문서와 코드가 우선**이다.

- 작성 기준: 2026-11-20 코드 (`TUNING`, `MATERIALS`, `SHADOW_*`)
- 색 공간: 카메라·제품은 선형에서 합성하고, Overlay/Soft Light만 sRGB에서 한다. sRGB↔선형은 정식 EOTF(2.2 근사 금지).
- 제품 hex는 바꾸지 않는다. 진하기 0이면 그 부위는 카메라 픽셀 그대로다.
- 카탈로그 제형 이름: `Texture` = `matte | velvet | cream | satin | sheer | glossy | shimmer` (`types/index.ts`). 실제 셰이더에 쓰이는 범위는 부위마다 다르다.
- 제형 선택: `shade.textureOverride ?? product.texture`. 립케어(오일·밤)만 제품 이름이 정한다(`lib/lipCare.ts`).
- 값은 실기기 튜닝 대상이다. Expo Go에서 확인하지 않은 항목은 확정값이 아니다.

---

## 1. 공통 합성 함수

조명색 `uLightColor`, 노출 `uExposure`, 피부 평균 밝기 `uSkinMeanLum`, 스와치 종이 반사 `uPaperWhite = 0.85`.

밝기 \(L(c) = 0.2126 R + 0.7152 G + 0.0722 B\).

### 1-1. `layer` — 불투명 안료

카메라 명암을 제품 색에 곱한다. 피부 결은 밝기 비율로만 남는다.

```
shade = clamp( L(cam) / max(refLum, ε), 0, shadeMax )
layer(cam, albedo) = albedo × uLightColor × shade × uExposure
```

- 파운데이션 `shadeMax` = `foundShadeMax` **1.2**
- 가루(`powder` 안) `shadeMax` = **1.6**

### 1-2. `powder` — 반투명 가루 (블러셔·쉐딩·눈썹 1층)

밝은 색이 어두운 피부 위에 잿빛 막이 되지 않게, 덮는 층과 **피부를 거르는 필름**을 섞는다.

```
tint  = cam × √(clamp(albedo / paperWhite, 0, 1))
powder = mix( layer(cam, albedo, skinMean, 1.6), tint, powderTint )
```

`powderTint` 기본 **0.4**. 쉐딩을 켠 동안 턱선은 **0.32**.

최종 픽셀:

```
col = mix(col, powder(cam, albedo), α)
```

### 1-3. `shadowPack` — 제품 AR 아이섀도 색

눈꺼풀보다 어두운 색은 곱하기 필름, 밝은 파스텔은 가루로 눈꺼풀을 밝힌다.

```
pw   = powder(cam, alb)
lift = shadowLift × clamp( 3 × (L(pw) − L(cam)) / L(cam), 0, 1 )
결과 = mix( col × clamp(alb / paperWhite, 0, 1), pw, lift )
```

영상 룩 섀도는 `shadowPack`이 아니라 `col × (색 / paperWhite)` 곱하기만 쓴다.

---

## 2. 진하기 → 덮는 양

슬라이더 `intensity` ∈ [0, 1]. 기본값 `store/makeupStore.ts` `DEFAULT_INTENSITY`.

| 부위 | 기본 intensity | 덮는 양 α |
|---|---|---|
| 립 | 0.65 | 아래 2-1. `a1` 누적 |
| 블러셔 | 0.45 | `intensity × blushCoverage(0.6)` |
| 아이섀도 | 0.45 | 마스크 × 제형 opacity (제품 AR은 `SHADOW_PRODUCT_OPACITY`) |
| 아이라인 | 0.85 | 코어 **1.0** (`EYELINER_DARK.opacity`, 진하기로 옅어지지 않음) |
| 마스카라 | 0.70 | `0.55 + 0.35 × intensity` (가닥 코어는 `lashCore` 0.92) |
| 하이라이터 | 0.50 | `intensity × hlCoverage(0.5)` × 입체감 0.7~1.4 |
| 쉐딩 | 0.55 | `intensity × contourCoverage(0.8)` (턱선만 ×0.85) × 입체감 0.6~1.5 |
| 아이브로우 | 0.70 | 마스크 가중 × `browCoverage` 1.0 |
| 파운데이션 | 0.45 | 커버력 막대가 `foundCoverage`·`foundOpaque` 구간을 보간 |

농도 막대는 블러셔 탭만 있다(0.15~1). 나머지는 룩 레시피와 기본값.

### 2-1. 립 덮는 양 (바르는 횟수)

`layersPerIntensity = 3` → 진하기 0.35 ≈ 1회, 0.85 ≈ 2.5회.

```
layers = max(0.3, intensity × 3)
cov    = 1 − (1 − a1)^layers
```

`a1` = 한 번 발랐을 때 입술을 덮는 비율(제형표). 립케어는 이 식을 쓰지 않는다(9장).

셰이더에서 픽셀 덮임:

```
cov_px = clamp(lipMask × uLipCov × uneven, 0, 1)
```

`uneven`: 매트는 주름 골에 `creaseCover 0.15`만큼 더 쌓이고, 글로시는 융기에서 얇아진다.

---

## 3. 립 (`lip`)

화면 윤곽 + UV. **스티커가 아니라 바른 것처럼**: 주름·윗입술 그늘·아랫입술 볼륨을 카메라에서 가져오고, 윤기만 제형이 정한다.

칩 UI: 매트(매트+벨벳) · 크림(크림+새틴) · 글로시(글로시+시어) · 쉬머 · 립케어. 렌더는 카탈로그 7종 + oil/balm 그대로 쓴다.

### 3-1. 제형 표 `MATERIALS`

| 제형 | roughness | specular | flake | a1 | translucent | detail | shadeMatch | opacity | overlay | cavity |
|---|---|---|---|---|---|---|---|---|---|---|
| matte | 0.90 | 0.35 | 0 | 0.72 | 0 | 1.15 | 0.5 | 0.97 | 0 | 2.0 |
| velvet | 0.75 | 0.45 | 0 | 0.66 | 0 | 0.75 | 0.6 | 0.97 | 0.35 | 2.5 |
| cream | 0.55 | 0.60 | 0 | 0.58 | 0.12 | 0.90 | 0.5 | 0.97 | 0.30 | 2.0 |
| satin | 0.42 | 0.85 | 0 | 0.50 | 0.12 | 1.05 | 0.5 | 0.96 | 0.20 | 2.3 |
| sheer | 0.32 | 0.90 | 0 | 0.38 | 0.80 | 1.05 | 0.3 | 0.75 | 0.15 | 2.2 |
| glossy | 0.16 | 1.15 | 0 | 0.46 | **0** (11-23, 이전 0.28) | 0.95 | 0.4 | 0.95 | **0.10** (11-23, 이전 0.20) | 1.2 |
| shimmer | 0.38 | 0.90 | 1 | 0.55 | 0.12 | 1.10 | 0.5 | 1.00 | 0 | 1.6 |
| oil | 0.08 | 1.30 | 0 | (미사용) | 1.00 | 1.00 | 0 | 1.00 | 0 | 1.0 |
| balm | 0.35 | 0.75 | 0 | (미사용) | 0.95 | 0.85 | 0 | 1.00 | 0 | 1.0 |

11-23 glossy 변경(사용자 결정, 후보 GC)
- FPMT를 AR 맨프레임에 돌린 "실제로 바른 입술" 목표와 비교했다(`research/makeup_gen/COMPARE_LOCAL.md`, `fpmt_gap.py`, `ar_tune_render.mjs`). glossy는 맨입술의 노란기가 비치고(b* 15.7, 목표 10.1) 빨강이 과했다.
- `translucent` 0, `overlay` 0.10으로 바꿨다.
  - 03 베어 그레이프 실측색: 목표 색차 3.56 → 2.28
  - 빨강 #B0283A: hex 대비 7.66 → 4.87(채도 62 → 46, hex 59.5)
  - 공식몰 기본값: hex 대비 4.06 → 4.55
- 얼굴 1명·착용 사진 1장 근거이고 헤드리스 렌더만 확인했다.

11-23 제형 광택 변경(사용자 결정, 립 제형 PLAN 추천안 D)
- **문제:** 폰 캡처에서 매트는 서리처럼 반짝이는 얼룩, 새틴·글로시는 윗입술 윗가장자리에 밝은 띠가 보였다.
- **원인(절제 실험):**
  - 매트: 매트에도 켜져 있는 형태 광택이 매트 마스크의 능선 가중(1.6배)을 받아 능선마다 밝은 점을 만들었다.
  - 새틴·글로시: 광택용 입술 형태 법선이 윗입술 윗선에서 위로 기울어, 정면 광원 반사가 그 띠에 몰렸다.
- **새 재질 값 2개** (없으면 1 = 이전과 같음):
  - `glossScale`: 형태 광택 배수
  - `rimTilt`: 광택에만 쓰는 윗입술 위쪽 기울기 배수. 색과 명암은 원래 형태를 그대로 쓴다.
  - 립오일·밤은 둘 다 1로 고정된다.
- **적용한 값:**
  - matte `glossScale` 0.3, `matteSpecMask` 능선 가중 0.6 → 0.2 (거칠기 0.8 초과인 매트에만 쓰인다)
  - satin `rimTilt` 0.3
  - glossy `rimTilt` 0.3. glossy `cavity`는 11-15 순서 규칙(글로시 < 크림)에 따라 1.2를 유지한다.
- **결과(헤드리스, 얼굴 5장 평균, `research/makeup_gen/finish_candidates.py`):**
  - 매트: 광택 면적 45 → 7%, 평균 밝기 증가 +2.0 → +0.8 L*, 결 세기 1.75 → 1.43, 색 변화 ΔE 1.05
  - 글로시: 윗입술 띠 26 → 14%(고르게 퍼졌을 때 약 14%), 최대 밝기 12.9 → 10.4 L*, 주름 따라가기 0.19 → 0.28
  - 새틴: 띠 22 → 12%, 최대 밝기 9.3 → 8.2 L*
- velvet·cream·sheer·shimmer는 그대로다. 폰 확인 전이다.

| 제형 | glossScale | rimTilt |
|---|---|---|
| matte | 0.3 | (1) |
| satin | (1) | 0.3 |
| glossy | (1) | 0.3 |
| 나머지 | (1) | (1) |

의미:

- **roughness** → 매끈함 `smooth = 1 − roughness`. 윤기 로브·하이라이트 유지량.
- **a1** → 한 번 바른 덮임.
- **translucent** 0 = 안료로 덮음, 1 = 염료 필터처럼 비침.
- **detail** → 카메라 주름 대비 유지. 1보다 크면 주름이 더 살아 있고, 작으면 메운다.
- **overlay** → 제품색 Overlay 레이어 세기(`lipOverlay` 켜짐). 어두운 픽셀은 Soft Light.
- **cavity** → 반사에 `(카메라밝기 / 주변3px)^cavity`를 곱해 주름 골은 덜 빛나게.
- **shadeMatch** → 표면 대비 맞춤. 입술 틈은 `lipSeamMatch`가 따로 처리.

### 3-2. 색 층 쌓기 (핵심)

가정: `카메라 = 조명 × 명암 × 맨입술색`. 맨입술색 `rPx`는 0.5초마다, 색 방향은 주변 5점.

```
paint  = mix(rPx, 제품색, cov)                          # 덮는 만큼 제품 쪽으로
filt   = clamp(제품색 / paperWhite, 0, 1)
mixCol = paint × mix(1, filt / L(filt), cov × translucent)  # 비치는 몫만 색조로 물들임
ratio  = clamp(mixCol / rPx, 0, ratioMax=4)
```

밝기 상한: 덮인 안료는 입술을 밝게 할 수 있다. 비치는 몫만 `lumGainMax 1.15`.

```
opaqueW = cov × (1 − translucent)
lumOnly = mixCol × gainScale × (L(camDiffuse) / L(rPx))
layered = mix(camDiffuse × ratio, lumOnly, cov) × fill
```

- 덮인 몫은 **카메라 밝기만** 가져온다(채널 비율을 쓰면 노랑·초록 반점).
- `fill`: detail로 주름을 메우거나 살림. 범위 clamp 0.6~1.6.
- 불투명 제형: 입술 두께 비율 8점 저역 밝기만 `opaqueShadeGamma`로 눌러 큰 얼룩을 줄이고 미세 결은 남긴다.

하이라이트 분리: 채도 낮고 (주변 3px보다 튀는 좁은 반사 **또는** 입술 평균 × 2.2 넓은 젖은 광). 매트는 넓은 반사를 덮고, 좁은 주름 반사는 모든 제형이 표면 결로 유지. `hlKeep`은 매끈함에 따라 다시 올림.

### 3-3. 윤기

- Lambert 볼륨: `lipVolume` × cov × 형태 법선 / 메시 법선 비.
- GGX 클리어코트 + 능선 글린트. 코팅(글로시)은 빛 색, 안료 윤기(새틴·크림)는 밝아진 제품 색.
- 두 로브: 광원 자체 또렷한 반사 + 주변 번짐. 상한 `glossMax`를 `smooth³`로 보간.
- 글로시만 방 조명 가로 띠 환경 반사(`envW`, smooth 0.6~0.8에서 켜짐).
- 쉬머: `flake = 1` 노이즈 반짝임, cavity와 같은 주름 감쇠.
- 매트만 `matteSpecMask [0.05, 0.6, 0.10]`: 국소 대비로 주름은 반사 0, 융기는 무광 반사(roughness > 0.8).

### 3-4. 립케어 (오일·밤)

색 덮임과 윤기를 나눈다.

```
색 cov  = (0.10 + 0.10 × intensity) × care.tint × 0.6     # 최대 약 12%
윤기 cov = 0.6 + 0.4 × intensity
```

`care.tint`: 칩이 입술색(핑크·레드 등, 채도 충분)일 때만 0~1. 포장색·placeholder는 0 → 맨입술색 유지, 윤기만.

오일/밤을 색 립 위에 올리면 매끈함은 둘 중 더 매끈한 쪽.

---

## 4. 블러셔 (`blush`)

UV 볼 타원. AR 탭은 **제형 칩 없이 색만**. 카탈로그 제형은 거칠기(`MATERIALS.roughness`)만 가장자리와 가루 윤기에 쓴다.

```
blushA = blushMask^blushPow × intensity × 0.6
blushPow = mix(1.7, 0.5, clamp((roughness − 0.16) / 0.74, 0, 1))
```

- 매트·벨벳(rough ≈ 0.9): 지수 큼 → 가장자리가 가루처럼 넓게.
- 글로시·시어(rough ≈ 0.16): 지수 작음 → 패치가 작고 크림처럼.

합성(제품 AR):

```
col = mix(col, powder(cam, blushAlbedo), blushA)
col += blushAlbedo × light × powderSheen(...) × blushA
```

영상 룩만 `blushColor`(색상 혼합) · `softLight` 경로를 추가로 탄다. 제품 경로는 Soft Light를 쓰지 않는다.

위치: 제품만 고르면 미리 그린 UV 마스크(반지름 얼굴 너비 0.17 × 0.11). 룩이 `blushPlacement` / `size` / `softness`를 주면 셰이더가 타원 두 개를 계산하고 `appleScale 0.8`.

---

## 5. 아이섀도 (`eyeshadow`)

UV. 눈두덩 → 쌍꺼풀(`shadowCrease 0.6`) + 눈꼬리 아래. `hexTo`가 있으면 두 번째 색을 눈꼬리·아래 라인에 `shadowPack`(제품) 또는 `powder`(룩).

마무리 id는 카탈로그 Texture가 아니라 `geometry.shadowFinish` (`lib/shadowFinishes.ts`). 칩: 매트 · 새틴 · 쉬머 · 글리터 · 글로시. 제품명에 메탈이면 글리터를 메탈릭 경로로 그린다.

### 5-1. 덮임

영상 룩: `SHADOW_FINISHES.opacity`.  
제품 AR: `SHADOW_PRODUCT_OPACITY` (펄 제형이 너무 비쳐 색이 안 보이던 것 보정, 11-19 v9).

| 마무리 | 룩 opacity | 제품 opacity | roughness | sparkleDensity | specular |
|---|---|---|---|---|---|
| matte | 0.70 | 0.95 | 1.00 | 0 | 0 |
| satin | 0.55 | 0.85 | 0.55 | 0 | 0.45 |
| shimmer | 0.30 | 0.65 | 0.40 | 0.35 | 0.40 |
| metallic | 0.60 | 0.85 | 0.30 | 0.20 | 1.00 |
| glitter | 0.30 | 0.90 | 0.20 | 0.75 | 0.95 |
| glossy | 0.25 | 0.50 | 0.05 | 0 | 0.90 |

```
shadowA = mask × opacity
col = mix(col, shadowPack(col, cam, alb), shadowA)   # 제품
col = mix(col, col × (alb / paperWhite), shadowA)    # 영상 룩
```

레이어(제품): 앞머리 `innerSheer`로 옅게, 눈꼬리 V·쌍꺼풀 띠에 같은 색을 한 번 더.

### 5-2. 제품 AR 재질 경로 (`SHADOW_MODE`)

색 두 패스 이후. 카메라 밝기 기복(`lidRelief`)을 높이로 읽어 미세 법선(주름 **검출이 아님**). 빛 항은 국소 카메라 밝기·볼록 정도를 곱해 주름 안·어두운 곳에 흰 점이 안 생기게.

| 모드 | 하는 일 |
|---|---|
| 0 matte | 펄 없음. 피부 명암 오버레이만 |
| 1 satin | 넓은 실크 윤기, 입자 없음 |
| 2 shimmer | 보로노이 고운 둥근 점 + 잔펄 |
| 3 metallic | 빈틈 적은 면 펄 + 연속 금속광. 제품명 메탈일 때 |
| 4 glitter | 틈 있는 판상 조각, 알갱이 수 ≈ 쉬머의 1.4배(v8). 큰 입자 제품은 `largeCell` |
| 5 glossy | 입자 없음. 빛 받는 접힘에 젖은 막 하이라이트 |

입자: 아래 색을 **곱으로 밝히고**(명암 유지) 반짝임만 더한다. 글리터 알갱이는 제품 색 + 흰색 15%(v9).

보로노이 기본 (`SHADOW_VORO`, 슬라이더 없이 `VORO_FIXED` 캡처값):

| | cell | density | fill | gap | body | flash | sharp |
|---|---|---|---|---|---|---|---|
| shimmer | 0.85 | 0.75 | 0 (점) | 0 | 0.45 | 1.2 | 24 |
| metallic | 0.75 | 1.0 | 1 (면) | 0.05 | 0.90 | 3.0 | 40 |
| glitter | 2.0 | 0.75 | 1 | 0.14 | 0.60 | 5.5 | 50 |

`SHADOW_PEARL` 0~100 표(밀도·크기·밝기·반짝임·반사 폭·주름 보존 등)는 `pearlUniforms()`가 0~1 유니폼으로 바꾼다. 매트는 density·sparkle 0.

글리터 형질은 제품·셰이드 **이름**에서만 읽는다(`glitterTraitsOf`): 메탈 / 큰 입자(스팽·청크) / 홀로.

---

## 6. 아이라인 (`eyeliner`)

화면 공간 눈 캔버스 R. 속눈썹 라인 띠 + 꼬리. 스타일 칩 6개(`lib/linerLooks.ts`): 두께·꼬리·각도·번짐·아래 라인.

```
linerA = 캔버스R × 1.0
col    = mix(col, 제품색 × mix(1, 카메라명암, linerShade=0.4), linerA)
```

- 코어는 거의 불투명. 카메라 흐림 맞추기 없음. 반 텍셀 AA만.
- 띠 최소 1.5 텍셀. 아래 경계를 눈 너비 0.015만큼 눈 쪽으로 겹침(`linerRootInset`). 눈 구멍 패스가 흰자 위를 지움.
- 매트·벨벳: 번진 테두리만 `max()`로 더해 검은 중심 유지.
- `fitLidLine`: 카메라에서 속눈썹 경계를 찾아 점을 옮김. 눈 40px 미만·감김·옆얼굴이면 사전값.

---

## 7. 마스카라 (`mascara`)

탐색 칩 없음. 연예인·스타일 룩 카메라만. 눈 캔버스 G, 절차적 가닥(베지어 리본).

- 길이·굵기·부채·묶음은 `lib/mascaraLooks.ts` / `ZoneGeometry`.
- 무작위는 가닥 번호 시드(프레임마다 안 바뀜).
- 눈 뜨면 위로, 감으면 아래로. 고개 돌리면 facing으로 길이·기울기.
- 가닥 끝만 카메라 흐림. 컬 위 가장자리 반사 `lashGloss 0.18` × 방 조명.
- 내 속눈썹(라인 근처 어두운 픽셀)은 overlay로 색만.

---

## 8. 아이브로우 (`brow`)

화면 공간 눈썹 캔버스. 점은 안 옮김. 카탈로그 제형은 전부 satin으로 취급 → **제형 차이 없음**.

1층 펜슬·파우더: `powder()`, 세기 `powder 0.25`. 앞머리 0.4 · 산 0.85 · 꼬리 0.9.

2층 브로우 마스카라: **국소 피부보다 어두운 픽셀만** 털. 밝기는 두고 색도를 제품 쪽으로 `hairShift 0.9`. 밝은 제품은 털 밝기를 `lift 0.35`만.

앞머리 가드: 세그먼터 머리카락 클래스가 이마에서 내려오면 색 0.

---

## 9. 파운데이션 (`foundation`)

UV 얼굴 윤곽 안(입술·눈·눈썹 구멍 제외). **제품 제형은 렌더에 안 씀.** 커버력 막대만.

`t = intensity` (0 시어 → 1 풀커버):

```
foundCoverage = mix(0.30, 0.85, t)
foundOpaque   = mix(0.15, 0.90, t)
foundA        = 얼굴마스크 × foundCoverage × 피부마스크
pigment       = layer(cam, albedo, skinMean, 1.2)
film          = cam × √(albedo / paperWhite)
col           = mix(col, mix(film, pigment, foundOpaque), foundA)
```

별도 광택·피부 매끈하게 하기·밝히기 없음. 붉은 기·얼룩은 안료 몫만큼만 가려진다.

머리카락: selfie 얼굴 피부 클래스. 없으면 밝기 `foundHair` 0.3~0.55. 눈 아래는 마스크가 늦어도 `foundLowerFloor 0.9`로 랜드마크를 따라가되, 손·머리가 가리면 끔.

영상 룩만 `skinEven`·톤 보정을 파운데이션 경로에 얹을 수 있다. 제품 AR은 해당 유니폼 0.

---

## 10. 하이라이터 (`highlighter`)

UV. 얼굴형(`HL_FACE_AREAS`)이 켤 부위(이마·눈 밑·콧대·인중·턱·광대)를 정함. 거칠기는 립과 같은 `MATERIALS`에서 읽어 윤기 로브만 바꾼다.

세기:

```
hlA = 마스크 × intensity × 0.5 × clamp(1 + volumeGain × (volFace − 0.7), 0.7, 1.4)
```

`hlNatural` (기본 켜짐): 흰색을 더하지 않고 픽셀 자기 색에 비례해 올림.

```
room = (표시밝기 headroom) × (얼굴평균보다 이미 밝으면 감소)
col *= 1 + hlA × room × hlLift × mix(1, 제품색조, hlTint=0.10)
col += 탈채도(픽셀) × GGX윤기 × hlA × room
```

반짝임은 1px 점이 아니라 둥근 글린트(쉬머 제형 `flake`). 이마는 피부 마스크로 앞머리 위 금지.

구경로(`hlNatural` 끄면): `mix(col, layer(...), 0.35 × hlA)` + 제품색 30%+흰 70% 더하기. 쓰지 않는 것이 기본.

---

## 11. 쉐딩 (`contour`)

UV. 턱선 띠 + 콧대 음영. 볼 패임·얼굴형 개인화는 **꺼져 있음**(기본 모양만).

```
contourA = 마스크 × intensity × (턱선 ? 0.85 : 0.8)
contourA *= clamp(1 + volume × (0.7 − volFace), 0.6, 1.5)
col = mix(col, powder(cam, albedo), contourA)
```

가루 68% + 필름 32%(`powderTint` 0.32). 순수 Multiply가 아니다. 턱선은 피부 마스크·옆얼굴 숨김(`uJawYaw`).

순서: **쉐딩 → 하이라이터**. 밝은 윗면 위에 어두운 음영이 먼저 깔린다.

---

## 12. 그리는 순서 (한 픽셀)

대략: 파운데이션 → 쉐딩 → 블러셔 → 하이라이터 → 아이섀도(색 → 제형 펄) → 아이라인 → 마스카라 → 아이브로우 → 립.

아이라인 코어 아래로는 섀도가 비치지 않게 비운다. 눈 구멍·가림 마스크(`uOccGate`)는 해당 부위의 α를 줄인다.

---

## 13. 제품 AR vs 영상 룩

| | 제품 AR | 영상 룩 (`video: true`) |
|---|---|---|
| 색 | 카탈로그 hex 유지 | `lib/videoLookStyles.ts` 룩 전용 색 가능 |
| 섀도 | `shadowPack` + 6제형 보로노이 | 곱하기 + 옛 `SHADOW_FINISHES` 펄 |
| 블러셔 | `powder`만 | 소프트 라이트·색상 혼합 가능 |
| 립 | 제품 재질표 | 룩 색 + 강도 슬라이더 0.3~1.7 (기본 0.7) |
| 피부 | 정리 없음 | `skinEven` 등, 설윤 뿌까만 확인됨 |

룩 강도는 덮임·효과 이득만 스케일하고 색·모양 hex는 그대로(`scaleLookOverrides`).

---

## 14. 부위 × 제형이 렌더에 미치는 범위

| 부위 | 카탈로그 Texture가 하는 일 |
|---|---|
| 립 | 위 표 전부 (덮임·비침·윤기·Overlay·주름) |
| 블러셔 | roughness → 가장자리 `blushPow` + 가루 윤기. UI 칩 없음 |
| 아이섀도 | shimmer/glossy면 기본 마무리. 실제 재질은 `shadowFinish` + 제품명(메탈) |
| 아이라인 | 매트·벨벳만 번진 테두리. 색·불투명은 공통 |
| 마스카라 | 제형 없음. 룩 geometry |
| 아이브로우 | 무시 (전부 같은 두 층) |
| 파운데이션 | 무시. 커버력만 |
| 하이라이터 | roughness / flake → 윤기·반짝임 |
| 쉐딩 | powderTint 고정. 제형 칩 없음 |

---

## 15. 실패로 보는 기준 (계산이 맞았는지)

- 립: 입술 전체가 같은 밝기의 불투명 면. 제품 hex를 명암 없이 덮음.
- 블러셔: 밝은 색이 어두운 피부에 잿빛 사각형.
- 섀도: 글리터에서 아래 색이 안 보이거나, 어둠 속에 흰 점만.
- 파운데이션: 피부결 제거, 얼굴 전체 밝히기, 머리카락 위 칠.
- 하이라이터: 흰 동그라미·1px 흰 점, 앞머리 위 반짝임.
- 공통: 진하기 0인데 픽셀이 바뀜. 얼굴 영상을 서버로 보냄.

원본 상수 위치: `TUNING` · `MATERIALS` · `SHADOW_FINISHES` · `SHADOW_PRODUCT_OPACITY` · `SHADOW_PEARL` · `SHADOW_VORO` · `EYELINER_DARK` · `EYEBROW_PRESET` — 모두 `components/ar/faceTrackerHtml.ts`.
