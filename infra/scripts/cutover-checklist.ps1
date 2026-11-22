# Prints the production cutover checklist (ADR-0011). No AWS changes.
Write-Host @"
VISHUE 운영 컷오버 체크리스트
==============================

[0] 도구
    aws --version && terraform version && helm version && kubectl version --client

[1] AWS 자격
    aws configure   # 또는 aws login / 캠프 프로필
    aws sts get-caller-identity

[2] Terraform
    cd infra/terraform/aws
    terraform init
    terraform plan
    terraform apply
    terraform output

[3] kubeconfig + 플랫폼
    aws eks update-kubeconfig --name vishue --region ap-northeast-2
    pwsh -File infra/scripts/bootstrap-platform.ps1

[4] Secrets Manager 키 채우기 (콘솔)
    vishue/production/api      — NAVER_*, YOUTUBE_API_KEY, SUPABASE_SECRET_KEY
    vishue/production/chatbot  — NEO4J_PASSWORD, LLM_API_KEY
    (DATABASE_URL / REDIS_URL 은 Terraform이 채움)

[5] values-prod.yaml PR
    supabase.url / publishableKey, chatbot NEO4J_URI / LLM_MODEL, gateway.hostname

[6] 첫 이미지·Argo 동기화
    main 병합 → images.yml → 태그 PR 병합
    또는 임시로 helm upgrade (비상). ExternalSecret 이 vishue-api Secret 을 만든 뒤 복원.

[7] 덤프 복원
    aws s3 cp .\vishue.dump.sql.gz s3://<ops_bucket>/dumps/
    pwsh -File infra/scripts/restore-rds-dump.ps1 -Bucket <ops_bucket> -Key dumps/... -Yes
    (api 기동 → Alembic → 필요 시 seedOnDeploy 1회 → sync-graph)

[8] 검증
    pwsh -File infra/scripts/verify-prod.ps1 -GatewayUrl <URL>
    앱 EXPO_PUBLIC_API_BASE_URL 을 Gateway 로 변경

[9] 시연 외
    pwsh -File infra/scripts/pause-prod.ps1 -ScaleNodes -StopRds -Yes
"@
