[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^tunnel_[A-Za-z0-9]+$')]
    [string]$TunnelId,

    [string]$Profile = 'codex-bridge',

    [string]$TunnelClient = "$env:USERPROFILE\Downloads\tunnel-client.exe",

    [switch]$Force,

    [switch]$OpenWebUi
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
$envFile = Join-Path $repoRoot '.env'

if (-not (Test-Path -LiteralPath $TunnelClient -PathType Leaf)) {
    throw "tunnel-client.exe was not found at '$TunnelClient'. Pass -TunnelClient with its full path."
}

if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw "Virtual environment Python was not found at '$pythonExe'. Create .venv and install the package first."
}

if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw "Missing '$envFile'. Copy .env.example to .env and configure BRIDGE_ALLOWED_ROOTS first."
}

$codexCommand = Get-Command codex -ErrorAction SilentlyContinue
if ($null -eq $codexCommand) {
    throw "Codex CLI is not available on PATH. Install/authenticate Codex CLI before creating the tunnel profile."
}

Push-Location $repoRoot
try {
    & $pythonExe -c "import codex_chatgpt_bridge; print('Bridge import: OK')"
    if ($LASTEXITCODE -ne 0) {
        throw 'The bridge package could not be imported from .venv.'
    }

    & $TunnelClient --version
    if ($LASTEXITCODE -ne 0) {
        throw 'tunnel-client.exe failed its version check.'
    }

    $pythonForProfile = $pythonExe.Replace('\', '/')
    $mcpCommand = "`"$pythonForProfile`" -m codex_chatgpt_bridge"

    $initArgs = @(
        'init',
        '--sample', 'sample_mcp_stdio_local',
        '--profile', $Profile,
        '--tunnel-id', $TunnelId,
        '--mcp-command', $mcpCommand
    )

    if ($Force) {
        $initArgs += '--force'
    }
    if ($OpenWebUi) {
        $initArgs += '--open-web-ui'
    }

    & $TunnelClient @initArgs
    if ($LASTEXITCODE -ne 0) {
        throw "tunnel-client init failed with exit code $LASTEXITCODE."
    }

    $profilePath = Join-Path $env:APPDATA "tunnel-client\$Profile.yaml"
    Write-Host "Tunnel profile created: $profilePath"
    Write-Host "Next: set CONTROL_PLANE_API_KEY in this terminal and run scripts\run-tunnel.ps1"
}
finally {
    Pop-Location
}
