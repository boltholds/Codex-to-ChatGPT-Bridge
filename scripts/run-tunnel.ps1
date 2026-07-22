[CmdletBinding()]
param(
    [string]$Profile = 'codex-bridge',

    [string]$TunnelClient = "$env:USERPROFILE\Downloads\tunnel-client.exe",

    [string]$HealthListenAddr = '127.0.0.1:8081',

    [switch]$SkipDoctor
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
$envFile = Join-Path $repoRoot '.env'

if (-not (Test-Path -LiteralPath $TunnelClient -PathType Leaf)) {
    throw "tunnel-client.exe was not found at '$TunnelClient'. Pass -TunnelClient with its full path."
}

if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw "Virtual environment Python was not found at '$pythonExe'."
}

if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw "Missing '$envFile'. Copy .env.example to .env and configure it first."
}

if ([string]::IsNullOrWhiteSpace($env:CONTROL_PLANE_API_KEY)) {
    throw 'CONTROL_PLANE_API_KEY is not set in this PowerShell session.'
}

if ($null -eq (Get-Command codex -ErrorAction SilentlyContinue)) {
    throw 'Codex CLI is not available on PATH.'
}

$previousHealthListenAddr = $env:HEALTH_LISTEN_ADDR
$env:HEALTH_LISTEN_ADDR = $HealthListenAddr

Push-Location $repoRoot
try {
    Write-Host "Using tunnel health/UI listener: $HealthListenAddr"

    if (-not $SkipDoctor) {
        & $TunnelClient doctor --profile $Profile --explain
        if ($LASTEXITCODE -ne 0) {
            throw "tunnel-client doctor failed with exit code $LASTEXITCODE."
        }
    }

    Write-Host "Starting Secure MCP Tunnel profile '$Profile'. Keep this window open."
    & $TunnelClient run --profile $Profile
    if ($LASTEXITCODE -ne 0) {
        throw "tunnel-client run failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
    $env:HEALTH_LISTEN_ADDR = $previousHealthListenAddr
}
