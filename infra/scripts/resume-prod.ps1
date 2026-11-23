# Bring production back after pause-prod.ps1.
#
# Usage:
#   pwsh -File infra/scripts/resume-prod.ps1 [-StartRds] [-ScaleNodes] [-Yes]
#   pwsh -File infra/scripts/resume-prod.ps1 -StartRds -ScaleNodes -Yes -GatewayUrl https://api.example.com

param(
  [switch]$StartRds,
  [switch]$ScaleNodes,
  [switch]$Yes,
  [string]$Namespace = "vishue",
  [string]$ClusterName = "vishue",
  [string]$Region = "ap-northeast-2",
  [string]$DbIdentifier = "vishue-postgres",
  [int]$ApiReplicas = 2,
  [int]$ChatbotReplicas = 2,
  [int]$NodeDesired = 2,
  [string]$GatewayUrl = ""
)

$ErrorActionPreference = "Stop"

if ($StartRds) {
  Write-Host "==> start RDS $DbIdentifier"
  if ($Yes) {
    aws rds start-db-instance --db-instance-identifier $DbIdentifier --region $Region | Out-Null
    Write-Host "Waiting for RDS available..."
    aws rds wait db-instance-available --db-instance-identifier $DbIdentifier --region $Region
  }
}

if ($ScaleNodes) {
  $ng = aws eks list-nodegroups --cluster-name $ClusterName --region $Region --query "nodegroups[0]" --output text
  Write-Host "==> nodegroup $ng -> desired $NodeDesired"
  if ($Yes -and $ng -and $ng -ne "None") {
    aws eks update-nodegroup-config `
      --cluster-name $ClusterName `
      --nodegroup-name $ng `
      --region $Region `
      --scaling-config "minSize=2,maxSize=4,desiredSize=$NodeDesired" | Out-Null
    Write-Host "Waiting for nodes Ready (manual check: kubectl get nodes)"
  }
}

if ($Yes) {
  if (kubectl -n $Namespace get cronjob vishue-sync-graph -o name 2>$null) {
    kubectl -n $Namespace patch cronjob vishue-sync-graph --type merge -p '{"spec":{"suspend":false}}'
  }
  if (kubectl -n $Namespace get deploy vishue-api -o name 2>$null) {
    kubectl -n $Namespace scale deploy/vishue-api --replicas=$ApiReplicas
  }
  if (kubectl -n $Namespace get deploy vishue-chatbot -o name 2>$null) {
    kubectl -n $Namespace scale deploy/vishue-chatbot --replicas=$ChatbotReplicas
  }
  kubectl -n $Namespace rollout status deploy/vishue-api --timeout=5m
  kubectl -n $Namespace rollout status deploy/vishue-chatbot --timeout=5m
}

if ($GatewayUrl) {
  & (Join-Path $PSScriptRoot "verify-prod.ps1") -GatewayUrl $GatewayUrl
}

Write-Host "Resume complete."
