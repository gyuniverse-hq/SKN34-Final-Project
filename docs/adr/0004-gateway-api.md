# ADR-0004 단일 진입점은 Gateway API(Envoy Gateway)로 둔다

- 상태: 채택 (2026-10-23)

## 배경

앱은 주소 하나만 알아야 하고, 경로에 따라 `api`와 `chatbot`으로 나눠 보내야 합니다. 오랫동안 많이 쓰인 ingress-nginx는 2026년 3월에 유지보수가 종료됐습니다. 쿠버네티스 표준은 Gateway API로 옮겨 가고 있습니다.

## 결정

- Helm 차트가 `Gateway`와 `HTTPRoute`를 만듭니다. 라우팅 규칙은 `/api/chat` → `chatbot`, 나머지 `/api` → `api`입니다(가장 긴 prefix가 우선).
- 구현체는 로컬(kind)과 운영(EKS) 모두 Envoy Gateway(`gatewayClassName: eg`)를 씁니다. 같은 구현체를 쓰면 로컬에서 본 동작이 운영에서도 같습니다.
- TLS를 켜면 HTTP는 HTTPS로 301 리다이렉트합니다.
- Docker Compose에서는 nginx가 같은 라우팅 규칙을 흉내 냅니다(`infra/compose/nginx.conf`).
- NetworkPolicy는 Gateway 네임스페이스(`envoy-gateway-system`)에서 오는 트래픽만 `api`와 `chatbot`으로 들여보냅니다.

## 결과

- 진입점 뒤의 서비스 구성이 바뀌어도 앱은 영향을 받지 않습니다.
- Envoy Gateway와 Gateway API CRD를 클러스터에 먼저 설치해야 합니다([DEPLOYMENT.md](../DEPLOYMENT.md)).
- AWS ALB를 직접 쓰고 싶으면 `gateway.className`만 AWS Load Balancer Controller의 클래스로 바꾸면 됩니다.
