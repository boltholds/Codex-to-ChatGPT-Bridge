[CmdletBinding()]
param(
    [string]$Profile = 'codex-bridge',

    [string]$TunnelClient = "$env:USERPROFILE\Downloads\tunnel-client.exe",

    [string]$HealthListenAddr = '127.0.0.1:8089',

    [ValidatePattern('^[0-9]+(?:ns|us|ms|s|m|h)$')]
    [string]$McpConnectionMaxTtl = '6h',

    [ValidateRange(1, 1000)]
    [int]$McpMaxConcurrentRequests = 1,

    [switch]$SkipDoctor,

    [switch]$NoAutoRestart,

    [ValidateRange(1, 300)]
    [int]$RestartDelaySeconds = 3,

    [ValidateRange(0, 1000)]
    [int]$MaxRestartAttempts = 0
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
$previousMcpConnectionMaxTtl = $env:MCP_CONNECTION_MAX_TTL
$previousMcpMaxConcurrentRequests = $env:MCP_MAX_CONCURRENT_REQUESTS

$env:HEALTH_LISTEN_ADDR = $HealthListenAddr
$env:MCP_CONNECTION_MAX_TTL = $McpConnectionMaxTtl
$env:MCP_MAX_CONCURRENT_REQUESTS = [string]$McpMaxConcurrentRequests

Push-Location $repoRoot
try {
    Write-Host "Using tunnel health/UI listener: $HealthListenAddr"
    Write-Host "Using MCP connection TTL: $McpConnectionMaxTtl"
    Write-Host "Using MCP max concurrent requests: $McpMaxConcurrentRequests"

    if (-not $SkipDoctor) {
        & $TunnelClient doctor --profile $Profile --explain
        if ($LASTEXITCODE -ne 0) {
            throw "tunnel-client doctor failed with exit code $LASTEXITCODE."
        }
    }

    $restartAttempt = 0
    while ($true) {
        Write-Host "Starting Secure MCP Tunnel profile '$Profile'. Keep this window open."
        & $TunnelClient run --profile $Profile
        $runExitCode = $LASTEXITCODE

        if ($NoAutoRestart) {
            if ($runExitCode -eq 0) {
                Write-Host "tunnel-client stopped cleanly."
                break
            }
            throw "tunnel-client run failed with exit code $runExitCode."
        }

        $restartAttempt += 1
        if ($MaxRestartAttempts -gt 0 -and $restartAttempt -gt $MaxRestartAttempts) {
            throw (
                "tunnel-client exited with code $runExitCode and exceeded " +
                "$MaxRestartAttempts restart attempts."
            )
        }

        Write-Warning (
            "tunnel-client exited with code $runExitCode. Restarting profile '$Profile' " +
            "in $RestartDelaySeconds seconds (attempt $restartAttempt)."
        )
        Start-Sleep -Seconds $RestartDelaySeconds
    }
}
finally {
    Pop-Location
    $env:HEALTH_LISTEN_ADDR = $previousHealthListenAddr
    $env:MCP_CONNECTION_MAX_TTL = $previousMcpConnectionMaxTtl
    $env:MCP_MAX_CONCURRENT_REQUESTS = $previousMcpMaxConcurrentRequests
}
