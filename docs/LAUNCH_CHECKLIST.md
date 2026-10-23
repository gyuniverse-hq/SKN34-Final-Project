# 출시 체크리스트 — 직접 해야 하는 일

코드로 할 수 있는 부분은 구현되어 있습니다. 아래는 계정, 결제, 법률 판단, 실기기 확인처럼 **사람이 직접 해야 하는 일**만 모았습니다.

## 1. 지금 바로 (보안)

- [ ] **노출된 Expo 액세스 토큰 2개 폐기** — expo.dev → Account settings → Access tokens → Revoke
- [ ] **YouTube API 키 제한 설정** — Google Cloud Console → 사용자 인증 정보 → 해당 키 → API 제한: *YouTube Data API v3*만 허용
  - 키가 대화 기록에 노출됐으니 재발급 후 `.env`의 `YOUTUBE_API_KEY`를 교체하는 것을 권장
- [ ] `.env`를 절대 커밋하지 않기 (이미 `.gitignore` 처리됨)

## 2. API 키 발급

- [x] **네이버 검색 API** 키 입력 완료 — 제품 사진이 네이버 쇼핑의 실제 상품 이미지로 표시됨
- [ ] **네이버 쇼핑 검색(`shop.json`) 사용 가능 여부 확인** — 현재 이 애플리케이션 키로는 쇼핑 검색만 `SE05`(존재하지 않는 검색 API)가 반환됩니다(블로그·이미지 검색은 정상). 개발자 센터 → 내 애플리케이션 → API 설정에서 "검색"이 켜져 있는지 확인하고, 그래도 안 되면 개발자 포럼에 문의
  - 풀리면 코드 수정 없이 상품 상세에 "온라인 구매"(판매처·최저가·링크)가 자동으로 나타납니다. 지금은 해당 영역만 숨겨집니다
- [ ] (운영) YouTube API 할당량: 기본 하루 10,000 유닛, 검색 1회 = 100 유닛. 서버 캐시(12시간)로 줄였지만 사용자가 많아지면 Google에 할당량 증가 신청 필요

## 3. 데이터 확인 (`backend/api/seed/catalog.json`, 이후 크롤링 데이터)

- [ ] **제품 가격·컬러명·HEX 색상 검수** — 실제 제품 라인이지만 값은 참고치입니다. 공식몰 기준으로 확인
- [ ] **제품 이미지 라이선스** — 지금은 Unsplash 임시 사진(다른 브랜드가 찍힌 사진 포함). 네이버 연동 이미지나 브랜드 공식 보도자료 이미지로 교체
- [ ] **룩 썸네일 교체** — 저작권이 확보된 이미지로 교체
- [ ] **매장 주소·좌표·영업시간 검수** (시드 파일의 `stores`)
- [ ] 룩 ↔ 제품 매핑 최종 확정, 제품 수 확대 (MVP 권장 30~50개)

## 4. 법률·정책 판단

- [ ] **셀럽 이름 사용 범위 결정** — 앱 화면에는 셀럽 이름 대신 "Inspired by K-pop ..." 문구만 쓰고, 이름은 YouTube 검색어에만 넣었습니다. 퍼블리시티권 이슈는 법률 검토 권장
- [ ] **"Olive Young" 매장명 표기** — 제휴 없이 상호를 쓰는 것이 괜찮은지 확인. 아니면 "매장 찾기" 형태로 일반화
- [ ] **개인정보처리방침·이용약관 확정** (`constants/legal.ts`의 `[대괄호]` 채우기: 회사명, 연락처, 로그 보관 기간 등)
  - 한국어 버전 작성 (국내 개인정보보호법 대응)
  - **공개 URL로 호스팅** (노션 공개 페이지 등) — 앱스토어·플레이스토어 등록 시 필수
- [ ] 실결제를 붙일지 결정 — 붙인다면 PG(토스페이먼츠, 포트원 등) 계약, 사업자등록, 통신판매업 신고 필요. 붙이지 않으면 현재 구조(쇼핑 리스트 + 외부 링크)로 출시 가능

## 5. 실기기 확인 (제가 할 수 없는 부분)

- [ ] **AR 품질 확인** — iPhone과 Android 실기기에서 입술·볼·눈두덩 위치, 발색, 끊김 확인. 웹 테스트에서 실제 인물 사진으로 위치는 검증했지만 조명·카메라별 튜닝은 실기기에서만 가능
  - 발색 조절 위치: `components/ar/faceTrackerHtml.ts`의 `drawLips` / `drawBlush` / `drawEyeshadow`
- [ ] 저사양 Android 기기에서 AR 프레임 확인
- [ ] 4개 언어 화면에서 텍스트 잘림 확인

## 6. 브랜딩

- [x] **앱 이름 확정** (`app.json`의 `name`: "VISHUE")
- [ ] **번들 ID 확정** — 현재 `com.kbeautyar.app`. **스토어에 한 번 올리면 변경 불가**
- [x] 앱 아이콘(1024×1024), Android 적응형 아이콘, 파비콘 교체 (`assets/images/`)
- [x] 스플래시 이미지 교체 (`assets/images/splash-icon.png`)
- [ ] 스토어 스크린샷, 설명문 (영어 + 대상 국가 언어)

## 7. 계정·배포

- [ ] **Apple Developer Program** 가입 (연 $99) — iOS 출시와 실기기 빌드에 필요
- [ ] **Google Play Console** 가입 (1회 $25)
- [ ] EAS 프로젝트 연결: `npx eas-cli@latest init`
- [ ] **백엔드 배포** — [`DEPLOYMENT.md`](DEPLOYMENT.md)의 "AWS EKS" 절. 네이버·YouTube 키는 앱이 아니라 백엔드 시크릿(`vishue/production/api`)에 넣습니다
  - 배포 후 `https://api.<도메인>/api/health`가 `{"ok":true,"integrations":{"youtube":true,...}}`인지 확인
- [ ] **앱에 백엔드 주소 등록** (공개 값이라 `plaintext`):
  ```bash
  npx eas-cli@latest env:create --name EXPO_PUBLIC_API_BASE_URL --value https://api.<도메인> --environment production --visibility plaintext
  ```
  (`preview` 환경에도 동일하게. 주소를 바꾸면 앱을 다시 빌드해야 반영됩니다)
- [ ] 테스트 빌드: `npx eas-cli@latest build --profile preview --platform android` → APK 설치해 확인
- [ ] 출시 빌드·제출: `npx eas-cli@latest build --profile production --platform all` → `npx eas-cli@latest submit`
- [ ] App Store Connect **개인정보 라벨**: 계정 없음, 수집 데이터 없음(카메라는 기기 내 처리), 검색어는 서버로 전달되지만 사용자와 연결되지 않음
- [ ] Google Play **데이터 보안 섹션**: 위와 동일하게 작성. 앱 권한은 카메라만 요청 (마이크·저장소 권한은 차단해 둠)

## 참고: 구현된 운영 품질 항목

- API 키는 백엔드 전용, 앱 번들에 미포함
- 백엔드 캐시(Redis: YouTube 12시간, 네이버 판매처 6시간·이미지 24시간), 튜토리얼 검색 레이트리밋(IP당 분당 20회), 외부 API 타임아웃, 입력값 검증
- 네트워크 오류·로딩·빈 화면 처리, 재시도
- 장바구니·쇼핑 리스트·설정은 기기에 저장, 마이 탭에서 전체 삭제 가능
- 카메라: 동의 화면, 권한 거부 시 설정으로 이동, 탭 이탈·앱 백그라운드 시 카메라 해제
- iOS 개인정보 매니페스트, 암호화 수출 규정 선언, 권한 문구 4개 언어
- 접근성 라벨, 햅틱 피드백
- 테스트 21개 (`npm test`), 타입체크·린트 통과
