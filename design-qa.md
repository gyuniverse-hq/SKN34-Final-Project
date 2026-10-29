# 피부 리포트 화면 검증

- Source visual truth: 사용자가 제공한 올리브영 화면 4장.
  - `C:/Users/PLAYDA~1/AppData/Local/Temp/codex-clipboard-a37b4acd-a88a-469b-abdc-e633274a0d35.png`
  - `C:/Users/PLAYDA~1/AppData/Local/Temp/codex-clipboard-98837921-a8b2-4d65-800a-8a5bb05f8642.png`
  - `C:/Users/PLAYDA~1/AppData/Local/Temp/codex-clipboard-c2d58aa7-0648-412a-ae5d-d414c045abcd.png`
  - `C:/Users/PLAYDA~1/AppData/Local/Temp/codex-clipboard-f60fd310-1768-402f-8484-9fc3bd4e57b3.png`
- Reference pixels: 각 원본 1080 × 2093. 채팅 표시본은 1057 × 2048.
- Intended implementation: `http://localhost:8083/skin-recommendations`.
- Intended viewport: 390 × 756 CSS px, deviceScaleFactor 1, 한국어, 저장 결과 없음/명시적 예시 리포트.
- Intended density normalization: 원본을 너비 390px로 축소하여 동일 화면 폭으로 비교.
- Implementation screenshots: 아직 확보되지 않음.

## 검증 상태

현재 소스 캡처와 렌더된 구현을 함께 놓고 비교하지 못했다. 아래 항목을 코드만 보고 통과로 처리하지 않는다.

| 항목 | 상태 |
| --- | --- |
| 글꼴·크기·줄바꿈 | 시각 검증 대기 |
| 간격·배치·가로 넘침 | 시각 검증 대기 |
| VISHUE 색상·토큰·대비 | 토큰 적용, 시각 검증 대기 |
| 생성 히어로 이미지·크롭 | 에셋 직접 확인, 화면 내 크롭 검증 대기 |
| 실제 화면 문구·예시 표시 | 번역 계약 자동 검사 수행, 렌더 검증 대기 |
| 탭·접기·토글·상품 모달·스크롤 | 구현됨, 브라우저 동작 검증 대기 |
| 브라우저 콘솔 오류 | 수집 미완료 |
| Full-view / focused-region comparison | 렌더 캡처가 없어 수행하지 못함 |

## 시도와 차단 사유

1. 기본 Metro 미리보기는 파일 감시 시작에 실패했다.
2. CI 모드로 감시를 끄고 단일 작업자로 로컬 서버를 시작했다.
3. 앱 내 브라우저는 초기화/상태 조회에서 시간 초과했다.
4. 번들된 Playwright로 별도 브라우저를 열었으나 샌드박스에서 localhost 접근이
   `ERR_NETWORK_ACCESS_DENIED`로 거절됐다.
5. 별도 권한으로 실행한 Chrome 캡처도 페이지 진입 120초 제한을 초과했다.
   로컬 서버 상태 요청도 15초 제한을 초과했다. 구현 화면을 확보하지 못했으므로 시각 검증은 미완료다.

## 자동 검사 결과

- 앱 테스트: 19개 suite, 134개 test 통과.
- 새 리포트 규칙·번역 집중 검사: 18개 test 통과.
- 최종 로딩 훅 수정 후 저장소 오류·재시도·명시적 요청 검사: 4개 test 통과.
- 변경 파일 린트 및 최종 리포트 화면·로딩 훅 린트: 통과.
- `npm run check`: 기존 `app/chat.tsx`의 `ScrollViewInstance` 타입 오류로 중단.
  이번 변경 파일에서 타입 오류는 보고되지 않았다.
- 정적 검사와 단위 테스트 통과를 시각 검증 통과로 대체하지 않는다.

## 의도한 차이

- 올리브영 그린 대신 기존 VISHUE 아이보리·버건디·로즈 토큰 사용.
- 큐브·마스코트 대신 생성한 장식용 로즈 유리 방울 사용.
- 사진은 보관하지 않으므로 얼굴 사진·흐림 토글 대신 수치·부위별 결과 토글 제공.
- 저장 결과가 없으면 명시적 예시 배너를 추가한다. 나이·성별·과거 이력은 임의로 만들지 않는다.

## 남은 확인

미리보기에서 요약·솔루션·상세·상품 모달을 캡처하고, 같은 너비로 정규화한 참고 화면과
한 비교 이미지에서 확인한다. 360px·390px 너비의 가로 넘침, 고정 탭, 폰트 확대,
실기기의 분석→설문→저장→리포트 진입도 확인한다.

final result: blocked
