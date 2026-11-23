# Restore a PostgreSQL dump from the ops S3 bucket into RDS (one-shot Job).
# Supports pg_dump custom format (PGDMP / .dump). The Job runs pg_restore --clean.
#
# Cutover:
#   # Scale writers down first so connections do not block DROP.
#   kubectl -n vishue scale deploy/vishue-api deploy/vishue-chatbot --replicas=0
#   aws s3 cp .\vishue-integrated.dump "s3://<ops_bucket>/dumps/"
#   kubectl apply -f infra/platform/restore-serviceaccount.yaml
#   pwsh -File infra/scripts/restore-rds-dump.ps1 -Bucket <ops_bucket> -Key dumps/vishue-integrated.dump -Yes
#   # After Job succeeds: set seedOnDeploy=false, scale api/chatbot back up, verify.
#
# Then: confirm alembic_version matches the api image; avoid re-seeding over the dump.

param(
  [Parameter(Mandatory = $true)]
  [string]$Bucket,
  [Parameter(Mandatory = $true)]
  [string]$Key,
  [string]$Namespace = "vishue",
  [string]$SecretName = "vishue-api",
  [string]$ServiceAccount = "vishue-restore",
  [switch]$Yes
)

$ErrorActionPreference = "Stop"
$jobName = "vishue-rds-restore-$(Get-Date -Format 'yyyyMMddHHmmss')"
$tplPath = Join-Path $PSScriptRoot "..\platform\restore-job.yaml.tpl"
$tpl = Get-Content -Raw -Path $tplPath

$manifest = $tpl.
  Replace("{{JOB_NAME}}", $jobName).
  Replace("{{NAMESPACE}}", $Namespace).
  Replace("{{SERVICE_ACCOUNT}}", $ServiceAccount).
  Replace("{{SECRET_NAME}}", $SecretName).
  Replace("{{BUCKET}}", $Bucket).
  Replace("{{KEY}}", $Key)

Write-Host $manifest

if (-not $Yes) {
  Write-Host "Dry run only. Re-run with -Yes to create the Job."
  exit 0
}

if (-not (kubectl -n $Namespace get sa $ServiceAccount -o name 2>$null)) {
  throw "ServiceAccount $Namespace/$ServiceAccount missing. kubectl apply -f infra/platform/restore-serviceaccount.yaml"
}

$tmp = Join-Path $env:TEMP "$jobName.yaml"
Set-Content -Path $tmp -Value $manifest -Encoding utf8
kubectl apply -f $tmp
Write-Host "Job $jobName created. Logs: kubectl -n $Namespace logs job/$jobName -c restore -f"
