# ADR-0009 팀 공용 개발 서버는 Render(무료) + Supabase + Neo4j AuraDB Free로 둔다

- 상태: 채택 (2026-10-24). [ADR-0008](0008-aws-environments.md)의 "EKS 안 dev 네임스페이스" 부분을 대체합니다. AWS는 운영 배포에만 씁니다.

## 배경

AWS 작업은 배포 단계에서 하기로 했습니다. 하지만 팀원들은 지금부터 실제 백엔드에 붙어서 개발해야 하고, 각자 PC에 Docker를 설치하기는 어렵습니다(관리자 권한, Windows 가상화 설정, 기존 DB와 포트 충돌). EKS를 개발 기간 내내 켜 두는 비용도 아끼고 싶습니다.

## 결정

1. **서버는 Render 무료 플랜**: `vishue-api`, `vishue-chatbot` 두 웹 서비스를 `infra/render/render.yaml`(Blueprint)로 정의합니다. `develop` 브랜치를 Render가 직접 빌드하고, **커밋의 GitHub 검사(`ci-ok`)가 통과한 뒤에만 배포**합니다(`autoDeployTrigger: checksPass`).
2. **DB는 외부 무료 서비스**: PostgreSQL은 Supabase(로그인과 같은 프로젝트), Neo4j는 AuraDB Free를 씁니다. Redis는 쓰지 않습니다. 코드는 Redis가 없으면 캐시 없이 동작하도록 이미 만들어져 있습니다.
3. **마이그레이션은 서버 시작 때**: 무료 플랜에는 배포 전 작업 단계가 없어서, `RUN_MIGRATIONS=true`일 때만 컨테이너가 시작하면서 `alembic upgrade head`를 실행합니다. 여러 인스턴스가 동시에 시작해도 PostgreSQL advisory lock으로 한 번만 적용됩니다. 쿠버네티스(initContainer)와 Compose(migrate 서비스)는 지금처럼 따로 실행합니다.
4. **데이터는 GitHub Actions가 넣습니다** (`dev-data.yml`). 시드 파일이 바뀌면 Supabase에 마이그레이션·시드를 하고, dev api를 거쳐 AuraDB로 복사합니다. 챗봇은 계속 PostgreSQL에 직접 접근하지 않습니다([ADR-0002](0002-postgres-source-neo4j-copy.md)). 같은 워크플로가 12시간마다 돌면서 무료 서비스들이 잠들거나 일시 정지되지 않게 합니다.
5. **ADR-0008에서 만든 EKS dev 구성(values-dev, GitHub OIDC 배포 역할, dev 네임스페이스)은 지웁니다.** 개발 경로를 하나로 유지하기 위해서입니다.

## 결과

- 화면 담당 팀원은 Docker 없이 `.env`에 `vishue-api` 주소만 넣고 개발합니다.
- 비용이 들지 않습니다. 대신 무료 플랜의 제약을 받아들입니다. 15분 동안 요청이 없으면 잠들어서 첫 요청이 느리고, 사용 시간은 월 750시간까지이며, Redis가 없습니다. 불편이 커지면 `vishue-api`만 유료로 올립니다.
- Render는 서버마다 주소가 따로라서 하나의 입구가 없습니다. 앱에 챗봇 화면을 붙일 때 챗봇 주소를 따로 쓰거나 입구 서버를 추가합니다. 운영(EKS)에는 Gateway가 있어서 이 문제가 없습니다.
- dev와 운영의 실행 환경이 다릅니다(Render와 EKS). 같은 Dockerfile과 같은 마이그레이션을 쓰는 것으로 차이를 줄이고, 쿠버네티스 동작은 kind와 운영 배포 전 점검에서 확인합니다.
