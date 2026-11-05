param(
    [string]$HostAddress = "127.0.0.1",
    [ValidateRange(1024, 65535)][int]$Port = 8000
)
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$mlProject = Join-Path $repoRoot "ml"
$configFile = Join-Path $repoRoot ".env.skin-server.local"
if (-not (Test-Path -LiteralPath $configFile)) {
    throw "Copy .env.skin-server.example to .env.skin-server.local and configure server authentication first."
}
$allowedNames = @("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SKIN_AUTH_MODE", "SKIN_TEST_BEARER_TOKEN", "SKIN_GPU_UUID", "SKIN_MODEL_BUNDLE", "SKIN_FACE_MODEL", "SKIN_MAX_UPLOAD_BYTES")
foreach ($line in Get-Content -LiteralPath $configFile) {
    if ($line -match '^\s*(#|$)') { continue }
    $parts = $line -split '=', 2
    if ($parts.Count -ne 2 -or $parts[0].Trim() -notin $allowedNames) { throw "Unknown server configuration entry" }
    $name = $parts[0].Trim()
    $value = $parts[1].Trim()
    if ($value -and -not [Environment]::GetEnvironmentVariable($name, 'Process')) {
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}
$authMode = if ($env:SKIN_AUTH_MODE) { $env:SKIN_AUTH_MODE } else { "supabase" }
if ($authMode -eq "test-token") {
    if (-not $env:SKIN_TEST_BEARER_TOKEN -or $env:SKIN_TEST_BEARER_TOKEN.Length -lt 32) {
        throw "SKIN_TEST_BEARER_TOKEN must be at least 32 characters in test-token mode"
    }
} elseif ($authMode -eq "supabase") {
    if (-not $env:SUPABASE_URL -or -not $env:SUPABASE_PUBLISHABLE_KEY) { throw "Supabase server authentication is not configured" }
} else { throw "SKIN_AUTH_MODE must be 'supabase' or 'test-token'" }
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONPATH = "$repoRoot;$env:PYTHONPATH"
if (-not $env:UV_CACHE_DIR) { $env:UV_CACHE_DIR = Join-Path $mlProject ".uv-cache" }
$facePath = if ($env:SKIN_FACE_MODEL) { $env:SKIN_FACE_MODEL } else {
    Join-Path $mlProject "runs/face-detection/face_detection_yunet_2023mar.onnx"
}
& uv run --project $mlProject --locked --no-dev --group inference-server python -B -m server.nia.face_detection --download --output $facePath
if ($LASTEXITCODE -ne 0) { throw "Face-detector setup failed" }
Write-Host "Desktop inference: http://${HostAddress}:$Port (one CUDA worker, $authMode authentication)"
& uv run --project $mlProject --locked --no-dev --group inference-server python -B -m uvicorn server.nia.api:app --host $HostAddress --port $Port --workers 1 --no-proxy-headers --no-access-log
exit $LASTEXITCODE
