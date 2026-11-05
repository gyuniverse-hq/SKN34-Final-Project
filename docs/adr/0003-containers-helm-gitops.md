# ADR-0003 컨테이너 + Helm + Argo CD, 환경은 Compose → kind → EKS 순서로 올린다

- 상태: 채택 (2026-10-23)

## 배경

로컬에서 되던 것이 서버에서 안 되는 문제를 줄이고, 누가 언제 무엇을 배포했는지 추적할 수 있어야 합니다. 동시에 팀원 모두가 쿠버네티스를 알 필요는 없어야 합니다.

## 결정

- **같은 이미지, 세 환경**
  - Docker Compose (`infra/compose`): 일상 개발. `docker compose up` 한 번으로 전체가 뜹니다.
  - kind (`infra/kind`, `values-local.yaml`): 운영과 같은 Helm 차트를 노드 2대(zone 2개)에서 검증합니다.
  - AWS EKS (`values-prod.yaml`): 운영 환경입니다.
- **이미지 태그는 불변**: `sha-<커밋 7자리>`를 씁니다. `latest`는 쓰지 않습니다. 이미지에는 SBOM과 provenance를 붙입니다.
- **GitOps**: main에 병합되면 이미지를 발행하고, `values-prod.yaml`의 태그를 바꾸는 PR을 자동으로 엽니다. 그 PR을 병합하는 것이 배포이고, revert가 롤백입니다. 클러스터에 직접 `kubectl apply`하지 않습니다.
- **CI 게이트**: PR마다 변경된 영역(앱, 백엔드, Docker, 인프라)만 검사하고, 그 결과를 `ci-ok` 하나로 모읍니다. 브랜치 보호에는 `ci-ok`만 필수로 겁니다.

## 결과

- 배포 이력은 Git 이력과 같습니다. 운영 상태를 Git에서 확인할 수 있습니다.
- 환경 차이는 values 파일에만 있습니다. 그 외 차이는 버그로 봅니다.
- EKS는 고정비가 큽니다(컨트롤 플레인과 NAT 비용). 캠프에서 AWS를 지원하지 않으면, 같은 이미지를 Render나 Cloud Run 같은 관리형 컨테이너 서비스에 올리고 Helm 차트는 kind 시연용으로 씁니다. 애플리케이션 코드는 바뀌지 않습니다.
- (2026-10-24) 캠프의 AWS 지원이 확정되어 EKS로 갑니다. dev 환경과 Terraform 결정은 [ADR-0008](0008-aws-environments.md)에 있습니다.
