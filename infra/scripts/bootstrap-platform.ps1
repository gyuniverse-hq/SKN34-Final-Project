# Install cluster add-ons once after `terraform apply`.
# Prerequisites: aws, kubectl, helm; kubeconfig already points at the vishue cluster.
# Usage (repo root):
#   pwsh -File infra/scripts/bootstrap-platform.ps1

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repoRoot

Write-Host "==> metrics-server"
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/ 2>$null
helm repo update metrics-server
helm upgrade --install metrics-server metrics-server/metrics-server -n kube-system

Write-Host "==> Envoy Gateway"
helm upgrade --install eg oci://docker.io/envoyproxy/gateway-helm `
  -n envoy-gateway-system --create-namespace

Write-Host "==> External Secrets"
helm repo add external-secrets https://charts.external-secrets.io 2>$null
helm repo update external-secrets
helm upgrade --install external-secrets external-secrets/external-secrets `
  -n external-secrets --create-namespace

Write-Host "==> Argo CD"
helm repo add argo https://argoproj.github.io/argo-helm 2>$null
helm repo update argo
helm upgrade --install argocd argo/argo-cd -n argocd --create-namespace

Write-Host "==> platform manifests"
kubectl apply -f infra/platform/gatewayclass.yaml
kubectl apply -f infra/platform/cluster-secret-store.yaml
kubectl apply -f infra/platform/restore-serviceaccount.yaml
kubectl apply -f infra/argocd/project.yaml
kubectl apply -f infra/argocd/application-prod.yaml

Write-Host "Done. Fill Secrets Manager + values-prod.yaml, then wait for Argo CD to sync."
Write-Host "Verify: kubectl -n argocd get applications"
Write-Host "Dump restore SA: vishue/vishue-restore (ops S3 dumps/)"
