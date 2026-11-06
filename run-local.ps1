<#
.SYNOPSIS
  Start the TrustAI stack locally (no Docker): governance :8004, AI gateway :8005, dashboard :3001.

.DESCRIPTION
  Opens one PowerShell window per service so each log stays visible; close a window to stop that service.
  Local-only development settings (SQLite database, dev static API key, mock model upstreams).
  Override any value by setting the environment variable before running this script.

.EXAMPLE
  cd "C:\Users\kishore kumar\Desktop\TrustAI"
  powershell -ExecutionPolicy Bypass -File .\run-local.ps1
#>

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

# Returns the environment variable's value, or the local-dev default when it is not set.
function Get-Setting([string]$name, [string]$default) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if ([string]::IsNullOrWhiteSpace($value)) { return $default }
    return $value
}

$dbPath         = (Join-Path $root ".local\governance.db") -replace "\\", "/"
$internalSecret = Get-Setting "TRUSTAI_INTERNAL_API_SECRET" "local-internal-secret"
$staticKeys     = Get-Setting "TRUSTAI_GOVERNANCE_STATIC_KEYS" "tai_live_local_factory_key_01=55555555-5555-5555-5555-555555555555"
$upstreams      = Get-Setting "TRUSTAI_GATEWAY_UPSTREAMS" '{"claude-sonnet-4-5": {"provider": "mock"}, "gpt-4o": {"provider": "mock"}, "trustai-mock": {"provider": "mock"}}'
$cors           = '["http://localhost:3001"]'

New-Item -ItemType Directory -Force (Join-Path $root ".local") | Out-Null

# Observability (traces) + admin run in Docker from the already-built images: Postgres, Redis, ingestion :8001,
# API :8002, admin :8003 (issues agent ingest keys), processor. docker compose reads TRUSTAI_INTERNAL_API_SECRET
# from .env, which must match the value the governance window uses below.
Push-Location $root
try {
    docker compose up -d --no-build postgres postgres-analytics redis migrate ingestion api admin processor
    if ($LASTEXITCODE -ne 0) { Write-Warning "docker compose failed - Traces and agent key provisioning will not work" }
} finally { Pop-Location }

# Starts one service in its own window; $envVars is a hashtable applied inside that window only.
function Start-Service-Window([string]$title, [string]$dir, [hashtable]$envVars, [string]$command) {
    $sets = ($envVars.GetEnumerator() | ForEach-Object {
        "`$env:$($_.Key) = '$($_.Value -replace "'", "''")'"
    }) -join "; "
    $script = "`$Host.UI.RawUI.WindowTitle = '$title'; Set-Location '$dir'; $sets; $command"
    # -EncodedCommand (UTF-16LE base64): Windows command-line parsing would strip the double quotes inside JSON
    # values such as TRUSTAI_CORS_ORIGINS='["http://..."]', and the service would then fail to start.
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
    Start-Process powershell -ArgumentList "-NoExit", "-EncodedCommand", $encoded | Out-Null
    Write-Host "started $title"
}

Start-Service-Window "TrustAI governance :8004" (Join-Path $root "services\governance") @{
    TRUSTAI_ENVIRONMENT            = "development"
    TRUSTAI_POSTGRES_URL           = "sqlite+aiosqlite:///$dbPath"
    TRUSTAI_GOVERNANCE_STATIC_KEYS = $staticKeys
    TRUSTAI_INTERNAL_API_SECRET    = $internalSecret
    TRUSTAI_EVAL_EXECUTOR          = "inline"
    TRUSTAI_GATEWAY_PUBLIC_URL     = "http://localhost:8005"
    TRUSTAI_PORTAL_URL             = "http://localhost:3001"
    TRUSTAI_CORS_ORIGINS           = $cors
    TRUSTAI_ADMIN_URL              = "http://localhost:8003"
    TRUSTAI_INGESTION_PUBLIC_URL   = "http://localhost:8001"
} ".\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8004"

Start-Service-Window "TrustAI gateway :8005" (Join-Path $root "services\gateway") @{
    TRUSTAI_ENVIRONMENT         = "development"
    TRUSTAI_GOVERNANCE_URL      = "http://127.0.0.1:8004"
    TRUSTAI_INTERNAL_API_SECRET = $internalSecret
    TRUSTAI_GATEWAY_UPSTREAMS   = $upstreams
    TRUSTAI_CORS_ORIGINS        = $cors
} ".\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8005"

Start-Service-Window "TrustAI dashboard :3001" (Join-Path $root "dashboard") @{
    NEXT_PUBLIC_GOVERNANCE_URL = "http://127.0.0.1:8004"
    INTERNAL_GOVERNANCE_URL    = "http://127.0.0.1:8004"
    NEXT_PUBLIC_GATEWAY_URL    = "http://localhost:8005"
} "npx next dev -p 3001"

Write-Host ""
Write-Host "Dashboard   http://localhost:3001/governance"
Write-Host "Governance  http://localhost:8004/docs"
Write-Host "Gateway     http://localhost:8005/docs"
Write-Host "Traces      http://localhost:3001/traces   (ingestion :8001, API :8002, admin :8003 in Docker)"
