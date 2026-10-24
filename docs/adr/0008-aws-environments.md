# ADR-0008 AWS 위에 dev와 운영을 두고, 인프라는 Terraform으로 관리한다

- 상태: 채택 (2026-10-24). [ADR-0003](0003-containers-helm-gitops.md)의 "AWS 지원이 없으면 Render" 대안은 쓰지 않습니다.

## 배경

캠프에서 AWS를 지원하기로 했습니다. 동시에 팀원 PC에 Docker를 설치하기 어렵다는 문제가 확인됐습니다. 관리자 권한과 Windows 가상화 설정이 필요하고, PC에 이미 설치된 DB와 포트가 겹쳤습니다. 화면을 만드는 팀원도 실제 백엔드에 붙어서 개발할 수 있어야 합니다.

## 결정

1. **인프라는 코드로 관리합니다** (`infra/terraform/aws`). VPC(2개 AZ, NAT 1개), EKS, RDS, ElastiCache, Secrets Manager, IAM이 대상이고, 콘솔에서 손으로 만들지 않습니다. CI가 `terraform fmt`와 `validate`를 검사합니다.
2. **EKS 클러스터 하나에 두 환경**을 둡니다.
   - `vishue-dev` (dev): 팀 공용 개발 서버. PostgreSQL은 **Supabase**를 씁니다(팀이 대시보드로 데이터를 보기 쉽고 무료). Redis와 Neo4j는 네임스페이스 안 컨테이너입니다.
   - `vishue` (운영): RDS PostgreSQL, ElastiCache(TLS), Neo4j AuraDB.
3. **배포 방식을 환경마다 다르게** 합니다.
   - dev: `develop`에 병합되면 GitHub Actions가 OIDC로 짧게 쓰는 자격 증명을 받아 `helm upgrade`합니다(push 방식). 병합할 때마다 PR을 하나 더 만들지 않아도 되고, 배포 결과가 워크플로 성공·실패로 바로 보입니다. 배포 역할은 `vishue-dev` 네임스페이스 안에서만 권한이 있습니다.
   - 운영: 지금처럼 태그 갱신 PR → Argo CD(GitOps). 운영 변경은 Git 이력으로만 남깁니다.
4. **dev 카탈로그의 원본은 Git**(`backend/api/seed/catalog.json`)입니다. 배포할 때마다 시드 작업이 DB를 교체하고 캐시를 비운 뒤 그래프를 다시 동기화합니다. 데이터 담당자는 DB 비밀번호 없이 PR로 데이터를 바꾸고, CI가 무결성을 검사합니다([`DATA.md`](../DATA.md)).
5. 차트는 데이터 저장소를 저장소별로 켜고 끕니다. 켜진 저장소의 접속 정보는 차트가 직접 연결해서, values에 릴리스 이름이 들어간 주소를 손으로 쓰지 않습니다.

## 결과

- 화면 담당 팀원은 Docker 없이 `.env`에 dev 주소만 넣고 개발합니다.
- dev와 운영이 같은 차트, 같은 이미지, 같은 마이그레이션을 씁니다. dev에서 먼저 확인한 것만 운영으로 갑니다.
- 고정비가 생깁니다(대략 월 $250: EKS, 노드 2대, NAT, RDS, ElastiCache, NLB 2개). 캠프 크레딧 안에서 쓰고, 프로젝트가 끝나면 `terraform destroy`로 정리합니다.
- dev의 Supabase와 운영의 RDS는 서로 다른 DB라서, 운영 데이터 반영은 별도 절차가 필요합니다. 운영 시드는 자동으로 돌지 않습니다.
- Supabase를 운영 DB로 쓰지 않는 이유: 서버와 같은 VPC에 있는 RDS가 지연·보안·장애 대응에서 유리합니다. 바꿀 때는 `DATABASE_URL`만 바꾸면 되므로 결정을 되돌리기도 쉽습니다.
