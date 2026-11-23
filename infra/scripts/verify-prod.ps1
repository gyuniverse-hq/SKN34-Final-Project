# Smoke-check the production Gateway after deploy or resume.
# Usage:
#   pwsh -File infra/scripts/verify-prod.ps1 -GatewayUrl https://api.example.com
#   pwsh -File infra/scripts/verify-prod.ps1 -GatewayUrl http://127.0.0.1:8080

param(
  [Parameter(Mandatory = $true)]
  [string]$GatewayUrl
)

$ErrorActionPreference = "Stop"
$base = $GatewayUrl.TrimEnd("/")

function Assert-Ok([string]$Path, [int[]]$OkStatuses = @(200)) {
  $url = "$base$Path"
  Write-Host "GET $url"
  try {
    $resp = Invoke-WebRequest -Uri $url -Method GET -UseBasicParsing -TimeoutSec 30
  }
  catch {
    if ($_.Exception.Response) {
      $code = [int]$_.Exception.Response.StatusCode
      if ($OkStatuses -contains $code) {
        Write-Host "  -> $code (accepted)"
        return
      }
    }
    throw "Failed $url : $_"
  }
  if ($OkStatuses -notcontains [int]$resp.StatusCode) {
    throw "Unexpected status $([int]$resp.StatusCode) for $url"
  }
  Write-Host "  -> $([int]$resp.StatusCode) ok"
}

Assert-Ok "/healthz" @(200)
# Prefer the public health that reports integrations when routed under /api.
try {
  Assert-Ok "/api/health" @(200)
}
catch {
  Write-Host "warn: /api/health not available yet ($_); continuing"
}

Assert-Ok "/api/products" @(200)

Write-Host "verify-prod: passed against $base"
