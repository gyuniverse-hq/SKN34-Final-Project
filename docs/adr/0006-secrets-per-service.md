# ADR-0006 시크릿은 서비스별로 나누고, 운영에서는 External Secrets로 주입한다

- 상태: 채택 (2026-10-23)

## 배경

앱 저장소의 규칙은 "API 키는 그 API를 부르는 `clients/`에서만 읽는다"입니다. 쿠버네티스에서 시크릿 하나를 모든 Pod에 주입하면, 이 규칙이 Pod 수준에서는 깨집니다.

## 결정

- 시크릿은 서비스마다 따로 둡니다.
  - `vishue-api`: `DATABASE_URL`, `REDIS_URL`, `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `YOUTUBE_API_KEY`
  - `vishue-chatbot`: `NEO4J_PASSWORD`, `REDIS_URL`, `LLM_API_KEY`
- 비밀이 아닌 설정(모델 이름, 로그 레벨, Supabase 공개 값)은 ConfigMap에 둡니다. ConfigMap이 바뀌면 checksum 어노테이션 때문에 Pod가 다시 뜹니다.
- 운영 시크릿의 원본은 AWS Secrets Manager(`vishue/production/api`, `vishue/production/chatbot`)이고, External Secrets Operator가 쿠버네티스 Secret으로 동기화합니다. Git에는 시크릿 값을 커밋하지 않습니다.
- 로컬(kind)에서만 `secrets.create: true`로 values의 일회용 값을 Secret으로 만듭니다. 둘을 동시에 켜면 차트 렌더링이 실패합니다.
- Pod는 서비스 어카운트 토큰을 마운트하지 않고(`automountServiceAccountToken: false`), 비루트, 읽기 전용 루트 파일시스템, 모든 capability 제거로 실행합니다.

## 결과

- `api` Pod가 탈취되더라도 LLM 키는 노출되지 않습니다.
- 키를 교체할 때는 Secrets Manager 값만 바꾸면 됩니다(기본 1시간 안에 반영되고, 새 Pod부터 적용).
