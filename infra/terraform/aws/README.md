# AWS 운영 인프라 (Terraform)

VPC, EKS, RDS, ElastiCache, Secrets Manager, S3를 한 번에 정의합니다. 절차 본문은 [`docs/DEPLOYMENT.md`](../../../docs/DEPLOYMENT.md)와 [ADR-0011](../../../docs/adr/0011-production-cutover.md)입니다.

## 전제

- AWS CLI 프로필(캠프 계정), Terraform ≥ 1.10, kubectl, Helm
- 리전 기본값 `ap-northeast-2`, 접두사 `vishue`

```powershell
cd infra/terraform/aws
terraform init
terraform plan
terraform apply
terraform output
```

팀이 같은 state를 쓰려면 `versions.tf`의 S3 backend 주석을 해제하고 버킷을 만든 뒤 `terraform init -migrate-state`를 실행합니다.

## 출력

| output | 용도 |
| --- | --- |
| `configure_kubectl` | `aws eks update-kubeconfig …` 한 줄 |
| `postgres_endpoint` | RDS 호스트 (URL은 Secrets Manager) |
| `redis_endpoint` | ElastiCache primary |
| `ops_bucket` | 덤프·백업 S3 |
| `secret_names` | 채울 Secrets Manager 이름 |

## 주변 스크립트

| 경로 | 역할 |
| --- | --- |
| [`../scripts/bootstrap-platform.ps1`](../scripts/bootstrap-platform.ps1) | Gateway · ESO · Argo CD · 메트릭 설치 |
| [`../scripts/pause-prod.ps1`](../scripts/pause-prod.ps1) | 시연 외 축소 |
| [`../scripts/resume-prod.ps1`](../scripts/resume-prod.ps1) | 재개 |
| [`../scripts/restore-rds-dump.ps1`](../scripts/restore-rds-dump.ps1) | 덤프 → RDS 복원 Job |
| [`../scripts/verify-prod.ps1`](../scripts/verify-prod.ps1) | 배포 후 경로 확인 |
