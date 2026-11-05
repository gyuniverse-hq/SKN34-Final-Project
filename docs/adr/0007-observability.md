# ADR-0007 JSON 로그 + 요청 ID + 프로브 분리, LLM 추적은 Langfuse로 한다

- 상태: 채택 (2026-10-23). Langfuse 연동은 3단계에서 합니다.

## 배경

요청 하나가 Gateway, `api`, `chatbot`, LLM을 거칩니다. 장애가 났을 때 어디서 막혔는지 찾을 수 있어야 하고, 챗봇의 답변 품질과 비용도 측정해야 합니다.

## 결정

- **로그**: 모든 서비스가 한 줄에 JSON 하나를 남깁니다(`ts`, `level`, `service`, `request_id`, `method`, `path`, `status`, `duration_ms`). 클러스터 로그 수집기(CloudWatch, Loki 등)가 바로 인덱싱할 수 있는 형태입니다.
- **요청 ID**: Gateway가 `X-Request-ID`를 만들거나 그대로 넘기고, 각 서비스가 응답과 로그에 남깁니다.
- **프로브 분리**: `/healthz`는 프로세스 생존만, `/readyz`는 의존성(DB, Redis, Neo4j)까지 확인합니다. DB 장애가 Pod 재시작 폭주로 번지지 않게 하기 위해서입니다.
- **LLM 관측 (3단계)**: Langfuse Cloud에 챗봇의 trace(프롬프트 버전, 검색된 제품, 토큰, 지연, 비용)를 보냅니다. 골든 질문 세트로 오프라인 평가를 돌리고, 점수가 기준보다 떨어지면 CI에서 막습니다. Langfuse를 직접 운영하면 PostgreSQL, ClickHouse, Redis, MinIO가 추가로 필요해서 클라우드 플랜을 씁니다.
- **개인정보**: 챗봇은 질문 내용을 애플리케이션 로그에 남기지 않습니다. Langfuse trace에는 사용자 식별 정보를 넣지 않습니다(사용자 ID는 해시로).

## 결과

- 요청 ID 하나로 여러 서비스의 로그를 이어서 볼 수 있습니다.
- 메트릭(Prometheus)과 분산 추적(OpenTelemetry)은 아직 없습니다. 트래픽이 늘면 추가합니다.
