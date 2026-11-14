# 상용 AR 메이크업 비교 (블랙박스)

YouCam·DeepAR의 **화면 결과만** 우리 AR과 나란히 비교한다. 앱·SDK 코드, 셰이더, 모델, 텍스처는 뜯거나 가져오지 않는다(두 회사 약관이 역공학을 금지). 원리는 아래 공개 자료에서만 가져온다.

## 1. 공개 자료에서 확인한 것 (2026-11-03)

| 출처 | 공개된 내용 | 우리 셰이더와 비교 | 판단 |
|---|---|---|---|
| DeepAR Studio 문서 [Ultimate Beauty](https://docs.deepar.ai/deepar-studio/guides-and-tutorials/ultimate-beauty/) | 립은 두 층: `lipcolorMat`(색 텍스처, 매트에 해당) 위에 `lipglossMat`. 글로스는 **매트캡**(정적 조명·반사를 미리 구운 텍스처, 법선 방향으로 읽음) + 노멀맵(요철) + 반사 세기 텍스처 + 색조 | 우리 글로시는 그 사람 윤곽에서 만든 형태 법선 + 추정 빛 + 항상 있는 정면 광원(`frontGloss`). 매트캡과 역할이 비슷하지만 조명을 따라감 | 매트캡처럼 조명과 무관한 반사는 원칙 1-2와 부딪힘. 비교에서 "윤기 약함"이 반복될 때만 `frontGloss` 쪽으로 검토. **입술 노멀맵 템플릿은 6-5-3 금지(템플릿·그린 주름 법선 없음)** |
| DeepAR npm [`@deepar/beauty`](https://www.npmjs.com/package/@deepar/beauty) | `lipMakeup.lipstick.shade`(템플릿), `lipMakeup.lipGloss.gloss`·`amount` 0–100. 립스틱과 글로스를 따로 켬 | 글로스 덧바르기 = 우리 F18(M16, 겹쳐 바르기) | MVP로 당길지는 팀 결정(6-5-3) |
| Perfect Corp 특허 [US 11,030,798](https://patents.justia.com/patent/11030798) | 이미지의 그림자를 미리 조명을 바꿔 둔 3D 얼굴 모델들과 비교해 빛 방향·세기·색을 고르고, 메이크업 표면 성질(확산 반사·정반사·투명도, 하위 표면 산란 언급)로 **픽셀마다** 조정. 입술 일부가 그늘이면 그 부분만 어둡게 | 우리도 픽셀마다(층 쌓기 + Lambert + GGX). 빛 추정은 Gray World + 메시 법선 | **특허 청구 방식(미리 구운 3D 모델과 그림자 매칭)은 구현하지 않음.** 원리(입술 안 그늘은 그대로 남긴다)는 이미 6-5-3 층 쌓기와 같음 |
| Perfect Corp [Makeup VTO API](https://docs.perfectcorp.com/reference/makeup_vto/section/overview) | `lip_color`: texture 7종, `gloss`, `transparencyIntensity`, shimmer 색·세기·밀도·크기, style `full`/`ombre`/`twoTone`, morphology `fullness`·`wrinkless` | 7제형·세기는 6-5-4 매핑에 이미 있음. 볼륨·주름 제거는 1-3으로 0 | 변경 없음 |
| Perfect Corp [블로그](https://www.perfectcorp.com/business/blog/makeup/how-virtual-makeup-try-on-renders-lipstick-blush-foundation) | 립스틱은 입술선·입술 결·**윗입술/아랫입술 두 톤 명암**을 지켜야 함. 글로스는 고개를 따라 움직이는 반사·투명도 | 아래 지표 `upper_lower_L`, `hl_*`로 잰다 | 측정 대상 |

정리: 공개 자료만으로는 "우리가 무엇을 빠뜨렸는지" 단정할 수 없다. 고칠 때는 6-5-3 규칙 안에서만 고친다.

**특허 원리 실험(11-03)**: 위 특허의 조명 추정 원리(후보 조명마다 그 얼굴의 명암·그림자를 계산해 카메라와 가장 맞는 것을 고름)를 학습용으로 `faceTrackerHtml.ts`의 `matchLight`에 구현했다. 미리 구운 3D 얼굴 모델 대신 매 순간 그 사람의 얼굴 메시로 그림자를 계산한다. `TUNING.lightMatch`(기본 꺼짐)로 켠다. 배포하지 않는 학생 연구용이며, 상용화하면 특허 검토가 필요하다.

## 2. 촬영 방법 (선택)

YouCam·DeepAR과 비교하고 싶을 때만 찍는다. 우리 변경 전후 비교는 같은 규칙으로 앱 이름 대신 `before`·`after`를 쓴다(예: `coral-gloss-side__before.png` = `lightMatch` 끔, `__after.png` = 켬).

같은 사람·같은 자리·같은 조명에서 앱(또는 설정)만 바꿔 찍는다. 얼굴 사진은 `research/data/vto_benchmark/<날짜>/`에만 둔다(저장소 제외). 동의한 팀원 얼굴만(1-13).

1. **조명 고정**: 창문 등지지 않기, 실내등 하나. 촬영 중 자리를 옮기지 않는다.
2. **색**: 우리 카탈로그 셰이드 중 코랄·레드·누드 1개씩. YouCam·DeepAR에서는 **눈으로 가장 비슷한 색**을 고른다(색 자체는 비교 대상이 아님. 명암·결·윤기·경계를 본다).
3. **제형**: 매트, 글로시 각각.
4. **자세**: 정면(입 다묾) / 입 살짝 벌림 / 고개 옆 30°.
5. **진하기**: 각 앱 기본값.
6. **파일 이름**: `<색>-<제형>-<자세>__<앱>.png`
   - 앱: `ours`, `youcam`, `deepar`, `bare`(맨입술, 있으면 좋음), 우리 변경 전후는 `before`, `after`
   - 예: `coral-gloss-front__ours.png`, `coral-gloss-front__youcam.png`
7. 화면 캡처 그대로 넣어도 된다(UI가 있어도 얼굴만 찾음). 얼굴이 작으면 확대해서 찍는다(입 너비 150px 이상 권장).
8. 영상(3~5초, 고개 좌우)은 같은 폴더에 두고 눈으로 비교한다. 이 스크립트는 사진만 잰다.

최소 세트: 3색 × 2제형 × 정면 = 6조건 × 2앱 = 12장.

## 3. 실행

```bash
uv run research/vto_benchmark/compare_lips.py research/data/vto_benchmark/2026-11-03
```

얼굴 점 모델은 `research/data/models/face_landmarker.task`(없으면 스크립트가 받을 주소를 알려 줌). 결과는 `<폴더>/_out/`:

- `summary.md` — 조건마다 "우리가 YouCam(없으면 DeepAR) 대비 어디가 다른지", `before`·`after`가 있으면 "변경 후가 변경 전 대비 어디가 다른지"
- `metrics.csv` — 숫자 전체
- `<조건>_sheet.png` — 입술 확대 나란히, 아래 줄은 하이라이트(하늘색)·바깥 입술선(초록)

## 4. 지표

| 열 | 뜻 | 스티커처럼 보일 때 |
|---|---|---|
| `L_spread` | 입술 밝기 p90 − p10 (명암 폭) | 작다 |
| `flat_frac` | 중앙값 ±3 L* 안의 픽셀 비율 (같은 밝기 면) | 크다 |
| `texture` | 고역(입 너비 1.2% 흐림과의 차) 표준편차 (주름 결) | 작다 |
| `upper_lower_L` | 윗입술 / 아랫입술 평균 밝기 (윗입술 그늘) | 1에 가깝다 |
| `hl_area_pct` | 주변보다 튀는 밝은 픽셀 비율 (윤기 면적) | 0 또는 과다 |
| `hl_peak` | 입술 p99 − 중앙값 (윤기 세기) | 너무 작거나 너무 큼 |
| `hl_lower_frac`, `hl_cx` | 윤기 중 아랫입술 비율, 입 가운데로부터 거리(0 = 가운데) | 위치가 다름 |
| `edge_w_pct` | 입술색 → 피부색 80%→20% 전환 폭, 입 너비 대비 % (경계 부드러움) | 너무 작다(칼같음) |
| `L_mean`, `C_mean`, `hue_deg` | 평균 밝기·채도·색상각 | 참고만(앱마다 고른 색이 달라 비교하지 않음) |

`summary.md`의 안내는 기준(YouCam/DeepAR) 대비 25~60% 이상 차이 날 때만 나온다. **숫자 차이가 곧 정답은 아니다**: YouCam이 피부 보정·볼륨을 켜면 그쪽이 비현실적일 수 있다(1-2, 1-3). 고칠 항목은 사진을 눈으로 보고 정한다.

## 5. 자체 확인 (2026-11-03, 시험 사진은 확인 후 삭제)

`image/mediapipe.png`(우리 AR 캡처)로:

- 같은 사진 두 장 → 차이 없음
- 아랫입술 가운데 인공 하이라이트 + 윗입술 그늘 추가 → 명암 폭 26.9→38.9, 위/아래 0.86→0.69, 윤기 면적 0.2→2.2%(93%가 아랫입술, 가운데), 윤기 세기 16→39를 잡음
- 사진 전체 흐림(σ 3px) → 경계 폭 1.8→4.8%를 잡음
