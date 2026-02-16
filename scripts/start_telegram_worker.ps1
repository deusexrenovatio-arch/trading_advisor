[CmdletBinding()]
param(
    [string]$ConfigPath = "configs/default.yaml",
    [string]$LogLevel = "INFO",
    [string]$PythonExe = "",
    [switch]$NoLocalEnv,
    [switch]$AllowMultiple,
    [switch]$SkipBackendCheck,
    [switch]$CheckOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-PythonExecutable {
    param([string]$Requested)

    if ($Requested) {
        return $Requested
    }

    $candidate = Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"
    if (Test-Path $candidate) {
        return $candidate
    }
    return "python"
}

function Get-RunningTelegramWorkers {
    try {
        return Get-CimInstance Win32_Process |
            Where-Object {
                $_.Name -match "^python" -and
                $_.CommandLine -match "moex_carry\.cli telegram_bot"
            }
    }
    catch {
        Write-Warning "[moex] Could not query process list: $($_.Exception.Message)"
        return @()
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$configAbsolute = if ([System.IO.Path]::IsPathRooted($ConfigPath)) {
    $ConfigPath
}
else {
    Join-Path $repoRoot $ConfigPath
}
$localEnvPath = Join-Path $PSScriptRoot "moex-carry.local.ps1"
$python = Resolve-PythonExecutable -Requested $PythonExe

if ((-not $NoLocalEnv) -and (Test-Path $localEnvPath)) {
    . $localEnvPath
}

$env:PYTHONPATH = Join-Path $repoRoot "src"
if (-not $env:MOEX_CARRY_TELEGRAM__ENABLED) {
    $env:MOEX_CARRY_TELEGRAM__ENABLED = "true"
}
if (-not $env:MOEX_CARRY_TELEGRAM__BACKEND_BASE_URL) {
    $env:MOEX_CARRY_TELEGRAM__BACKEND_BASE_URL = "http://127.0.0.1:8050"
}
if (-not $env:MOEX_CARRY_TELEGRAM__STATE_PATH) {
    $env:MOEX_CARRY_TELEGRAM__STATE_PATH = ("{0}/data/telegram/bot_state.json" -f $repoRoot.Replace("\", "/"))
}

if (-not $env:MOEX_CARRY_TELEGRAM__BOT_TOKEN) {
    throw "MOEX_CARRY_TELEGRAM__BOT_TOKEN is required. Put it into scripts/moex-carry.local.ps1"
}
if (-not $env:MOEX_CARRY_TELEGRAM__ALLOWED_USER_IDS) {
    throw "MOEX_CARRY_TELEGRAM__ALLOWED_USER_IDS is required. Example: [186419048]"
}

if (-not $AllowMultiple) {
    $runningWorkers = @(Get-RunningTelegramWorkers)
    if ($runningWorkers.Count -gt 0) {
        $pids = ($runningWorkers | ForEach-Object { $_.ProcessId }) -join ","
        Write-Host "[moex] Telegram worker is already running. PID: $pids"
        Write-Host "[moex] Exit without starting a second poller."
        exit 0
    }
}

$backendUrl = $env:MOEX_CARRY_TELEGRAM__BACKEND_BASE_URL.TrimEnd("/")
if (-not $SkipBackendCheck) {
    try {
        $null = Invoke-RestMethod "$backendUrl/api/signals/active" -TimeoutSec 8
        Write-Host "[moex] Backend check OK: $backendUrl/api/signals/active"
    }
    catch {
        Write-Warning "[moex] Backend check failed: $($_.Exception.Message)"
        Write-Warning "[moex] Worker will start anyway."
    }
}

Write-Host "[moex] RepoRoot: $repoRoot"
Write-Host "[moex] Config: $configAbsolute"
Write-Host "[moex] Python: $python"
Write-Host "[moex] LogLevel: $LogLevel"
Write-Host "[moex] BackendBaseUrl: $backendUrl"
Write-Host "[moex] StatePath: $($env:MOEX_CARRY_TELEGRAM__STATE_PATH)"

if ($CheckOnly) {
    Write-Host "[moex] CheckOnly: no process started."
    exit 0
}

Set-Location $repoRoot
& $python -m moex_carry.cli telegram_bot --config $configAbsolute --log-level $LogLevel
exit $LASTEXITCODE
