# AR 제어 평가 결과

2026-11-16 실제 로컬 챗봇과 Redis, gpt-6-luna를 연결한 40개 독립 시나리오의 1회 실행 결과.

React Native 화면을 마운트하고 실제 /api/chat 응답을 앱의 기존 조작 경로로 실행했다. 카메라와 얼굴 렌더러는 테스트 대역이며 렌더 완료 신호를 주입했다. 카탈로그는 앱의 oyCatalog.json 전체다. 수동 준비는 팔레트가 쓰는 applyShade 함수를 호출했다. STT와 스마트폰 스피커는 평가에 포함하지 않았다.

각 사례는 별도 익명 사용자와 새 착용 이력에서 시작했다. 기본 화면은 립 팔레트, 립과 블러셔 강도 0.55다. 체험순서 사례는 맨얼굴에서 시작했다. 기대값은 실행 전에 fixture에 고정했다. 준비 대화도 실제 모델로 실행했다.

## 결과

**사전에 고정한 조작 기준은 38/40 통과(95%)다.** 답변을 대조하면서 N09의 사실 오류도 추가로 발견했다. 이 비율은 조작 검사 결과이며, 답변 정확도까지 통과한 비율로 해석할 수 없다.

준비 대화 14개와 평가 대상 40개를 합해 실제 사용자 발화 54개를 처리했다. 실행은 약 7분 12초 걸렸다. 각 사례를 한 번 실행한 값으로 반복 안정성은 추가 검증 대상이다. 기존 회귀 문장과 새 표현을 함께 포함했다.

## 확인된 문제

### N10 — 없는 호수명을 색감 추천으로 대체

“별빛구름맛이라는 립으로 발라줘”에 없는 호수임을 안내하거나 확인 질문을 해야 했다. 실제로는 `apply_shade/lip/by_color`, `family=nude`를 선택해 토니모리 겟잇 틴트 워터풀 시럽 밀키누드시럽을 적용했다. 색감 선택을 위임한 요청으로 잘못 해석한 사례다.

### M09 — 수동 변경 후 생략된 방향을 추측

준비 대화에서 립을 연하게 바꾼 뒤 손으로 번트하트를 골라 이전 조절 기록을 무효화했다. 이후 “조금 더”에서는 대상을 확인하거나 조절 방향을 물어야 했다. 실제로 `adjust_intensity/lip/up`을 선택해 강도가 `0.275 → 0.375`로 올라갔다.

준비 발화인 “립 좀 연하게 해줘”에서도 `set_intensity/lip/half`를 선택해 `0.55 → 0.275`로 줄였다. 일반적인 첫 상대 조절 폭 0.10보다 크게 바꾼 추가 관찰이며, 40개 대상 요청의 성공률에는 별도 사례로 세지 않았다.

### N09 — 착용은 유지했지만 잘못된 브랜드의 호수로 설명

“페이드 레드도 있어? 아직 바르지는 말고”에 Luna는 이름 필터 없이 `find_shades/lip`을 호출했다. 반환된 12개 예시는 퓌 글로스의 다른 호수들이었고, 답변은 “네, 퓌 3D 볼류밍 글로스에서 페이드 레드 색상을 찾을 수 있어요”였다. 실제 페이드 레드는 롬앤 제로 벨벳 틴트 24호다. 이 사례는 착용 유지·읽기 전용 조작 기준에서는 PASS지만, 호수명과 제품의 사실 일치 검토에서는 실패다.

### 답변 말투 관찰

후속 조절 답변에는 “이 정도가 원하신 느낌일까요?”처럼 사용자에게 느낌을 묻는 표현이 나왔다. 호수명 지정에서는 제품명과 색 설명이 중심이었고 “발라드렸어요”가 반복됐다. M05에서는 적용 완료 뒤에도 “낮춰볼게요”라는 미래형을 사용했다. 문장 자연스러움과 완료 시제의 일관성은 별도 개선 항목으로 남긴다.

## 유형별 조작 검사

| 유형 | 성공 / 실행 | 성공률 |
|---|---:|---:|
| 호수명 | 9 / 10 | 90.0% |
| 색감 | 10 / 10 | 100.0% |
| 멀티턴 | 9 / 10 | 90.0% |
| 체험순서 | 10 / 10 | 100.0% |

호수명과 체험 복원은 제품·호수 ID 및 실제 착용색을 검사했다. 색감은 지정 조건의 툴 인자, 카탈로그의 실제 호수 적용, 다른 부위 유지 여부를 검사했다. 추천 호수의 지각적 적합성은 별도 평가가 필요하다. 멀티턴은 Redis 확인 결과에 따른 부위·방향·변화 폭과 다른 부위 유지를 검사했다. 답변 전문은 아래 기록에 남겼으며 페르소나와 문장 자연스러움은 자동 성공률에 포함하지 않았다.

## 전체 평가셋

| ID | 유형 | 사용자 입력 | 기대 결과 | 결과 |
|---|---|---|---|---|
| N01 | 호수명 | 페이드 레드 발라줘 | 롬앤 24호 지정 적용 | PASS |
| N02 | 호수명 | 페이드레드로 한번 볼래 | 띄어쓰기 없이 롬앤 24호 지정 적용 | PASS |
| N03 | 호수명 | 번트하트 있지? 그거 발라줘 | 롬앤 04호 지정 적용 | PASS |
| N04 | 호수명 | 오늘은 피칸타르트로 해줄래? | 롬앤 14호 지정 적용 | PASS |
| N05 | 호수명 | 롬앤 제로 벨벳 틴트 앤셜리 발라볼래 | 롬앤 12호 지정 적용 | PASS |
| N06 | 호수명 | 너드 핑크로 바꿔줘 | 롬앤 25호 지정 적용 | PASS |
| N07 | 호수명 | 얼그레이 숄 그 색으로 발라줘 | 롬앤 19호 지정 적용 | PASS |
| N08 | 호수명 | 페이드 레드는 바르지 말고 지금 바른 립 이름만 알려줘 | 현재 제품 조회, 착용 유지 | PASS |
| N09 | 호수명 | 페이드 레드도 있어? 아직 바르지는 말고 | 조회 또는 안내, 착용 유지 | PASS |
| N10 | 호수명 | 별빛구름맛이라는 립으로 발라줘 | 없는 호수는 안내 또는 거절, 착용 유지 | FAIL |
| C01 | 색감 | 차분한 레드로 발라줘 | 레드·낮은 채도로 추천 적용 | PASS |
| C02 | 색감 | 쨍한 핑크 말고 좀 차분한 핑크로 해줘 | 핑크·낮은 채도로 추천 적용 | PASS |
| C03 | 색감 | 입술은 쨍한 빨강으로 포인트 줘 | 레드·높은 채도로 추천 적용 | PASS |
| C04 | 색감 | 밝고 여리여리한 핑크 립 발라줘 | 핑크·밝은 톤으로 추천 적용 | PASS |
| C05 | 색감 | 이번엔 코랄빛 립으로 바꿔볼래 | 코랄 계열 추천 적용 | PASS |
| C06 | 색감 | 입술에 딥한 브라운으로 분위기 내줘 | 브라운·어두운 톤 추천 적용 | PASS |
| C07 | 색감 | 누드톤 립 하나 골라서 발라줘 | 누드 계열 추천 적용 | PASS |
| C08 | 색감 | 블러셔는 연한 핑크빛으로 올려줘 | 블러셔 핑크·밝은 톤 추천 적용 | PASS |
| C09 | 색감 | 여리여리한 느낌으로 립 하나 골라 발라줘 | 밝고 낮은 채도의 립 추천 적용 | PASS |
| C10 | 색감 | 입술은 선명한 베리 컬러로 해줘 | 베리·높은 채도로 추천 적용 | PASS |
| M01 | 멀티턴 | 조금 더 | 립 감소의 연속, 0.45 → 0.40 | PASS |
| M02 | 멀티턴 | 거기서 딱 한 끗만 더 | 립 감소의 연속, 0.45 → 0.40 | PASS |
| M03 | 멀티턴 | 조금 더 | 열린 립 팔레트 대신 블러셔 증가, 0.65 → 0.70 | PASS |
| M04 | 멀티턴 | 한 번만 더 덜어줘 | 블러셔 감소의 연속, 0.45 → 0.40 | PASS |
| M05 | 멀티턴 | 거기서 조금 더 연하게 | 실제 직전 폭 0.30의 절반인 0.15 감소 | PASS |
| M06 | 멀티턴 | 여기서 조금만 더 | 직전 폭 0.05의 절반 반올림, 0.40 → 0.37 | PASS |
| M07 | 멀티턴 | 이번엔 블러셔를 연하게 해줘 | 새 대상 블러셔 감소, 립 유지 | PASS |
| M08 | 멀티턴 | 아니다 입술을 좀 더 진하게 해줘 | 명시적으로 바뀐 방향으로 립 증가 | PASS |
| M09 | 멀티턴 | 조금 더 | 수동 제품 변경으로 이전 강도 근거 무효, 되묻고 착용 유지 | FAIL |
| M10 | 멀티턴 | 입술 더 연하게 해줘 | 최솟값에서 변화 없음 | PASS |
| H01 | 체험순서 | 아까 두 번째로 발라본 립 다시 발라줘 | 수동→Luna→수동 뒤 두 번째 립 ID·호수 복원 | PASS |
| H02 | 체험순서 | 맨 처음 써본 입술 색으로 돌아가자 | 첫 수동 립 복원 | PASS |
| H03 | 체험순서 | 두 번째 립이 더 좋았어. 그걸로 다시 해줘 | Luna→수동→수동 뒤 두 번째 수동 립 복원 | PASS |
| H04 | 체험순서 | 두 번째로 바른 립으로 다시 해줘 | 블러셔를 제외하고 립의 두 번째 복원 | PASS |
| H05 | 체험순서 | 전체에서 두 번째로 발라본 제품 다시 발라줘 | 전체 순서의 두 번째 블러셔, 이미 착용해 NO_CHANGE | PASS |
| H06 | 체험순서 | 세 번째로 발랐던 립으로 해줘 | 이미 착용 중인 세 번째 호수 유지 | PASS |
| H07 | 체험순서 | 두 번째 립 다시 보여줘 | 같은 호수 반복 선택은 중복 집계하지 않고 24호 복원 | PASS |
| H08 | 체험순서 | 두 번째로 발라봤던 입술 색 다시 발라줘 | 강도 조절은 체험 순번에서 제외하고 24호 복원 | PASS |
| H09 | 체험순서 | 아까 다섯 번째 립 다시 발라줘 | 없는 순번 안내 또는 거절, 착용 유지 | PASS |
| H10 | 체험순서 | 아까 두 번째로 바른 립 다시 발라줘 | 비어 있는 이번 체험 이력 안내, 착용 유지 | PASS |

## 실패 사례

### N10 별빛구름맛이라는 립으로 발라줘

기대 결과는 없는 호수는 안내 또는 거절, 착용 유지이다.

```text
expect(received).toEqual(expected) // deep equality

- Expected  - 2
+ Received  + 2

@@ -2,9 +2,9 @@
    "blush": Object {
      "productId": "oy-a000000171371",
      "shadeId": "a000000171371-044",
    },
    "lip": Object {
-     "productId": "oy-a000000120880",
-     "shadeId": "23",
+     "productId": "oy-a000000223922",
+     "shadeId": "16",
    },
  }
```

### M09 조금 더

기대 결과는 수동 제품 변경으로 이전 강도 근거 무효, 되묻고 착용 유지이다.

```text
expect(received).toEqual(expected) // deep equality

- Expected  - 1
+ Received  + 1

@@ -10,10 +10,10 @@
    "eyeshadow": null,
    "foundation": null,
    "highlighter": null,
    "lip": Object {
      "hex": "#8B4651",
-     "intensity": 0.275,
+     "intensity": 0.375,
      "texture": "velvet",
    },
    "mascara": null,
  }
```


## 실제 조작과 답변 요약

표의 제품·호수와 강도는 평가 대상 요청이 끝난 시점의 착용 상태다. 조회·거절·변경 없음 사례에는 요청 전부터 바르고 있던 제품이 표시된다.

| ID | action | status | 적용 제품 / 호수 | 강도 | 실제 답변 |
|---|---|---|---|---:|---|
| N01 | apply_shade/product_shade | APPLIED | 롬앤 제로 벨벳 틴트 / 페이드 레드 | 0.55 | 롬앤 제로 벨벳 틴트 페이드 레드는 깊이감 있는 레드예요. 발라드렸어요. |
| N02 | apply_shade/product_shade | APPLIED | 롬앤 제로 벨벳 틴트 / 페이드 레드 | 0.55 | 롬앤 제로 벨벳 틴트 페이드 레드는 딥한 레드 컬러예요. |
| N03 | apply_shade/product_shade | APPLIED | 롬앤 제로 벨벳 틴트 / 번트하트 | 0.55 | 롬앤 제로 벨벳 틴트 번트하트는 차분하고 깊은 베리 컬러예요. 발라드렸어요. |
| N04 | apply_shade/product_shade | APPLIED | 롬앤 제로 벨벳 틴트 / 피칸타르트 | 0.55 | 롬앤 제로 벨벳 틴트 피칸타르트로 연출해드렸어요. 차분한 딥 베리 컬러예요. |
| N05 | apply_shade/product_shade | APPLIED | 롬앤 제로 벨벳 틴트 / 앤셜리 | 0.55 | 롬앤 제로 벨벳 틴트 앤셜리는 선명하고 딥한 레드 컬러예요. 발라드렸어요. |
| N06 | apply_shade/product_shade | APPLIED | 롬앤 제로 벨벳 틴트 / 너드 핑크 | 0.55 | 롬앤 제로 벨벳 틴트 너드 핑크의 차분하고 깊은 베리 컬러로 바꿨어요. |
| N07 | apply_shade/product_shade | APPLIED | 롬앤 제로 벨벳 틴트 / 얼그레이 숄 | 0.55 | 롬앤 제로 벨벳 틴트 얼그레이 숄의 차분하고 짙은 레드 컬러로 발라드렸어요. |
| N08 | get_state/lip | OK | 롬앤 제로 벨벳 틴트 / 빈티지 토프 | 0.55 | 지금 바른 립은 롬앤 제로 벨벳 틴트 ‘빈티지 토프’예요. |
| N09 | find_shades/lip | OK | 롬앤 제로 벨벳 틴트 / 빈티지 토프 | 0.55 | 네, 퓌 3D 볼류밍 글로스에서 페이드 레드 색상을 찾을 수 있어요. 아직 바르지는 않았어요. |
| N10 | apply_shade/lip/by_color | APPLIED | [한정기획] 토니모리 겟잇 틴트 워터풀 시럽 / 밀키누드시럽 | 0.55 | 토니모리 [한정기획] 겟잇 틴트 워터풀 시럽의 밀키누드시럽을 발라드렸어요. 가볍고 차분한 누드 색감이에요. |
| C01 | apply_shade/lip/by_color | APPLIED | [얼그레이에디션/10월 올영픽] 퓌 3D 볼류밍 글로스 (기획/단품) / 바닐라 쿠키 70% | 0.55 | 퓌 [얼그레이에디션/10월 올영픽] 퓌 3D 볼류밍 글로스 (기획/단품)의 바닐라 쿠키 70%를 발랐어요. 차분한 미디엄 레드예요. |
| C02 | apply_shade/lip/by_color | APPLIED | [아이돌PICK] 잉가 워터 글로우 립 틴트 4.5g_13컬러 / 스플래쉬 | 0.55 | 잉가 워터 글로우 립 틴트 ‘스플래쉬’로 바꿨어요. 쨍하지 않고 차분한 미디엄 핑크예요. |
| C03 | apply_shade/lip/by_color | APPLIED | [매끈보송립] 누즈 무스 립추얼 6Colors / 러비 코랄 | 0.55 | 누즈 무스 립추얼 러비 코랄의 선명하고 짙은 레드로 입술에 포인트를 줬어요. |
| C04 | apply_shade/lip/by_color | APPLIED | 어뮤즈 립 스머져  0.5g 6종 / 복숭아 우유 | 0.55 | 어뮤즈 립 스머져 ‘복숭아 우유’로 밝고 여리여리한 핑크 립을 발라드렸어요. |
| C05 | apply_shade/lip/by_color | APPLIED | 얼터너티브스테레오 립 포션 슈가 글레이즈 틴트 8ml / 호 누디 볼 | 0.55 | 얼터너티브스테레오 립 포션 슈가 글레이즈 틴트 8ml의 호 누디 볼로 바꿨어요. 가볍고 은은한 코랄빛이에요. |
| C06 | apply_shade/lip/by_color | APPLIED | [NEW/쿠로미에디션]  3CE 글레이지 립 글로우 3.2g 기획/단품 / 솔티 스윗 | 0.55 | 3CE 글레이지 립 글로우의 솔티 스윗으로 입술에 딥하고 차분한 브라운 무드를 더했어요. |
| C07 | apply_shade/lip/by_color | APPLIED | [한정기획] 토니모리 겟잇 틴트 워터풀 시럽 / 밀키누드시럽 | 0.55 | 토니모리 겟잇 틴트 워터풀 시럽 밀키누드시럽을 발라드렸어요. 부드럽고 차분한 연한 누드톤이에요. |
| C08 | apply_shade/blush/by_color | APPLIED | 어뮤즈 치크 톡톡 10종 / 럽미 톡 | 0.55 | 어뮤즈 치크 톡톡의 럽미 톡으로 연한 핑크빛 블러셔를 올렸어요. |
| C09 | apply_shade/lip/by_color | APPLIED | 어뮤즈 듀 틴트 4g 13종 (기획/단품) / 도토리 | 0.55 | 어뮤즈 듀 틴트 ‘도토리’의 여린 누드 컬러를 발라드렸어요. |
| C10 | apply_shade/lip/by_color | APPLIED | MAC 맥시멀 슬릭 새틴 립스틱 11 Colors / 팝스타 핑크 | 0.55 | 입술에 맥 맥시멀 슬릭 새틴 립스틱 팝스타 핑크를 발라 선명하고 깊은 베리 컬러로 연출했어요. |
| M01 | adjust_intensity/lip/down | APPLIED | 롬앤 제로 벨벳 틴트 / 빈티지 토프 | 0.4 | 입술 색을 한결 더 부드럽고 은은하게 낮춰드렸어요. 이 정도가 괜찮으실까요? |
| M02 | adjust_intensity/lip/down | APPLIED | 롬앤 제로 벨벳 틴트 / 빈티지 토프 | 0.4 | 립 컬러를 아주 살짝 더 부드럽게 낮췄어요. 이 정도가 원하신 느낌일까요? |
| M03 | adjust_intensity/blush/up | APPLIED | [1등 블러셔/모공블러] 네이밍 플러피 파우더 블러쉬 20colors / 베이크드 | 0.7 | 블러셔를 살짝 더 또렷하게 올려봤어요. 느낌 어떠세요? |
| M04 | adjust_intensity/blush/down | APPLIED | [1등 블러셔/모공블러] 네이밍 플러피 파우더 블러쉬 20colors / 베이크드 | 0.4 | 볼터치를 한층 더 부드럽고 은은하게 덜어드렸어요. 느낌 괜찮으신가요? |
| M05 | adjust_intensity/lip/down | APPLIED | 롬앤 제로 벨벳 틴트 / 빈티지 토프 | 0.15 | 립 컬러를 조금 더 부드럽고 은은하게 낮춰볼게요. 어떠신가요? |
| M06 | adjust_intensity/lip/down | APPLIED | 롬앤 제로 벨벳 틴트 / 빈티지 토프 | 0.37 | 입술 컬러를 살짝 더 부드럽게 눌러드렸어요. 이 정도가 괜찮으세요? |
| M07 | adjust_intensity/blush/down | APPLIED | [1등 블러셔/모공블러] 네이밍 플러피 파우더 블러쉬 20colors / 베이크드 | 0.45 | 블러셔 색감을 조금 부드럽게 낮춰드렸어요. 어떠신가요? |
| M08 | adjust_intensity/lip/up | APPLIED | 롬앤 제로 벨벳 틴트 / 빈티지 토프 | 0.55 | 입술 색을 한층 더 진하게 올려드렸어요. 어떠신가요? |
| M09 | adjust_intensity/lip/up | APPLIED | 롬앤 제로 벨벳 틴트 / 번트하트 | 0.375 | 입술 컬러를 조금 더 또렷하고 대담하게 올려드렸어요. 어떠세요? |
| M10 | adjust_intensity/lip/down | NO_CHANGE | 롬앤 제로 벨벳 틴트 / 빈티지 토프 | 0 | 입술 색은 이미 가장 연한 단계라 더 연하게 바뀌지 않았어요. |
| H01 | reapply_try_on/lip | APPLIED | 롬앤 제로 벨벳 틴트 / 페이드 레드 | 0.65 | 아까 두 번째로 발라보신 롬앤 제로 벨벳 틴트 페이드 레드의 딥한 레드 컬러를 다시 발라드렸어요. |
| H02 | reapply_try_on/lip | APPLIED | 롬앤 제로 벨벳 틴트 / 번트하트 | 0.65 | 처음 써보셨던 롬앤 제로 벨벳 틴트 번트하트의 차분하고 깊은 베리 컬러로 돌아왔어요. |
| H03 | reapply_try_on/lip | APPLIED | 롬앤 제로 벨벳 틴트 / 페이드 레드 | 0.65 | 롬앤 제로 벨벳 틴트 페이드 레드의 깊이감 있는 레드로 다시 발라드렸어요. |
| H04 | reapply_try_on/lip | APPLIED | 롬앤 제로 벨벳 틴트 / 페이드 레드 | 0.65 | 롬앤 제로 벨벳 틴트 페이드 레드의 딥한 레드 컬러로 두 번째 립을 다시 발랐어요. |
| H05 | reapply_try_on/all | NO_CHANGE | [1등 블러셔/모공블러] 네이밍 플러피 파우더 블러쉬 20colors / 베이크드 | 0.45 | 네이밍 플러피 파우더 블러쉬의 베이크드 색상은 이미 발라져 있어서 다시 바뀌지 않았어요. |
| H06 | reapply_try_on/lip | NO_CHANGE | 롬앤 제로 벨벳 틴트 / 피즈 | 0.65 | 세 번째로 바르셨던 롬앤 제로 벨벳 틴트 ‘피즈’는 짙고 선명한 레드예요. 이미 해당 립으로 설정되어 있어 변경되지 않았어요. |
| H07 | reapply_try_on/lip | APPLIED | 롬앤 제로 벨벳 틴트 / 페이드 레드 | 0.65 | 두 번째 립은 롬앤 제로 벨벳 틴트 페이드 레드로, 차분하고 깊이감 있는 레드 컬러예요. |
| H08 | reapply_try_on/lip | APPLIED | 롬앤 제로 벨벳 틴트 / 페이드 레드 | 0.325 | 롬앤 제로 벨벳 틴트 페이드 레드의 딥한 레드 색상을 다시 발라드렸어요. |
| H09 | reapply_try_on/lip | REJECTED | 롬앤 제로 벨벳 틴트 / 번트하트 | 0.65 | 이번 세션에는 다섯 번째 립을 발라본 기록이 없어서 다시 바를 수 없어요. |
| H10 | reapply_try_on/lip | REJECTED |  |  | 이 세션에는 두 번째 립을 발랐던 기록이 없어 다시 바를 수 없어요. |


## 시작 상태와 실제 대화 기록

### N01 페이드 레드 발라줘

```json
{
  "id": "N01",
  "group": "호수명",
  "message": "페이드 레드 발라줘",
  "expected": "롬앤 24호 지정 적용",
  "setup": [],
  "turns": [
    {
      "message": "페이드 레드 발라줘",
      "proposal": {
        "choice": "apply_shade/product_shade",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": "oy-a000000120880",
        "shadeId": "24",
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "52e31db6-a371-4942-826b-7980fbd3313b",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "cd917843-25cc-40eb-8579-f0d96af84329",
        "expectedStateVersion": 8
      },
      "status": "APPLIED",
      "answer": "롬앤 제로 벨벳 틴트 페이드 레드는 깊이감 있는 레드예요. 발라드렸어요.",
      "elapsedMs": 6284,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "24"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8C2B28",
            "texture": "velvet",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "24"
        }
      ],
      "result": {
        "choice": "apply_shade/product_shade",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "24",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "페이드 레드",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "medium"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "롬앤",
          "product": "롬앤 제로 벨벳 틴트",
          "productKo": "롬앤 제로 벨벳 틴트",
          "shade": "페이드 레드",
          "family": "red",
          "lightness": "deep",
          "chroma": "medium"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### N02 페이드레드로 한번 볼래

```json
{
  "id": "N02",
  "group": "호수명",
  "message": "페이드레드로 한번 볼래",
  "expected": "띄어쓰기 없이 롬앤 24호 지정 적용",
  "setup": [],
  "turns": [
    {
      "message": "페이드레드로 한번 볼래",
      "proposal": {
        "choice": "apply_shade/product_shade",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": "oy-a000000120880",
        "shadeId": "24",
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "aa29903f-10c3-47a5-bdef-a4a3bf1ad6fc",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "99d91d05-a93a-47e3-93d7-7e2b6e2d9594",
        "expectedStateVersion": 18
      },
      "status": "APPLIED",
      "answer": "롬앤 제로 벨벳 틴트 페이드 레드는 딥한 레드 컬러예요.",
      "elapsedMs": 7439,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "24"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8C2B28",
            "texture": "velvet",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "24"
        }
      ],
      "result": {
        "choice": "apply_shade/product_shade",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "24",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "페이드 레드",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "medium"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "롬앤",
          "product": "롬앤 제로 벨벳 틴트",
          "productKo": "롬앤 제로 벨벳 틴트",
          "shade": "페이드 레드",
          "family": "red",
          "lightness": "deep",
          "chroma": "medium"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### N03 번트하트 있지? 그거 발라줘

```json
{
  "id": "N03",
  "group": "호수명",
  "message": "번트하트 있지? 그거 발라줘",
  "expected": "롬앤 04호 지정 적용",
  "setup": [],
  "turns": [
    {
      "message": "번트하트 있지? 그거 발라줘",
      "proposal": {
        "choice": "apply_shade/product_shade",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": "oy-a000000120880",
        "shadeId": "04",
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "87d5a2a3-2ada-40b8-bfd8-eb6865af2903",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "69b074dd-d493-4bcc-abed-490c49267d9f",
        "expectedStateVersion": 28
      },
      "status": "APPLIED",
      "answer": "롬앤 제로 벨벳 틴트 번트하트는 차분하고 깊은 베리 컬러예요. 발라드렸어요.",
      "elapsedMs": 7014,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8B4651",
            "texture": "velvet",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "04"
        }
      ],
      "result": {
        "choice": "apply_shade/product_shade",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "04",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "번트하트",
            "texture": "velvet"
          },
          "color": {
            "family": "berry",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "롬앤",
          "product": "롬앤 제로 벨벳 틴트",
          "productKo": "롬앤 제로 벨벳 틴트",
          "shade": "번트하트",
          "family": "berry",
          "lightness": "deep",
          "chroma": "muted"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### N04 오늘은 피칸타르트로 해줄래?

```json
{
  "id": "N04",
  "group": "호수명",
  "message": "오늘은 피칸타르트로 해줄래?",
  "expected": "롬앤 14호 지정 적용",
  "setup": [],
  "turns": [
    {
      "message": "오늘은 피칸타르트로 해줄래?",
      "proposal": {
        "choice": "apply_shade/product_shade",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": "oy-a000000120880",
        "shadeId": "14",
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "7bce4675-4755-48f7-971b-0b0a7db459a2",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "437983b7-04d0-460e-ab0b-28bdd8432f96",
        "expectedStateVersion": 38
      },
      "status": "APPLIED",
      "answer": "롬앤 제로 벨벳 틴트 피칸타르트로 연출해드렸어요. 차분한 딥 베리 컬러예요.",
      "elapsedMs": 7447,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "14"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#913239",
            "texture": "velvet",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "14"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "14"
        }
      ],
      "result": {
        "choice": "apply_shade/product_shade",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "14",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "피칸타르트",
            "texture": "velvet"
          },
          "color": {
            "family": "berry",
            "lightness": "deep",
            "chroma": "medium"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "롬앤",
          "product": "롬앤 제로 벨벳 틴트",
          "productKo": "롬앤 제로 벨벳 틴트",
          "shade": "피칸타르트",
          "family": "berry",
          "lightness": "deep",
          "chroma": "medium"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### N05 롬앤 제로 벨벳 틴트 앤셜리 발라볼래

```json
{
  "id": "N05",
  "group": "호수명",
  "message": "롬앤 제로 벨벳 틴트 앤셜리 발라볼래",
  "expected": "롬앤 12호 지정 적용",
  "setup": [],
  "turns": [
    {
      "message": "롬앤 제로 벨벳 틴트 앤셜리 발라볼래",
      "proposal": {
        "choice": "apply_shade/product_shade",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": "oy-a000000120880",
        "shadeId": "12",
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "a1bc6ea0-fbcc-4d9d-8681-4706349cadce",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "4a311d19-b1cc-42cd-8b8c-e39250dd12fd",
        "expectedStateVersion": 48
      },
      "status": "APPLIED",
      "answer": "롬앤 제로 벨벳 틴트 앤셜리는 선명하고 딥한 레드 컬러예요. 발라드렸어요.",
      "elapsedMs": 9342,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "12"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#CC2028",
            "texture": "velvet",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "12"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "12"
        }
      ],
      "result": {
        "choice": "apply_shade/product_shade",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "12",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "앤셜리",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "vivid"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "롬앤",
          "product": "롬앤 제로 벨벳 틴트",
          "productKo": "롬앤 제로 벨벳 틴트",
          "shade": "앤셜리",
          "family": "red",
          "lightness": "deep",
          "chroma": "vivid"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### N06 너드 핑크로 바꿔줘

```json
{
  "id": "N06",
  "group": "호수명",
  "message": "너드 핑크로 바꿔줘",
  "expected": "롬앤 25호 지정 적용",
  "setup": [],
  "turns": [
    {
      "message": "너드 핑크로 바꿔줘",
      "proposal": {
        "choice": "apply_shade/product_shade",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": "oy-a000000120880",
        "shadeId": "25",
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "c24b9c15-f826-46d0-be80-e79060cdba59",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "db43c46a-67ae-4a0e-b9d1-ad7d0ea44a01",
        "expectedStateVersion": 58
      },
      "status": "APPLIED",
      "answer": "롬앤 제로 벨벳 틴트 너드 핑크의 차분하고 깊은 베리 컬러로 바꿨어요.",
      "elapsedMs": 8778,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "25"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#883640",
            "texture": "velvet",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "25"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "25"
        }
      ],
      "result": {
        "choice": "apply_shade/product_shade",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "25",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "너드 핑크",
            "texture": "velvet"
          },
          "color": {
            "family": "berry",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "롬앤",
          "product": "롬앤 제로 벨벳 틴트",
          "productKo": "롬앤 제로 벨벳 틴트",
          "shade": "너드 핑크",
          "family": "berry",
          "lightness": "deep",
          "chroma": "muted"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### N07 얼그레이 숄 그 색으로 발라줘

```json
{
  "id": "N07",
  "group": "호수명",
  "message": "얼그레이 숄 그 색으로 발라줘",
  "expected": "롬앤 19호 지정 적용",
  "setup": [],
  "turns": [
    {
      "message": "얼그레이 숄 그 색으로 발라줘",
      "proposal": {
        "choice": "apply_shade/product_shade",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": "oy-a000000120880",
        "shadeId": "19",
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "05aef5d6-bdb8-407a-9ee6-011844f483b4",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "5f2350a7-a45f-4233-af95-1d8e6e3a7a57",
        "expectedStateVersion": 68
      },
      "status": "APPLIED",
      "answer": "롬앤 제로 벨벳 틴트 얼그레이 숄의 차분하고 짙은 레드 컬러로 발라드렸어요.",
      "elapsedMs": 7669,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "19"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#843939",
            "texture": "velvet",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "19"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "19"
        }
      ],
      "result": {
        "choice": "apply_shade/product_shade",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "19",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "얼그레이 숄",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "롬앤",
          "product": "롬앤 제로 벨벳 틴트",
          "productKo": "롬앤 제로 벨벳 틴트",
          "shade": "얼그레이 숄",
          "family": "red",
          "lightness": "deep",
          "chroma": "muted"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### N08 페이드 레드는 바르지 말고 지금 바른 립 이름만 알려줘

```json
{
  "id": "N08",
  "group": "호수명",
  "message": "페이드 레드는 바르지 말고 지금 바른 립 이름만 알려줘",
  "expected": "현재 제품 조회, 착용 유지",
  "setup": [],
  "turns": [
    {
      "message": "페이드 레드는 바르지 말고 지금 바른 립 이름만 알려줘",
      "proposal": {
        "choice": "get_state/lip",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "ee1a42e7-f309-4e96-830a-002c73d615df",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "9885d5dd-6bab-4332-80f5-b620254bc3ff",
        "expectedStateVersion": 78
      },
      "status": "OK",
      "answer": "지금 바른 립은 롬앤 제로 벨벳 틴트 ‘빈티지 토프’예요.",
      "elapsedMs": 7679,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": [],
      "result": {
        "choice": "get_state/lip",
        "displayMode": "face",
        "status": "OK",
        "data": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null,
          "center": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "anchor": null,
          "activeZone": "lip"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### N09 페이드 레드도 있어? 아직 바르지는 말고

```json
{
  "id": "N09",
  "group": "호수명",
  "message": "페이드 레드도 있어? 아직 바르지는 말고",
  "expected": "조회 또는 안내, 착용 유지",
  "setup": [],
  "turns": [
    {
      "message": "페이드 레드도 있어? 아직 바르지는 말고",
      "proposal": {
        "choice": "find_shades/lip",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": "list",
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "68d63e64-72ed-4fdd-86ba-a34396b32133",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "7ae04249-ce73-4334-9fc5-74fb4027d241",
        "expectedStateVersion": 87
      },
      "status": "OK",
      "answer": "네, 퓌 3D 볼류밍 글로스에서 페이드 레드 색상을 찾을 수 있어요. 아직 바르지는 않았어요.",
      "elapsedMs": 8763,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": [],
      "result": {
        "choice": "find_shades/lip",
        "displayMode": "face",
        "status": "OK",
        "data": {
          "count": 5074,
          "shades": [
            {
              "productId": "oy-a000000246445",
              "shadeId": "a000000246445-044",
              "brand": "퓌",
              "product": "[얼그레이에디션/10월 올영픽] 퓌 3D 볼류밍 글로스 (기획/단품)",
              "shade": "얼그레이 70%",
              "texture": "glossy"
            },
            {
              "productId": "oy-a000000246445",
              "shadeId": "a000000246445-040",
              "brand": "퓌",
              "product": "[얼그레이에디션/10월 올영픽] 퓌 3D 볼류밍 글로스 (기획/단품)",
              "shade": "차이 70%",
              "texture": "glossy"
            },
            {
              "productId": "oy-a000000246445",
              "shadeId": "a000000246445-045",
              "brand": "퓌",
              "product": "[얼그레이에디션/10월 올영픽] 퓌 3D 볼류밍 글로스 (기획/단품)",
              "shade": "오트우롱 70%",
              "texture": "glossy"
            },
            {
              "productId": "oy-a000000246445",
              "shadeId": "a000000246445-041",
              "brand": "퓌",
              "product": "[얼그레이에디션/10월 올영픽] 퓌 3D 볼류밍 글로스 (기획/단품)",
              "shade": "블랙티 70%",
              "texture": "glossy"
            },
            {
              "productId": "oy-a000000246445",
              "shadeId": "a000000246445-035",
              "brand": "퓌",
              "product": "[얼그레이에디션/10월 올영픽] 퓌 3D 볼류밍 글로스 (기획/단품)",
              "shade": "밀크티 70%",
              "texture": "glossy"
            },
            {
              "productId": "oy-a000000246445",
              "shadeId": "a000000246445-034",
              "brand": "퓌",
              "product": "[얼그레이에디션/10월 올영픽] 퓌 3D 볼류밍 글로스 (기획/단품)",
              "shade": "피치우롱 70%",
              "texture": "glossy"
            },
            {
              "productId": "oy-a000000246445",
              "shadeId": "a000000246445-033",
              "brand": "퓌",
              "product": "[얼그레이에디션/10월 올영픽] 퓌 3D 볼류밍 글로스 (기획/단품)",
              "shade": "로즈힙 70%",
              "texture": "glossy"
            },
            {
              "productId": "oy-a000000246445",
              "shadeId": "a000000246445-036",
              "brand": "퓌",
              "product": "[얼그레이에디션/10월 올영픽] 퓌 3D 볼류밍 글로스 (기획/단품)",
              "shade": "허니듀 70%",
              "texture": "glossy"
            },
            {
              "productId": "oy-a000000246445",
              "shadeId": "a000000246445-030",
              "brand": "퓌",
              "product": "[얼그레이에디션/10월 올영픽] 퓌 3D 볼류밍 글로스 (기획/단품)",
              "shade": "바닐라 70%",
              "texture": "glossy"
            },
            {
              "productId": "oy-a000000246445",
              "shadeId": "a000000246445-028",
              "brand": "퓌",
              "product": "[얼그레이에디션/10월 올영픽] 퓌 3D 볼류밍 글로스 (기획/단품)",
              "shade": "바닐라 소르베 70%",
              "texture": "glossy"
            },
            {
              "productId": "oy-a000000246445",
              "shadeId": "a000000246445-032",
              "brand": "퓌",
              "product": "[얼그레이에디션/10월 올영픽] 퓌 3D 볼류밍 글로스 (기획/단품)",
              "shade": "바닐라 쿠키 70%",
              "texture": "glossy"
            },
            {
              "productId": "oy-a000000246445",
              "shadeId": "a000000246445-031",
              "brand": "퓌",
              "product": "[얼그레이에디션/10월 올영픽] 퓌 3D 볼류밍 글로스 (기획/단품)",
              "shade": "바닐라 소르베 70%",
              "texture": "glossy"
            }
          ]
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### N10 별빛구름맛이라는 립으로 발라줘

```json
{
  "id": "N10",
  "group": "호수명",
  "message": "별빛구름맛이라는 립으로 발라줘",
  "expected": "없는 호수는 안내 또는 거절, 착용 유지",
  "setup": [],
  "turns": [
    {
      "message": "별빛구름맛이라는 립으로 발라줘",
      "proposal": {
        "choice": "apply_shade/lip/by_color",
        "family": "nude",
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "1fa0b630-e924-4b3c-b9c8-6635c380ce1f",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "b5110f56-0c67-4121-8f08-65c13ff28150",
        "expectedStateVersion": 96
      },
      "status": "APPLIED",
      "answer": "토니모리 [한정기획] 겟잇 틴트 워터풀 시럽의 밀키누드시럽을 발라드렸어요. 가볍고 차분한 누드 색감이에요.",
      "elapsedMs": 8981,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000223922",
            "shadeId": "16"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#C79685",
            "texture": "sheer",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000223922",
            "shadeId": "16"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000223922",
          "shadeId": "16"
        }
      ],
      "result": {
        "choice": "apply_shade/lip/by_color",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000223922",
            "shadeId": "16",
            "brand": "토니모리",
            "product": "[한정기획] 토니모리 겟잇 틴트 워터풀 시럽",
            "shade": "밀키누드시럽",
            "texture": "sheer"
          },
          "color": {
            "family": "nude",
            "lightness": "light",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "토니모리",
          "product": "[한정기획] 토니모리 겟잇 틴트 워터풀 시럽",
          "productKo": "[한정기획] 토니모리 겟잇 틴트 워터풀 시럽",
          "shade": "밀키누드시럽",
          "family": "nude",
          "lightness": "light",
          "chroma": "muted"
        }
      }
    }
  ],
  "passed": false,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  },
  "error": "expect(received).toEqual(expected) // deep equality\n\n- Expected  - 2\n+ Received  + 2\n\n@@ -2,9 +2,9 @@\n    \"blush\": Object {\n      \"productId\": \"oy-a000000171371\",\n      \"shadeId\": \"a000000171371-044\",\n    },\n    \"lip\": Object {\n-     \"productId\": \"oy-a000000120880\",\n-     \"shadeId\": \"23\",\n+     \"productId\": \"oy-a000000223922\",\n+     \"shadeId\": \"16\",\n    },\n  }"
}
```

### C01 차분한 레드로 발라줘

```json
{
  "id": "C01",
  "group": "색감",
  "message": "차분한 레드로 발라줘",
  "expected": "레드·낮은 채도로 추천 적용",
  "setup": [],
  "turns": [
    {
      "message": "차분한 레드로 발라줘",
      "proposal": {
        "choice": "apply_shade/lip/by_color",
        "family": "red",
        "lightness": null,
        "chroma": "muted",
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "90e41c6a-1892-4fd1-86de-e0350d658dcb",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "7f873888-4556-412b-bf2d-8fe0930323b1",
        "expectedStateVersion": 106
      },
      "status": "APPLIED",
      "answer": "퓌 [얼그레이에디션/10월 올영픽] 퓌 3D 볼류밍 글로스 (기획/단품)의 바닐라 쿠키 70%를 발랐어요. 차분한 미디엄 레드예요.",
      "elapsedMs": 7610,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000246445",
            "shadeId": "a000000246445-032"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#975A56",
            "texture": "glossy",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000246445",
            "shadeId": "a000000246445-032"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000246445",
          "shadeId": "a000000246445-032"
        }
      ],
      "result": {
        "choice": "apply_shade/lip/by_color",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000246445",
            "shadeId": "a000000246445-032",
            "brand": "퓌",
            "product": "[얼그레이에디션/10월 올영픽] 퓌 3D 볼류밍 글로스 (기획/단품)",
            "shade": "바닐라 쿠키 70%",
            "texture": "glossy"
          },
          "color": {
            "family": "red",
            "lightness": "medium",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "퓌",
          "product": "[얼그레이에디션/10월 올영픽] 퓌 3D 볼류밍 글로스 (기획/단품)",
          "productKo": "[얼그레이에디션/10월 올영픽] 퓌 3D 볼류밍 글로스 (기획/단품)",
          "shade": "바닐라 쿠키 70%",
          "family": "red",
          "lightness": "medium",
          "chroma": "muted"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### C02 쨍한 핑크 말고 좀 차분한 핑크로 해줘

```json
{
  "id": "C02",
  "group": "색감",
  "message": "쨍한 핑크 말고 좀 차분한 핑크로 해줘",
  "expected": "핑크·낮은 채도로 추천 적용",
  "setup": [],
  "turns": [
    {
      "message": "쨍한 핑크 말고 좀 차분한 핑크로 해줘",
      "proposal": {
        "choice": "apply_shade/lip/by_color",
        "family": "pink",
        "lightness": null,
        "chroma": "muted",
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "617d5a76-2d3c-4267-8590-5a22afd09e84",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "8a58369c-91b8-4024-aa9f-f83da5c9529f",
        "expectedStateVersion": 116
      },
      "status": "APPLIED",
      "answer": "잉가 워터 글로우 립 틴트 ‘스플래쉬’로 바꿨어요. 쨍하지 않고 차분한 미디엄 핑크예요.",
      "elapsedMs": 9719,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000209877",
            "shadeId": "a000000209877-007"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#CB899E",
            "texture": "sheer",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000209877",
            "shadeId": "a000000209877-007"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000209877",
          "shadeId": "a000000209877-007"
        }
      ],
      "result": {
        "choice": "apply_shade/lip/by_color",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000209877",
            "shadeId": "a000000209877-007",
            "brand": "잉가",
            "product": "[아이돌PICK] 잉가 워터 글로우 립 틴트 4.5g_13컬러",
            "shade": "스플래쉬",
            "texture": "sheer"
          },
          "color": {
            "family": "pink",
            "lightness": "medium",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "잉가",
          "product": "[아이돌PICK] 잉가 워터 글로우 립 틴트 4.5g_13컬러",
          "productKo": "[아이돌PICK] 잉가 워터 글로우 립 틴트 4.5g_13컬러",
          "shade": "스플래쉬",
          "family": "pink",
          "lightness": "medium",
          "chroma": "muted"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### C03 입술은 쨍한 빨강으로 포인트 줘

```json
{
  "id": "C03",
  "group": "색감",
  "message": "입술은 쨍한 빨강으로 포인트 줘",
  "expected": "레드·높은 채도로 추천 적용",
  "setup": [],
  "turns": [
    {
      "message": "입술은 쨍한 빨강으로 포인트 줘",
      "proposal": {
        "choice": "apply_shade/lip/by_color",
        "family": "red",
        "lightness": null,
        "chroma": "vivid",
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "1b0fb472-ae27-4286-ac16-9fd737838ea1",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "bc920d3f-c4da-4cd4-a7a0-829eb5d2acfe",
        "expectedStateVersion": 126
      },
      "status": "APPLIED",
      "answer": "누즈 무스 립추얼 러비 코랄의 선명하고 짙은 레드로 입술에 포인트를 줬어요.",
      "elapsedMs": 8150,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000192940",
            "shadeId": "02"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#C22B3B",
            "texture": "matte",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000192940",
            "shadeId": "02"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000192940",
          "shadeId": "02"
        }
      ],
      "result": {
        "choice": "apply_shade/lip/by_color",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000192940",
            "shadeId": "02",
            "brand": "누즈",
            "product": "[매끈보송립] 누즈 무스 립추얼 6Colors",
            "shade": "러비 코랄",
            "texture": "matte"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "vivid"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "누즈",
          "product": "[매끈보송립] 누즈 무스 립추얼 6Colors",
          "productKo": "[매끈보송립] 누즈 무스 립추얼 6Colors",
          "shade": "러비 코랄",
          "family": "red",
          "lightness": "deep",
          "chroma": "vivid"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### C04 밝고 여리여리한 핑크 립 발라줘

```json
{
  "id": "C04",
  "group": "색감",
  "message": "밝고 여리여리한 핑크 립 발라줘",
  "expected": "핑크·밝은 톤으로 추천 적용",
  "setup": [],
  "turns": [
    {
      "message": "밝고 여리여리한 핑크 립 발라줘",
      "proposal": {
        "choice": "apply_shade/lip/by_color",
        "family": "pink",
        "lightness": "light",
        "chroma": "muted",
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "e223a4f6-0e7b-47b6-9658-2bf6a916a505",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "d4ded60c-d14e-404e-afcf-de8c59e7a119",
        "expectedStateVersion": 136
      },
      "status": "APPLIED",
      "answer": "어뮤즈 립 스머져 ‘복숭아 우유’로 밝고 여리여리한 핑크 립을 발라드렸어요.",
      "elapsedMs": 7967,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000188432",
            "shadeId": "05"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#F7A8C9",
            "texture": "cream",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000188432",
            "shadeId": "05"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000188432",
          "shadeId": "05"
        }
      ],
      "result": {
        "choice": "apply_shade/lip/by_color",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000188432",
            "shadeId": "05",
            "brand": "어뮤즈",
            "product": "어뮤즈 립 스머져  0.5g 6종",
            "shade": "복숭아 우유",
            "texture": "cream"
          },
          "color": {
            "family": "pink",
            "lightness": "light",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "어뮤즈",
          "product": "어뮤즈 립 스머져  0.5g 6종",
          "productKo": "어뮤즈 립 스머져  0.5g 6종",
          "shade": "복숭아 우유",
          "family": "pink",
          "lightness": "light",
          "chroma": "muted"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### C05 이번엔 코랄빛 립으로 바꿔볼래

```json
{
  "id": "C05",
  "group": "색감",
  "message": "이번엔 코랄빛 립으로 바꿔볼래",
  "expected": "코랄 계열 추천 적용",
  "setup": [],
  "turns": [
    {
      "message": "이번엔 코랄빛 립으로 바꿔볼래",
      "proposal": {
        "choice": "apply_shade/lip/by_color",
        "family": "coral",
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "10baaf97-bd90-44cd-9646-25cc62a067ff",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "3e5d9c25-d07c-408e-a11e-96e1a25334f5",
        "expectedStateVersion": 146
      },
      "status": "APPLIED",
      "answer": "얼터너티브스테레오 립 포션 슈가 글레이즈 틴트 8ml의 호 누디 볼로 바꿨어요. 가볍고 은은한 코랄빛이에요.",
      "elapsedMs": 8066,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000211723",
            "shadeId": "1"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#F58D74",
            "texture": "glossy",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000211723",
            "shadeId": "1"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000211723",
          "shadeId": "1"
        }
      ],
      "result": {
        "choice": "apply_shade/lip/by_color",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000211723",
            "shadeId": "1",
            "brand": "얼터너티브스테레오",
            "product": "얼터너티브스테레오 립 포션 슈가 글레이즈 틴트 8ml",
            "shade": "호 누디 볼",
            "texture": "glossy"
          },
          "color": {
            "family": "coral",
            "lightness": "light",
            "chroma": "medium"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "얼터너티브스테레오",
          "product": "얼터너티브스테레오 립 포션 슈가 글레이즈 틴트 8ml",
          "productKo": "얼터너티브스테레오 립 포션 슈가 글레이즈 틴트 8ml",
          "shade": "호 누디 볼",
          "family": "coral",
          "lightness": "light",
          "chroma": "medium"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### C06 입술에 딥한 브라운으로 분위기 내줘

```json
{
  "id": "C06",
  "group": "색감",
  "message": "입술에 딥한 브라운으로 분위기 내줘",
  "expected": "브라운·어두운 톤 추천 적용",
  "setup": [],
  "turns": [
    {
      "message": "입술에 딥한 브라운으로 분위기 내줘",
      "proposal": {
        "choice": "apply_shade/lip/by_color",
        "family": "brown",
        "lightness": "deep",
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "d4a2d7c0-67ed-4ab6-ae87-42d1c1aaca58",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "4fe60d73-1077-499f-9fbf-12c3ec9513c3",
        "expectedStateVersion": 156
      },
      "status": "APPLIED",
      "answer": "3CE 글레이지 립 글로우의 솔티 스윗으로 입술에 딥하고 차분한 브라운 무드를 더했어요.",
      "elapsedMs": 7506,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000240091",
            "shadeId": "a000000240091-002"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#774335",
            "texture": "glossy",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000240091",
            "shadeId": "a000000240091-002"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000240091",
          "shadeId": "a000000240091-002"
        }
      ],
      "result": {
        "choice": "apply_shade/lip/by_color",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000240091",
            "shadeId": "a000000240091-002",
            "brand": "3CE",
            "product": "[NEW/쿠로미에디션]  3CE 글레이지 립 글로우 3.2g 기획/단품",
            "shade": "솔티 스윗",
            "texture": "glossy"
          },
          "color": {
            "family": "brown",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "3CE",
          "product": "[NEW/쿠로미에디션]  3CE 글레이지 립 글로우 3.2g 기획/단품",
          "productKo": "[NEW/쿠로미에디션]  3CE 글레이지 립 글로우 3.2g 기획/단품",
          "shade": "솔티 스윗",
          "family": "brown",
          "lightness": "deep",
          "chroma": "muted"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### C07 누드톤 립 하나 골라서 발라줘

```json
{
  "id": "C07",
  "group": "색감",
  "message": "누드톤 립 하나 골라서 발라줘",
  "expected": "누드 계열 추천 적용",
  "setup": [],
  "turns": [
    {
      "message": "누드톤 립 하나 골라서 발라줘",
      "proposal": {
        "choice": "apply_shade/lip/by_color",
        "family": "nude",
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "3b48ab63-d574-4b00-a67d-d66ed67b4661",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "89d5f635-3760-4189-b2eb-a629aec3088f",
        "expectedStateVersion": 166
      },
      "status": "APPLIED",
      "answer": "토니모리 겟잇 틴트 워터풀 시럽 밀키누드시럽을 발라드렸어요. 부드럽고 차분한 연한 누드톤이에요.",
      "elapsedMs": 6195,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000223922",
            "shadeId": "16"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#C79685",
            "texture": "sheer",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000223922",
            "shadeId": "16"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000223922",
          "shadeId": "16"
        }
      ],
      "result": {
        "choice": "apply_shade/lip/by_color",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000223922",
            "shadeId": "16",
            "brand": "토니모리",
            "product": "[한정기획] 토니모리 겟잇 틴트 워터풀 시럽",
            "shade": "밀키누드시럽",
            "texture": "sheer"
          },
          "color": {
            "family": "nude",
            "lightness": "light",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "토니모리",
          "product": "[한정기획] 토니모리 겟잇 틴트 워터풀 시럽",
          "productKo": "[한정기획] 토니모리 겟잇 틴트 워터풀 시럽",
          "shade": "밀키누드시럽",
          "family": "nude",
          "lightness": "light",
          "chroma": "muted"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### C08 블러셔는 연한 핑크빛으로 올려줘

```json
{
  "id": "C08",
  "group": "색감",
  "message": "블러셔는 연한 핑크빛으로 올려줘",
  "expected": "블러셔 핑크·밝은 톤 추천 적용",
  "setup": [],
  "turns": [
    {
      "message": "블러셔는 연한 핑크빛으로 올려줘",
      "proposal": {
        "choice": "apply_shade/blush/by_color",
        "family": "pink",
        "lightness": "light",
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "794e0e46-a0c3-4f27-ba7f-2a4d4e08385e",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "fdf119f1-c5f8-4964-95df-06ecc9177db2",
        "expectedStateVersion": 176
      },
      "status": "APPLIED",
      "answer": "어뮤즈 치크 톡톡의 럽미 톡으로 연한 핑크빛 블러셔를 올렸어요.",
      "elapsedMs": 5269,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000212026",
            "shadeId": "05"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#FF93BB",
            "texture": "glossy",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "blush",
            "productId": "oy-a000000212026",
            "shadeId": "05"
          }
        ]
      },
      "history": [
        {
          "zone": "blush",
          "productId": "oy-a000000212026",
          "shadeId": "05"
        }
      ],
      "result": {
        "choice": "apply_shade/blush/by_color",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "blush",
          "product": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044",
            "brand": "네이밍",
            "product": "[1등 블러셔/모공블러] 네이밍 플러피 파우더 블러쉬 20colors",
            "shade": "베이크드",
            "texture": "velvet"
          },
          "color": {
            "family": "nude",
            "lightness": "medium",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null
        },
        "after": {
          "zone": "blush",
          "product": {
            "productId": "oy-a000000212026",
            "shadeId": "05",
            "brand": "어뮤즈",
            "product": "어뮤즈 치크 톡톡 10종",
            "shade": "럽미 톡",
            "texture": "glossy"
          },
          "color": {
            "family": "pink",
            "lightness": "light",
            "chroma": "medium"
          },
          "intensity": 0.55,
          "geometry": null
        },
        "featuredShade": {
          "brand": "어뮤즈",
          "product": "어뮤즈 치크 톡톡 10종",
          "productKo": "어뮤즈 치크 톡톡 10종",
          "shade": "럽미 톡",
          "family": "pink",
          "lightness": "light",
          "chroma": "medium"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### C09 여리여리한 느낌으로 립 하나 골라 발라줘

```json
{
  "id": "C09",
  "group": "색감",
  "message": "여리여리한 느낌으로 립 하나 골라 발라줘",
  "expected": "밝고 낮은 채도의 립 추천 적용",
  "setup": [],
  "turns": [
    {
      "message": "여리여리한 느낌으로 립 하나 골라 발라줘",
      "proposal": {
        "choice": "apply_shade/lip/by_color",
        "family": null,
        "lightness": "light",
        "chroma": "muted",
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "e796bf83-b645-41ef-acf4-fd11dcfed07c",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "07dd21c0-d5de-4461-aab3-25708b354b35",
        "expectedStateVersion": 186
      },
      "status": "APPLIED",
      "answer": "어뮤즈 듀 틴트 ‘도토리’의 여린 누드 컬러를 발라드렸어요.",
      "elapsedMs": 5852,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000158147",
            "shadeId": "11"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#EAACAB",
            "texture": "glossy",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000158147",
            "shadeId": "11"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000158147",
          "shadeId": "11"
        }
      ],
      "result": {
        "choice": "apply_shade/lip/by_color",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000158147",
            "shadeId": "11",
            "brand": "어뮤즈",
            "product": "어뮤즈 듀 틴트 4g 13종 (기획/단품)",
            "shade": "도토리",
            "texture": "glossy"
          },
          "color": {
            "family": "nude",
            "lightness": "light",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "어뮤즈",
          "product": "어뮤즈 듀 틴트 4g 13종 (기획/단품)",
          "productKo": "어뮤즈 듀 틴트 4g 13종 (기획/단품)",
          "shade": "도토리",
          "family": "nude",
          "lightness": "light",
          "chroma": "muted"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### C10 입술은 선명한 베리 컬러로 해줘

```json
{
  "id": "C10",
  "group": "색감",
  "message": "입술은 선명한 베리 컬러로 해줘",
  "expected": "베리·높은 채도로 추천 적용",
  "setup": [],
  "turns": [
    {
      "message": "입술은 선명한 베리 컬러로 해줘",
      "proposal": {
        "choice": "apply_shade/lip/by_color",
        "family": "berry",
        "lightness": null,
        "chroma": "vivid",
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "24a1ae23-ce74-4a1c-a4e8-7b2ebe59351e",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "ecf59410-b2c0-49e7-851a-429f774c8c50",
        "expectedStateVersion": 196
      },
      "status": "APPLIED",
      "answer": "입술에 맥 맥시멀 슬릭 새틴 립스틱 팝스타 핑크를 발라 선명하고 깊은 베리 컬러로 연출했어요.",
      "elapsedMs": 6089,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000211288",
            "shadeId": "a000000211288-008"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#A90266",
            "texture": "satin",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000211288",
            "shadeId": "a000000211288-008"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000211288",
          "shadeId": "a000000211288-008"
        }
      ],
      "result": {
        "choice": "apply_shade/lip/by_color",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000211288",
            "shadeId": "a000000211288-008",
            "brand": "맥",
            "product": "MAC 맥시멀 슬릭 새틴 립스틱 11 Colors",
            "shade": "팝스타 핑크",
            "texture": "satin"
          },
          "color": {
            "family": "berry",
            "lightness": "deep",
            "chroma": "vivid"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "맥",
          "product": "MAC 맥시멀 슬릭 새틴 립스틱 11 Colors",
          "productKo": "MAC 맥시멀 슬릭 새틴 립스틱 11 Colors",
          "shade": "팝스타 핑크",
          "family": "berry",
          "lightness": "deep",
          "chroma": "vivid"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### M01 조금 더

```json
{
  "id": "M01",
  "group": "멀티턴",
  "message": "조금 더",
  "expected": "립 감소의 연속, 0.45 → 0.40",
  "setup": [
    {
      "say": "립 좀 연하게 해줘",
      "status": "APPLIED"
    }
  ],
  "turns": [
    {
      "message": "립 좀 연하게 해줘",
      "proposal": {
        "choice": "adjust_intensity/lip/down",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": 1,
        "ordinal": null,
        "value": null,
        "sessionId": "0f5d3e55-deaf-4567-9672-604a72662c7b",
        "onAppliedReply": "립 컬러를 한층 부드럽고 은은하게 낮춰드렸어요.",
        "action": "ar_control",
        "commandId": "7a0b238f-ec03-4306-898f-06e5d14b4836",
        "expectedStateVersion": 206
      },
      "status": "APPLIED",
      "answer": "립 컬러를 한층 부드럽고 은은하게 낮춰드렸어요.",
      "elapsedMs": 5476,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.45
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": []
    },
    {
      "message": "조금 더",
      "proposal": {
        "choice": "adjust_intensity/lip/down",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "0f5d3e55-deaf-4567-9672-604a72662c7b",
        "fineAdjustment": true,
        "onAppliedReply": "입술 색을 한결 더 부드럽고 은은하게 낮춰드렸어요. 이 정도가 괜찮으실까요?",
        "action": "ar_control",
        "commandId": "562ec4a9-1aac-475b-a45f-e19ef85f6a6e",
        "expectedStateVersion": 207
      },
      "status": "APPLIED",
      "answer": "입술 색을 한결 더 부드럽고 은은하게 낮춰드렸어요. 이 정도가 괜찮으실까요?",
      "elapsedMs": 4906,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.4
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": []
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### M02 거기서 딱 한 끗만 더

```json
{
  "id": "M02",
  "group": "멀티턴",
  "message": "거기서 딱 한 끗만 더",
  "expected": "립 감소의 연속, 0.45 → 0.40",
  "setup": [
    {
      "say": "립 좀 연하게 해줘",
      "status": "APPLIED"
    }
  ],
  "turns": [
    {
      "message": "립 좀 연하게 해줘",
      "proposal": {
        "choice": "adjust_intensity/lip/down",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "5c5da64e-d6ec-44f9-98ee-1a6669861d5f",
        "onAppliedReply": "립 컬러를 한층 부드럽고 은은하게 낮춰드렸어요. 어떠세요?",
        "action": "ar_control",
        "commandId": "32ea4408-4cce-420c-ba52-bcad43526fa3",
        "expectedStateVersion": 217
      },
      "status": "APPLIED",
      "answer": "립 컬러를 한층 부드럽고 은은하게 낮춰드렸어요. 어떠세요?",
      "elapsedMs": 8319,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.45
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": []
    },
    {
      "message": "거기서 딱 한 끗만 더",
      "proposal": {
        "choice": "adjust_intensity/lip/down",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "5c5da64e-d6ec-44f9-98ee-1a6669861d5f",
        "fineAdjustment": true,
        "onAppliedReply": "립 컬러를 아주 살짝 더 부드럽게 낮췄어요. 이 정도가 원하신 느낌일까요?",
        "action": "ar_control",
        "commandId": "579fa126-806e-4a04-a272-4400473e3f0f",
        "expectedStateVersion": 218
      },
      "status": "APPLIED",
      "answer": "립 컬러를 아주 살짝 더 부드럽게 낮췄어요. 이 정도가 원하신 느낌일까요?",
      "elapsedMs": 6334,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.4
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": []
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### M03 조금 더

```json
{
  "id": "M03",
  "group": "멀티턴",
  "message": "조금 더",
  "expected": "열린 립 팔레트 대신 블러셔 증가, 0.65 → 0.70",
  "setup": [
    {
      "say": "블러셔를 조금 진하게 해줘",
      "status": "APPLIED"
    }
  ],
  "turns": [
    {
      "message": "블러셔를 조금 진하게 해줘",
      "proposal": {
        "choice": "adjust_intensity/blush/up",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "b22b8161-8e0c-4f17-bd03-5335402b50df",
        "onAppliedReply": "블러셔를 조금 더 선명하고 생기 있게 올려드렸어요. 느낌 괜찮으신가요?",
        "action": "ar_control",
        "commandId": "2c1179b0-721f-44a0-b0ae-2f5319b5f524",
        "expectedStateVersion": 228
      },
      "status": "APPLIED",
      "answer": "블러셔를 조금 더 선명하고 생기 있게 올려드렸어요. 느낌 괜찮으신가요?",
      "elapsedMs": 7210,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.65
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": []
    },
    {
      "message": "조금 더",
      "proposal": {
        "choice": "adjust_intensity/blush/up",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "b22b8161-8e0c-4f17-bd03-5335402b50df",
        "fineAdjustment": true,
        "onAppliedReply": "블러셔를 살짝 더 또렷하게 올려봤어요. 느낌 어떠세요?",
        "action": "ar_control",
        "commandId": "74d11073-5547-4778-a995-a28112c79ffa",
        "expectedStateVersion": 229
      },
      "status": "APPLIED",
      "answer": "블러셔를 살짝 더 또렷하게 올려봤어요. 느낌 어떠세요?",
      "elapsedMs": 5241,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.7
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": []
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### M04 한 번만 더 덜어줘

```json
{
  "id": "M04",
  "group": "멀티턴",
  "message": "한 번만 더 덜어줘",
  "expected": "블러셔 감소의 연속, 0.45 → 0.40",
  "setup": [
    {
      "say": "블러셔를 살짝 연하게 해줘",
      "status": "APPLIED"
    }
  ],
  "turns": [
    {
      "message": "블러셔를 살짝 연하게 해줘",
      "proposal": {
        "choice": "adjust_intensity/blush/down",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "3283e27b-f431-4527-add3-c7d413a4dd3b",
        "onAppliedReply": "블러셔를 살짝 부드럽게 낮췄어요. 느낌 괜찮으신가요?",
        "action": "ar_control",
        "commandId": "bf462b18-5ddd-4f01-92ea-3bbdaf1f173c",
        "expectedStateVersion": 239
      },
      "status": "APPLIED",
      "answer": "블러셔를 살짝 부드럽게 낮췄어요. 느낌 괜찮으신가요?",
      "elapsedMs": 8963,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.45
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": []
    },
    {
      "message": "한 번만 더 덜어줘",
      "proposal": {
        "choice": "adjust_intensity/blush/down",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "3283e27b-f431-4527-add3-c7d413a4dd3b",
        "fineAdjustment": true,
        "onAppliedReply": "볼터치를 한층 더 부드럽고 은은하게 덜어드렸어요. 느낌 괜찮으신가요?",
        "action": "ar_control",
        "commandId": "9c1c0ac6-e540-46a6-8958-a8ff820eb80c",
        "expectedStateVersion": 240
      },
      "status": "APPLIED",
      "answer": "볼터치를 한층 더 부드럽고 은은하게 덜어드렸어요. 느낌 괜찮으신가요?",
      "elapsedMs": 5939,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.4
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": []
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### M05 거기서 조금 더 연하게

```json
{
  "id": "M05",
  "group": "멀티턴",
  "message": "거기서 조금 더 연하게",
  "expected": "실제 직전 폭 0.30의 절반인 0.15 감소",
  "setup": [
    {
      "zone": "lip",
      "intensity": 0.6,
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.6
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      }
    },
    {
      "say": "입술은 지금의 반만 남겨줘",
      "status": "APPLIED"
    }
  ],
  "turns": [
    {
      "message": "입술은 지금의 반만 남겨줘",
      "proposal": {
        "choice": "set_intensity/lip/half",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "0d052613-7b0f-43f4-990b-a6dec88c84ab",
        "onAppliedReply": "입술 색을 지금보다 한층 부드럽게 줄여드렸어요. 어떠세요?",
        "action": "ar_control",
        "commandId": "07322291-a574-421e-bf22-c6ba859778ff",
        "expectedStateVersion": 251
      },
      "status": "APPLIED",
      "answer": "입술 색을 지금보다 한층 부드럽게 줄여드렸어요. 어떠세요?",
      "elapsedMs": 8298,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.3
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": []
    },
    {
      "message": "거기서 조금 더 연하게",
      "proposal": {
        "choice": "adjust_intensity/lip/down",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "0d052613-7b0f-43f4-990b-a6dec88c84ab",
        "fineAdjustment": true,
        "onAppliedReply": "립 컬러를 조금 더 부드럽고 은은하게 낮춰볼게요. 어떠신가요?",
        "action": "ar_control",
        "commandId": "161a618c-122a-438b-bcf3-60aed5fecca5",
        "expectedStateVersion": 252
      },
      "status": "APPLIED",
      "answer": "립 컬러를 조금 더 부드럽고 은은하게 낮춰볼게요. 어떠신가요?",
      "elapsedMs": 6010,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.15
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": []
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### M06 여기서 조금만 더

```json
{
  "id": "M06",
  "group": "멀티턴",
  "message": "여기서 조금만 더",
  "expected": "직전 폭 0.05의 절반 반올림, 0.40 → 0.37",
  "setup": [
    {
      "say": "립 좀 연하게 해줘",
      "status": "APPLIED"
    },
    {
      "say": "조금 더",
      "status": "APPLIED"
    }
  ],
  "turns": [
    {
      "message": "립 좀 연하게 해줘",
      "proposal": {
        "choice": "adjust_intensity/lip/down",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "348b29c8-a007-4c75-aac4-c33faf40f414",
        "onAppliedReply": "립 컬러를 조금 부드럽고 은은하게 낮춰봤어요. 어떠세요?",
        "action": "ar_control",
        "commandId": "36980a45-c29f-4262-b7c2-14210c54ab63",
        "expectedStateVersion": 262
      },
      "status": "APPLIED",
      "answer": "립 컬러를 조금 부드럽고 은은하게 낮춰봤어요. 어떠세요?",
      "elapsedMs": 7304,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.45
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": []
    },
    {
      "message": "조금 더",
      "proposal": {
        "choice": "adjust_intensity/lip/down",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "348b29c8-a007-4c75-aac4-c33faf40f414",
        "fineAdjustment": true,
        "onAppliedReply": "립 컬러를 한결 부드럽고 은은하게 낮췄어요. 이 정도가 괜찮으실까요?",
        "action": "ar_control",
        "commandId": "ea6582aa-bfbe-4da8-8be0-82dca91864a2",
        "expectedStateVersion": 263
      },
      "status": "APPLIED",
      "answer": "립 컬러를 한결 부드럽고 은은하게 낮췄어요. 이 정도가 괜찮으실까요?",
      "elapsedMs": 7359,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.4
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": []
    },
    {
      "message": "여기서 조금만 더",
      "proposal": {
        "choice": "adjust_intensity/lip/down",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "348b29c8-a007-4c75-aac4-c33faf40f414",
        "fineAdjustment": true,
        "onAppliedReply": "입술 컬러를 살짝 더 부드럽게 눌러드렸어요. 이 정도가 괜찮으세요?",
        "action": "ar_control",
        "commandId": "1de74a4c-1a64-47d0-8bd7-942336faa661",
        "expectedStateVersion": 264
      },
      "status": "APPLIED",
      "answer": "입술 컬러를 살짝 더 부드럽게 눌러드렸어요. 이 정도가 괜찮으세요?",
      "elapsedMs": 7381,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.37
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": []
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### M07 이번엔 블러셔를 연하게 해줘

```json
{
  "id": "M07",
  "group": "멀티턴",
  "message": "이번엔 블러셔를 연하게 해줘",
  "expected": "새 대상 블러셔 감소, 립 유지",
  "setup": [
    {
      "say": "립 좀 연하게 해줘",
      "status": "APPLIED"
    }
  ],
  "turns": [
    {
      "message": "립 좀 연하게 해줘",
      "proposal": {
        "choice": "adjust_intensity/lip/down",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "61a1d54f-7c9f-41df-bef1-6380e5b933f1",
        "onAppliedReply": "립 컬러를 조금 부드럽게 낮춰봤어요. 느낌 괜찮으신가요?",
        "action": "ar_control",
        "commandId": "fa88fc32-86f1-4b79-a829-fb55278e1540",
        "expectedStateVersion": 274
      },
      "status": "APPLIED",
      "answer": "립 컬러를 조금 부드럽게 낮춰봤어요. 느낌 괜찮으신가요?",
      "elapsedMs": 7290,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.45
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": []
    },
    {
      "message": "이번엔 블러셔를 연하게 해줘",
      "proposal": {
        "choice": "adjust_intensity/blush/down",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "61a1d54f-7c9f-41df-bef1-6380e5b933f1",
        "onAppliedReply": "블러셔 색감을 조금 부드럽게 낮춰드렸어요. 어떠신가요?",
        "action": "ar_control",
        "commandId": "7ad17bea-ac95-4efa-95bf-59fe7a890c54",
        "expectedStateVersion": 275
      },
      "status": "APPLIED",
      "answer": "블러셔 색감을 조금 부드럽게 낮춰드렸어요. 어떠신가요?",
      "elapsedMs": 4442,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.45
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.45
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": []
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### M08 아니다 입술을 좀 더 진하게 해줘

```json
{
  "id": "M08",
  "group": "멀티턴",
  "message": "아니다 입술을 좀 더 진하게 해줘",
  "expected": "명시적으로 바뀐 방향으로 립 증가",
  "setup": [
    {
      "say": "립 좀 연하게 해줘",
      "status": "APPLIED"
    }
  ],
  "turns": [
    {
      "message": "립 좀 연하게 해줘",
      "proposal": {
        "choice": "adjust_intensity/lip/down",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "a742ca3c-d0dc-4161-8d4c-5c98ddb37b3e",
        "onAppliedReply": "립 컬러를 살짝 눌러 더 은은하게 정리해드렸어요. 어떠세요?",
        "action": "ar_control",
        "commandId": "fec71660-1622-40a7-80af-3337c4ccd19f",
        "expectedStateVersion": 285
      },
      "status": "APPLIED",
      "answer": "립 컬러를 살짝 눌러 더 은은하게 정리해드렸어요. 어떠세요?",
      "elapsedMs": 6309,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.45
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": []
    },
    {
      "message": "아니다 입술을 좀 더 진하게 해줘",
      "proposal": {
        "choice": "adjust_intensity/lip/up",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": 1,
        "ordinal": null,
        "value": null,
        "sessionId": "a742ca3c-d0dc-4161-8d4c-5c98ddb37b3e",
        "onAppliedReply": "입술 색을 한층 더 진하게 올려드렸어요. 어떠신가요?",
        "action": "ar_control",
        "commandId": "fb3fdee4-e507-4f87-a85b-3b781002a821",
        "expectedStateVersion": 286
      },
      "status": "APPLIED",
      "answer": "입술 색을 한층 더 진하게 올려드렸어요. 어떠신가요?",
      "elapsedMs": 3692,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.55
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": []
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### M09 조금 더

```json
{
  "id": "M09",
  "group": "멀티턴",
  "message": "조금 더",
  "expected": "수동 제품 변경으로 이전 강도 근거 무효, 되묻고 착용 유지",
  "setup": [
    {
      "say": "립 좀 연하게 해줘",
      "status": "APPLIED"
    },
    {
      "manual": "04",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8B4651",
            "texture": "velvet",
            "intensity": 0.275
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        ]
      }
    }
  ],
  "turns": [
    {
      "message": "립 좀 연하게 해줘",
      "proposal": {
        "choice": "set_intensity/lip/half",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "82aa5f10-a73a-425d-a3ca-ace86d83af94",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "3bcbd3cf-df33-40a0-b811-f7cfb64cf355",
        "expectedStateVersion": 296
      },
      "status": "APPLIED",
      "answer": "립 컬러를 한결 은은하게 낮춰드렸어요.",
      "elapsedMs": 6236,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0.275
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": [],
      "result": {
        "choice": "set_intensity/lip/half",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.55,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.275,
          "geometry": null,
          "lipCare": null
        }
      }
    },
    {
      "message": "조금 더",
      "proposal": {
        "choice": "adjust_intensity/lip/up",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "82aa5f10-a73a-425d-a3ca-ace86d83af94",
        "onAppliedReply": "입술 컬러를 조금 더 또렷하고 대담하게 올려드렸어요. 어떠세요?",
        "action": "ar_control",
        "commandId": "17656390-e7dd-420f-8c0a-413d60d2a67d",
        "expectedStateVersion": 298
      },
      "status": "APPLIED",
      "answer": "입술 컬러를 조금 더 또렷하고 대담하게 올려드렸어요. 어떠세요?",
      "elapsedMs": 4962,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8B4651",
            "texture": "velvet",
            "intensity": 0.375
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "04"
        }
      ]
    }
  ],
  "passed": false,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  },
  "error": "expect(received).toEqual(expected) // deep equality\n\n- Expected  - 1\n+ Received  + 1\n\n@@ -10,10 +10,10 @@\n    \"eyeshadow\": null,\n    \"foundation\": null,\n    \"highlighter\": null,\n    \"lip\": Object {\n      \"hex\": \"#8B4651\",\n-     \"intensity\": 0.275,\n+     \"intensity\": 0.375,\n      \"texture\": \"velvet\",\n    },\n    \"mascara\": null,\n  }"
}
```

### M10 입술 더 연하게 해줘

```json
{
  "id": "M10",
  "group": "멀티턴",
  "message": "입술 더 연하게 해줘",
  "expected": "최솟값에서 변화 없음",
  "setup": [
    {
      "zone": "lip",
      "intensity": 0,
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      }
    }
  ],
  "turns": [
    {
      "message": "입술 더 연하게 해줘",
      "proposal": {
        "choice": "adjust_intensity/lip/down",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "cee5d7d4-3496-4223-9b71-434e21b17c48",
        "onAppliedReply": "입술 색을 한결 은은하게 낮췄어요. 느낌이 괜찮은지 봐주세요!",
        "action": "ar_control",
        "commandId": "10c0e351-4513-4048-bf86-39737c871c18",
        "expectedStateVersion": 309
      },
      "status": "NO_CHANGE",
      "answer": "입술 색은 이미 가장 연한 단계라 더 연하게 바뀌지 않았어요.",
      "elapsedMs": 5318,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "23"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#803430",
            "texture": "velvet",
            "intensity": 0
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.55
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": [],
      "result": {
        "choice": "adjust_intensity/lip/down",
        "displayMode": "face",
        "status": "NO_CHANGE",
        "data": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "23",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "빈티지 토프",
            "texture": "velvet"
          },
          "intensity": 0,
          "geometry": null,
          "lipCare": null
        },
        "reason": "already at requested level or limit"
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {
      "lip": {
        "productId": "oy-a000000120880",
        "shadeId": "23"
      },
      "blush": {
        "productId": "oy-a000000171371",
        "shadeId": "a000000171371-044"
      }
    },
    "makeup": {
      "lip": {
        "hex": "#803430",
        "texture": "velvet",
        "intensity": 0.55
      },
      "blush": {
        "hex": "#C88B84",
        "texture": "velvet",
        "intensity": 0.55
      },
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### H01 아까 두 번째로 발라본 립 다시 발라줘

```json
{
  "id": "H01",
  "group": "체험순서",
  "message": "아까 두 번째로 발라본 립 다시 발라줘",
  "expected": "수동→Luna→수동 뒤 두 번째 립 ID·호수 복원",
  "setup": [
    {
      "manual": "04",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8B4651",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        ]
      }
    },
    {
      "say": "페이드 레드 발라줘",
      "status": "APPLIED"
    },
    {
      "manual": "07",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "07"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#AD0E28",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "07"
          }
        ]
      }
    }
  ],
  "turns": [
    {
      "message": "페이드 레드 발라줘",
      "proposal": {
        "choice": "apply_shade/product_shade",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": "oy-a000000120880",
        "shadeId": "24",
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "92602e02-febd-4b23-98aa-615eb70a6642",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "f69e8bc5-7840-4d91-a19e-9923c6426d81",
        "expectedStateVersion": 315
      },
      "status": "APPLIED",
      "answer": "롬앤 제로 벨벳 틴트 페이드 레드의 딥한 레드 컬러를 발라드렸어요.",
      "elapsedMs": 6919,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8C2B28",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "04"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "24"
        }
      ],
      "result": {
        "choice": "apply_shade/product_shade",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "04",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "번트하트",
            "texture": "velvet"
          },
          "color": {
            "family": "berry",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.65,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "24",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "페이드 레드",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "medium"
          },
          "intensity": 0.65,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "롬앤",
          "product": "롬앤 제로 벨벳 틴트",
          "productKo": "롬앤 제로 벨벳 틴트",
          "shade": "페이드 레드",
          "family": "red",
          "lightness": "deep",
          "chroma": "medium"
        }
      }
    },
    {
      "message": "아까 두 번째로 발라본 립 다시 발라줘",
      "proposal": {
        "choice": "reapply_try_on/lip",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": 2,
        "value": null,
        "sessionId": "92602e02-febd-4b23-98aa-615eb70a6642",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "76baa33c-9517-48c9-9913-cb49a623c0e3",
        "expectedStateVersion": 317
      },
      "status": "APPLIED",
      "answer": "아까 두 번째로 발라보신 롬앤 제로 벨벳 틴트 페이드 레드의 딥한 레드 컬러를 다시 발라드렸어요.",
      "elapsedMs": 5889,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8C2B28",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "07"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "04"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "24"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "07"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "24"
        }
      ],
      "result": {
        "choice": "reapply_try_on/lip",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "07",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "피즈",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "vivid"
          },
          "intensity": 0.65,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "24",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "페이드 레드",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "medium"
          },
          "intensity": 0.65,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "롬앤",
          "product": "롬앤 제로 벨벳 틴트",
          "productKo": "롬앤 제로 벨벳 틴트",
          "shade": "페이드 레드",
          "family": "red",
          "lightness": "deep",
          "chroma": "medium"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {},
    "makeup": {
      "lip": null,
      "blush": null,
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### H02 맨 처음 써본 입술 색으로 돌아가자

```json
{
  "id": "H02",
  "group": "체험순서",
  "message": "맨 처음 써본 입술 색으로 돌아가자",
  "expected": "첫 수동 립 복원",
  "setup": [
    {
      "manual": "04",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8B4651",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        ]
      }
    },
    {
      "say": "페이드 레드 발라줘",
      "status": "APPLIED"
    },
    {
      "manual": "07",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "07"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#AD0E28",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "07"
          }
        ]
      }
    }
  ],
  "turns": [
    {
      "message": "페이드 레드 발라줘",
      "proposal": {
        "choice": "apply_shade/product_shade",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": "oy-a000000120880",
        "shadeId": "24",
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "ead4da69-015f-409d-ac66-c34b1c3b15a8",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "7a01280b-6fd6-4ece-aa6d-6c2c712daf82",
        "expectedStateVersion": 324
      },
      "status": "APPLIED",
      "answer": "롬앤 제로 벨벳 틴트 페이드 레드의 딥한 레드 컬러로 발라드렸어요.",
      "elapsedMs": 7455,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8C2B28",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "04"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "24"
        }
      ],
      "result": {
        "choice": "apply_shade/product_shade",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "04",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "번트하트",
            "texture": "velvet"
          },
          "color": {
            "family": "berry",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.65,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "24",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "페이드 레드",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "medium"
          },
          "intensity": 0.65,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "롬앤",
          "product": "롬앤 제로 벨벳 틴트",
          "productKo": "롬앤 제로 벨벳 틴트",
          "shade": "페이드 레드",
          "family": "red",
          "lightness": "deep",
          "chroma": "medium"
        }
      }
    },
    {
      "message": "맨 처음 써본 입술 색으로 돌아가자",
      "proposal": {
        "choice": "reapply_try_on/lip",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": 1,
        "value": null,
        "sessionId": "ead4da69-015f-409d-ac66-c34b1c3b15a8",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "f36a3d8f-f9c9-47fb-8d31-4fc9dc55ec05",
        "expectedStateVersion": 326
      },
      "status": "APPLIED",
      "answer": "처음 써보셨던 롬앤 제로 벨벳 틴트 번트하트의 차분하고 깊은 베리 컬러로 돌아왔어요.",
      "elapsedMs": 6084,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8B4651",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "07"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "04"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "24"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "07"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "04"
        }
      ],
      "result": {
        "choice": "reapply_try_on/lip",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "07",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "피즈",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "vivid"
          },
          "intensity": 0.65,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "04",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "번트하트",
            "texture": "velvet"
          },
          "color": {
            "family": "berry",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.65,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "롬앤",
          "product": "롬앤 제로 벨벳 틴트",
          "productKo": "롬앤 제로 벨벳 틴트",
          "shade": "번트하트",
          "family": "berry",
          "lightness": "deep",
          "chroma": "muted"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {},
    "makeup": {
      "lip": null,
      "blush": null,
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### H03 두 번째 립이 더 좋았어. 그걸로 다시 해줘

```json
{
  "id": "H03",
  "group": "체험순서",
  "message": "두 번째 립이 더 좋았어. 그걸로 다시 해줘",
  "expected": "Luna→수동→수동 뒤 두 번째 수동 립 복원",
  "setup": [
    {
      "say": "번트하트 발라줘",
      "status": "APPLIED"
    },
    {
      "manual": "24",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8C2B28",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        ]
      }
    },
    {
      "manual": "07",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "07"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#AD0E28",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "07"
          }
        ]
      }
    }
  ],
  "turns": [
    {
      "message": "번트하트 발라줘",
      "proposal": {
        "choice": "apply_shade/product_shade",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": "oy-a000000120880",
        "shadeId": "04",
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "cf40078a-b49e-48b9-b3a4-7f54e297613c",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "0e025d55-4e85-4a5e-ba25-4b2a62148800",
        "expectedStateVersion": 332
      },
      "status": "APPLIED",
      "answer": "롬앤 제로 벨벳 틴트 번트하트 발라드렸어요. 차분하고 깊은 베리 컬러예요.",
      "elapsedMs": 7403,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8B4651",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "04"
        }
      ],
      "result": {
        "choice": "apply_shade/product_shade",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": null,
          "intensity": null,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "04",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "번트하트",
            "texture": "velvet"
          },
          "color": {
            "family": "berry",
            "lightness": "deep",
            "chroma": "muted"
          },
          "intensity": 0.65,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "롬앤",
          "product": "롬앤 제로 벨벳 틴트",
          "productKo": "롬앤 제로 벨벳 틴트",
          "shade": "번트하트",
          "family": "berry",
          "lightness": "deep",
          "chroma": "muted"
        }
      }
    },
    {
      "message": "두 번째 립이 더 좋았어. 그걸로 다시 해줘",
      "proposal": {
        "choice": "reapply_try_on/lip",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": 2,
        "value": null,
        "sessionId": "cf40078a-b49e-48b9-b3a4-7f54e297613c",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "ace51ba2-2e5b-432c-8fce-2cb1562e51e4",
        "expectedStateVersion": 335
      },
      "status": "APPLIED",
      "answer": "롬앤 제로 벨벳 틴트 페이드 레드의 깊이감 있는 레드로 다시 발라드렸어요.",
      "elapsedMs": 7658,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8C2B28",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "07"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "04"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "24"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "07"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "24"
        }
      ],
      "result": {
        "choice": "reapply_try_on/lip",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "07",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "피즈",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "vivid"
          },
          "intensity": 0.65,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "24",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "페이드 레드",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "medium"
          },
          "intensity": 0.65,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "롬앤",
          "product": "롬앤 제로 벨벳 틴트",
          "productKo": "롬앤 제로 벨벳 틴트",
          "shade": "페이드 레드",
          "family": "red",
          "lightness": "deep",
          "chroma": "medium"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {},
    "makeup": {
      "lip": null,
      "blush": null,
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### H04 두 번째로 바른 립으로 다시 해줘

```json
{
  "id": "H04",
  "group": "체험순서",
  "message": "두 번째로 바른 립으로 다시 해줘",
  "expected": "블러셔를 제외하고 립의 두 번째 복원",
  "setup": [
    {
      "manual": "04",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8B4651",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        ]
      }
    },
    {
      "manual": "blush",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8B4651",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.45
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "blush",
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        ]
      }
    },
    {
      "manual": "24",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "24"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8C2B28",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.45
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "blush",
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        ]
      }
    },
    {
      "manual": "07",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "07"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#AD0E28",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.45
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "blush",
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "07"
          }
        ]
      }
    }
  ],
  "turns": [
    {
      "message": "두 번째로 바른 립으로 다시 해줘",
      "proposal": {
        "choice": "reapply_try_on/lip",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": 2,
        "value": null,
        "sessionId": "edb92698-ae70-420a-b813-057cb87b31de",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "c706e078-c9a7-448e-9e37-05de501101e1",
        "expectedStateVersion": 345
      },
      "status": "APPLIED",
      "answer": "롬앤 제로 벨벳 틴트 페이드 레드의 딥한 레드 컬러로 두 번째 립을 다시 발랐어요.",
      "elapsedMs": 9945,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "24"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8C2B28",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.45
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "blush",
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "07"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "04"
        },
        {
          "zone": "blush",
          "productId": "oy-a000000171371",
          "shadeId": "a000000171371-044"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "24"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "07"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "24"
        }
      ],
      "result": {
        "choice": "reapply_try_on/lip",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "07",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "피즈",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "vivid"
          },
          "intensity": 0.65,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "24",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "페이드 레드",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "medium"
          },
          "intensity": 0.65,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "롬앤",
          "product": "롬앤 제로 벨벳 틴트",
          "productKo": "롬앤 제로 벨벳 틴트",
          "shade": "페이드 레드",
          "family": "red",
          "lightness": "deep",
          "chroma": "medium"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {},
    "makeup": {
      "lip": null,
      "blush": null,
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### H05 전체에서 두 번째로 발라본 제품 다시 발라줘

```json
{
  "id": "H05",
  "group": "체험순서",
  "message": "전체에서 두 번째로 발라본 제품 다시 발라줘",
  "expected": "전체 순서의 두 번째 블러셔, 이미 착용해 NO_CHANGE",
  "setup": [
    {
      "manual": "04",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8B4651",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        ]
      }
    },
    {
      "manual": "blush",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8B4651",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.45
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "blush",
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        ]
      }
    },
    {
      "manual": "24",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "24"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8C2B28",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.45
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "blush",
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        ]
      }
    }
  ],
  "turns": [
    {
      "message": "전체에서 두 번째로 발라본 제품 다시 발라줘",
      "proposal": {
        "choice": "reapply_try_on/all",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": 2,
        "value": null,
        "sessionId": "4082f5b8-713e-4351-9c6a-6824f1d019c3",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "a89a7b60-587c-4a7b-b968-a1e9d9eea600",
        "expectedStateVersion": 354
      },
      "status": "NO_CHANGE",
      "answer": "네이밍 플러피 파우더 블러쉬의 베이크드 색상은 이미 발라져 있어서 다시 바뀌지 않았어요.",
      "elapsedMs": 6692,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "24"
          },
          "blush": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8C2B28",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": {
            "hex": "#C88B84",
            "texture": "velvet",
            "intensity": 0.45
          },
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "blush",
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "04"
        },
        {
          "zone": "blush",
          "productId": "oy-a000000171371",
          "shadeId": "a000000171371-044"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "24"
        }
      ],
      "result": {
        "choice": "reapply_try_on/all",
        "displayMode": "face",
        "status": "NO_CHANGE",
        "data": {
          "zone": "blush",
          "product": {
            "productId": "oy-a000000171371",
            "shadeId": "a000000171371-044",
            "brand": "네이밍",
            "product": "[1등 블러셔/모공블러] 네이밍 플러피 파우더 블러쉬 20colors",
            "shade": "베이크드",
            "texture": "velvet"
          },
          "color": {
            "family": "nude",
            "lightness": "medium",
            "chroma": "muted"
          },
          "intensity": 0.45,
          "geometry": null
        },
        "featuredShade": {
          "brand": "네이밍",
          "product": "[1등 블러셔/모공블러] 네이밍 플러피 파우더 블러쉬 20colors",
          "productKo": "[1등 블러셔/모공블러] 네이밍 플러피 파우더 블러쉬 20colors",
          "shade": "베이크드",
          "family": "nude",
          "lightness": "medium",
          "chroma": "muted"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {},
    "makeup": {
      "lip": null,
      "blush": null,
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### H06 세 번째로 발랐던 립으로 해줘

```json
{
  "id": "H06",
  "group": "체험순서",
  "message": "세 번째로 발랐던 립으로 해줘",
  "expected": "이미 착용 중인 세 번째 호수 유지",
  "setup": [
    {
      "manual": "04",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8B4651",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        ]
      }
    },
    {
      "manual": "24",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8C2B28",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        ]
      }
    },
    {
      "manual": "07",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "07"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#AD0E28",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "07"
          }
        ]
      }
    }
  ],
  "turns": [
    {
      "message": "세 번째로 발랐던 립으로 해줘",
      "proposal": {
        "choice": "reapply_try_on/lip",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": 3,
        "value": null,
        "sessionId": "e33ed3b5-2582-4307-b3b1-6e2d2574f7bc",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "5a951865-7ae6-40ae-b01d-b2b23486161a",
        "expectedStateVersion": 362
      },
      "status": "NO_CHANGE",
      "answer": "세 번째로 바르셨던 롬앤 제로 벨벳 틴트 ‘피즈’는 짙고 선명한 레드예요. 이미 해당 립으로 설정되어 있어 변경되지 않았어요.",
      "elapsedMs": 8191,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "07"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#AD0E28",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "07"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "04"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "24"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "07"
        }
      ],
      "result": {
        "choice": "reapply_try_on/lip",
        "displayMode": "face",
        "status": "NO_CHANGE",
        "data": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "07",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "피즈",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "vivid"
          },
          "intensity": 0.65,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "롬앤",
          "product": "롬앤 제로 벨벳 틴트",
          "productKo": "롬앤 제로 벨벳 틴트",
          "shade": "피즈",
          "family": "red",
          "lightness": "deep",
          "chroma": "vivid"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {},
    "makeup": {
      "lip": null,
      "blush": null,
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### H07 두 번째 립 다시 보여줘

```json
{
  "id": "H07",
  "group": "체험순서",
  "message": "두 번째 립 다시 보여줘",
  "expected": "같은 호수 반복 선택은 중복 집계하지 않고 24호 복원",
  "setup": [
    {
      "manual": "04",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8B4651",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        ]
      }
    },
    {
      "manual": "04",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8B4651",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        ]
      }
    },
    {
      "manual": "24",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8C2B28",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        ]
      }
    },
    {
      "manual": "07",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "07"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#AD0E28",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "07"
          }
        ]
      }
    }
  ],
  "turns": [
    {
      "message": "두 번째 립 다시 보여줘",
      "proposal": {
        "choice": "reapply_try_on/lip",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": 2,
        "value": null,
        "sessionId": "46c0ea52-da51-4dbf-8213-e89c1beb24ed",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "9f127211-f1a4-49da-bf4d-60cc3c4cf5c5",
        "expectedStateVersion": 371
      },
      "status": "APPLIED",
      "answer": "두 번째 립은 롬앤 제로 벨벳 틴트 페이드 레드로, 차분하고 깊이감 있는 레드 컬러예요.",
      "elapsedMs": 9254,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8C2B28",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "07"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "04"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "24"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "07"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "24"
        }
      ],
      "result": {
        "choice": "reapply_try_on/lip",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "07",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "피즈",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "vivid"
          },
          "intensity": 0.65,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "24",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "페이드 레드",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "medium"
          },
          "intensity": 0.65,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "롬앤",
          "product": "롬앤 제로 벨벳 틴트",
          "productKo": "롬앤 제로 벨벳 틴트",
          "shade": "페이드 레드",
          "family": "red",
          "lightness": "deep",
          "chroma": "medium"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {},
    "makeup": {
      "lip": null,
      "blush": null,
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### H08 두 번째로 발라봤던 입술 색 다시 발라줘

```json
{
  "id": "H08",
  "group": "체험순서",
  "message": "두 번째로 발라봤던 입술 색 다시 발라줘",
  "expected": "강도 조절은 체험 순번에서 제외하고 24호 복원",
  "setup": [
    {
      "manual": "04",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8B4651",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        ]
      }
    },
    {
      "say": "립 좀 연하게 해줘",
      "status": "APPLIED"
    },
    {
      "manual": "24",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8C2B28",
            "texture": "velvet",
            "intensity": 0.325
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        ]
      }
    },
    {
      "manual": "07",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "07"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#AD0E28",
            "texture": "velvet",
            "intensity": 0.325
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "07"
          }
        ]
      }
    }
  ],
  "turns": [
    {
      "message": "립 좀 연하게 해줘",
      "proposal": {
        "choice": "set_intensity/lip/half",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": null,
        "value": null,
        "sessionId": "83fda772-de13-4aa7-ac8d-8f8bc763595b",
        "onAppliedReply": "립 컬러를 지금보다 절반 정도로 부드럽게 낮췄어요. 어떠세요?",
        "action": "ar_control",
        "commandId": "2db3c104-5901-45a8-a6ed-1c66653797a2",
        "expectedStateVersion": 378
      },
      "status": "APPLIED",
      "answer": "립 컬러를 지금보다 절반 정도로 부드럽게 낮췄어요. 어떠세요?",
      "elapsedMs": 7298,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8B4651",
            "texture": "velvet",
            "intensity": 0.325
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "04"
        }
      ]
    },
    {
      "message": "두 번째로 발라봤던 입술 색 다시 발라줘",
      "proposal": {
        "choice": "reapply_try_on/lip",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": 2,
        "value": null,
        "sessionId": "83fda772-de13-4aa7-ac8d-8f8bc763595b",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "b4c56796-737a-41f3-ba9d-42fe32887d7b",
        "expectedStateVersion": 381
      },
      "status": "APPLIED",
      "answer": "롬앤 제로 벨벳 틴트 페이드 레드의 딥한 레드 색상을 다시 발라드렸어요.",
      "elapsedMs": 6749,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8C2B28",
            "texture": "velvet",
            "intensity": 0.325
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "07"
          },
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "24"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "04"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "24"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "07"
        },
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "24"
        }
      ],
      "result": {
        "choice": "reapply_try_on/lip",
        "displayMode": "face",
        "status": "APPLIED",
        "before": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "07",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "피즈",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "vivid"
          },
          "intensity": 0.325,
          "geometry": null,
          "lipCare": null
        },
        "after": {
          "zone": "lip",
          "product": {
            "productId": "oy-a000000120880",
            "shadeId": "24",
            "brand": "롬앤",
            "product": "롬앤 제로 벨벳 틴트",
            "shade": "페이드 레드",
            "texture": "velvet"
          },
          "color": {
            "family": "red",
            "lightness": "deep",
            "chroma": "medium"
          },
          "intensity": 0.325,
          "geometry": null,
          "lipCare": null
        },
        "featuredShade": {
          "brand": "롬앤",
          "product": "롬앤 제로 벨벳 틴트",
          "productKo": "롬앤 제로 벨벳 틴트",
          "shade": "페이드 레드",
          "family": "red",
          "lightness": "deep",
          "chroma": "medium"
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {},
    "makeup": {
      "lip": null,
      "blush": null,
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### H09 아까 다섯 번째 립 다시 발라줘

```json
{
  "id": "H09",
  "group": "체험순서",
  "message": "아까 다섯 번째 립 다시 발라줘",
  "expected": "없는 순번 안내 또는 거절, 착용 유지",
  "setup": [
    {
      "manual": "04",
      "state": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8B4651",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        ]
      }
    }
  ],
  "turns": [
    {
      "message": "아까 다섯 번째 립 다시 발라줘",
      "proposal": {
        "choice": "reapply_try_on/lip",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": 5,
        "value": null,
        "sessionId": "e873768c-79e3-45ff-a5eb-c025393b1f97",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "0a71318d-0d8a-4b92-9e8a-3ea27112bb23",
        "expectedStateVersion": 388
      },
      "status": "REJECTED",
      "answer": "이번 세션에는 다섯 번째 립을 발라본 기록이 없어서 다시 바를 수 없어요.",
      "elapsedMs": 5009,
      "after": {
        "selections": {
          "lip": {
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        },
        "makeup": {
          "lip": {
            "hex": "#8B4651",
            "texture": "velvet",
            "intensity": 0.65
          },
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": [
          {
            "zone": "lip",
            "productId": "oy-a000000120880",
            "shadeId": "04"
          }
        ]
      },
      "history": [
        {
          "zone": "lip",
          "productId": "oy-a000000120880",
          "shadeId": "04"
        }
      ],
      "result": {
        "choice": "reapply_try_on/lip",
        "displayMode": "face",
        "status": "REJECTED",
        "reason": "no try-on at that position in this session",
        "data": {
          "scope": "lip",
          "ordinal": 5,
          "triedCount": 1
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {},
    "makeup": {
      "lip": null,
      "blush": null,
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

### H10 아까 두 번째로 바른 립 다시 발라줘

```json
{
  "id": "H10",
  "group": "체험순서",
  "message": "아까 두 번째로 바른 립 다시 발라줘",
  "expected": "비어 있는 이번 체험 이력 안내, 착용 유지",
  "setup": [],
  "turns": [
    {
      "message": "아까 두 번째로 바른 립 다시 발라줘",
      "proposal": {
        "choice": "reapply_try_on/lip",
        "family": null,
        "lightness": null,
        "chroma": null,
        "lipType": null,
        "lookupDetail": null,
        "name": null,
        "productId": null,
        "shadeId": null,
        "steps": null,
        "ordinal": 2,
        "value": null,
        "sessionId": "bf527b18-bddc-4fa2-a8f9-39f801a0bc89",
        "onAppliedReply": null,
        "action": "ar_control",
        "commandId": "780720ba-ced5-43c8-b9e5-19b835ecee73",
        "expectedStateVersion": 393
      },
      "status": "REJECTED",
      "answer": "이 세션에는 두 번째 립을 발랐던 기록이 없어 다시 바를 수 없어요.",
      "elapsedMs": 4384,
      "after": {
        "selections": {},
        "makeup": {
          "lip": null,
          "blush": null,
          "eyeshadow": null,
          "eyeliner": null,
          "mascara": null,
          "highlighter": null,
          "contour": null,
          "brow": null,
          "foundation": null
        },
        "history": []
      },
      "history": [],
      "result": {
        "choice": "reapply_try_on/lip",
        "displayMode": "face",
        "status": "REJECTED",
        "reason": "no try-on at that position in this session",
        "data": {
          "scope": "lip",
          "ordinal": 2,
          "triedCount": 0
        }
      }
    }
  ],
  "passed": true,
  "start": {
    "selections": {},
    "makeup": {
      "lip": null,
      "blush": null,
      "eyeshadow": null,
      "eyeliner": null,
      "mascara": null,
      "highlighter": null,
      "contour": null,
      "brow": null,
      "foundation": null
    },
    "history": []
  }
}
```

## 재실행

```powershell
$env:AR_CONTROL_TEST_PORT='8080'
$env:AR_EVAL_REPORT='docs/AR_CONTROL_EVALUATION.md'
npm.cmd test -- --runInBand --runTestsByPath __tests__/arIntegration.test.tsx -t AR_EVAL
```

모델 호출에 요금이 발생한다. 문장과 기대값은 __tests__/fixtures/arControlEvaluation.json에 있다. 이번 평가용 문장을 프롬프트에 추가하지 않았다.

## Source fingerprints (SHA-256)

```text
__tests__/fixtures/arControlEvaluation.json  7ba1af46254ac5521568764ae4b8eb39768700882a9a670f13588e3f71d1c34c
backend/chatbot/app/services/ar_control_service.py  b41d28deeaf58ab6f61e32ab6de9c6ebac59fc5b162da946ebf79a0cab381f72
backend/chatbot/app/clients/llm_client.py  c0f44a46863e9c8ffd47bec945307bc8d849e61ca8de211ae16c2f29626969d2
lib/arMakeupControls.ts  f0733062601962578e6906557e6696b2c2ebc9c587a208c047e83247516cd8ee
```
