# Shrink the production stack between demos (keeps VPC, ECR/GHCR images, Secrets, S3).
# Does NOT delete the cluster. Resume with resume-prod.ps1.
#
# Usage:
#   pwsh -File infra/scripts/pause-prod.ps1 [-StopRds] [-ScaleNodes] [-Yes]
#
# Default: scale api/chatbot/sync workloads to 0 in namespace vishue.
# -StopRds     also stops the RDS instance (storage still billed).
# -ScaleNodes  sets the EKS managed node group desired/min to 0 (control plane still billed).

param(
  [switch]$StopRds,
  [switch]$ScaleNodes,
  [switch]$Yes,
  [string]$Namespace = "vishue",
  [string]$ClusterName = "vishue",
  [string]$Region = "ap-northeast-2",
  [string]$DbIdentifier = "vishue-postgres"
)

$ErrorActionPreference = "Stop"

if (-not $Yes) {
  Write-Host "Dry view only. Re-run with -Yes to apply."
}

Write-Host "==> workloads in $Namespace"
kubectl -n $Namespace get deploy,cronjob 2>$null

if ($Yes) {
  foreach ($dep in @("vishue-api", "vishue-chatbot")) {
    if (kubectl -n $Namespace get deploy $dep -o name 2>$null) {
      kubectl -n $Namespace scale deploy/$dep --replicas=0
    }
  }
  # Suspend graph sync so it does not wake nodes for nothing.
  if (kubectl -n $Namespace get cronjob vishue-sync-graph -o name 2>$null) {
    $patchFile = Join-Path $env:TEMP "vishue-suspend-cronjob.json"
    Set-Content -Path $patchFile -Value '{"spec":{"suspend":true}}' -Encoding ascii
    kubectl -n $Namespace patch cronjob vishue-sync-graph --type merge --patch-file $patchFile
  }
}

if ($ScaleNodes) {
  $ng = aws eks list-nodegroups --cluster-name $ClusterName --region $Region --query "nodegroups[0]" --output text
  Write-Host "==> nodegroup $ng -> 0"
  if ($Yes -and $ng -and $ng -ne "None") {
    aws eks update-nodegroup-config `
      --cluster-name $ClusterName `
      --nodegroup-name $ng `
      --region $Region `
      --scaling-config minSize=0,maxSize=4,desiredSize=0 | Out-Null
  }
}

if ($StopRds) {
  Write-Host "==> stop RDS $DbIdentifier"
  if ($Yes) {
    aws rds stop-db-instance --db-instance-identifier $DbIdentifier --region $Region | Out-Null
  }
}

Write-Host "Pause plan complete. Control plane / NAT / stopped-RDS storage may still incur cost."
