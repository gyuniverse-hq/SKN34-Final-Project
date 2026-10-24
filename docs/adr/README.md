# 아키텍처 결정 기록 (ADR)

되돌리기 어렵거나 팀 전체에 영향을 주는 결정을 남깁니다. 결정을 바꿀 때는 기존 문서를 고치지 말고, 새 ADR을 쓰고 이전 ADR의 상태를 "대체됨"으로 바꿉니다.

| 번호 | 결정 | 상태 |
| --- | --- | --- |
| [0001](0001-two-backend-services.md) | 백엔드를 `api`와 `chatbot` 두 서비스로 나눈다 | 채택 |
| [0002](0002-postgres-source-neo4j-copy.md) | PostgreSQL이 원본이고, Neo4j는 `api` HTTP를 통해 한 방향으로 복사한다 | 채택 |
| [0003](0003-containers-helm-gitops.md) | 컨테이너 + Helm + Argo CD, 환경은 Compose → kind → EKS 순서로 올린다 | 채택 |
| [0004](0004-gateway-api.md) | 단일 진입점은 Gateway API(Envoy Gateway)로 둔다 | 채택 |
| [0005](0005-supabase-auth-jwks.md) | 인증은 Supabase Auth를 유지하고, 백엔드는 JWKS로 토큰을 검증한다 | 채택 |
| [0006](0006-secrets-per-service.md) | 시크릿은 서비스별로 나누고, 운영에서는 External Secrets로 주입한다 | 채택 |
| [0007](0007-observability.md) | JSON 로그 + 요청 ID + 프로브 분리, LLM 추적은 Langfuse로 한다 | 채택 (Langfuse는 3단계) |
| [0008](0008-aws-environments.md) | AWS EKS에 운영(RDS)을 두고, 인프라는 Terraform으로 관리한다 | 운영 부분 채택, dev 부분은 0009로 대체 |
| [0009](0009-render-dev-environment.md) | 팀 공용 개발 서버는 Render(무료) + Supabase + AuraDB Free로 둔다 | 채택 |

형식: 배경(왜 결정이 필요했나) → 결정 → 결과(얻는 것, 감수하는 것).
