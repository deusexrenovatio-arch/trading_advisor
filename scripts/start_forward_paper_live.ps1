[CmdletBinding()]
param(
    [string]$ConfigPath = "configs/default.yaml",
    [string]$LogLevel = "INFO",
    [string]$PythonExe = "",
    [switch]$NoLocalEnv,
    [switch]$SkipTelegramWorker,
    [switch]$SkipForwardStart,
    [switch]$ForceFullRefresh,
    [int]$BackendWaitSec = 45,
    [switch]$CheckOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Is-ProcessRunning {
    param(
        [string]$NameRegex,
        [string]$CommandRegex
    )

    $matches = Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -match $NameRegex -and
            $_.CommandLine -match $CommandRegex
        }
    return @($matches).Count -gt 0
}

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

function Wait-BackendReady {
    param(
        [string]$BaseUrl,
        [int]$WaitSec
    )

    $deadline = (Get-Date).AddSeconds([Math]::Max($WaitSec, 1))
    while ((Get-Date) -lt $deadline) {
        try {
            $null = Invoke-RestMethod "$BaseUrl/api/signals/refresh-status" -Method Get -TimeoutSec 8
            return $true
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }
    return $false
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
$backendScript = Join-Path $repoRoot "scripts\start_backend.ps1"
$workerScript = Join-Path $repoRoot "scripts\start_telegram_worker.ps1"
$logDir = Join-Path $repoRoot "data\runtime-logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$backendOut = Join-Path $logDir "backend.out.log"
$backendErr = Join-Path $logDir "backend.err.log"
$workerOut = Join-Path $logDir "worker.out.log"
$workerErr = Join-Path $logDir "worker.err.log"

$backendBaseUrl = $env:MOEX_CARRY_TELEGRAM__BACKEND_BASE_URL
if (-not $backendBaseUrl) {
    $backendBaseUrl = "http://127.0.0.1:8050"
}
$backendBaseUrl = $backendBaseUrl.TrimEnd("/")

Write-Host "[moex] RepoRoot: $repoRoot"
Write-Host "[moex] Config: $configAbsolute"
Write-Host "[moex] Python: $python"
Write-Host "[moex] BackendBaseUrl: $backendBaseUrl"
Write-Host "[moex] Mode: paper-forward-live"

if (-not (Is-ProcessRunning -NameRegex "^python" -CommandRegex "moex_carry\.cli ui")) {
    Write-Host "[moex] Starting backend..."
    if (-not $CheckOnly) {
        Start-Process `
            -FilePath "powershell.exe" `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$backendScript`" -ConfigPath `"$configAbsolute`" -LogLevel `"$LogLevel`"" `
            -WorkingDirectory $repoRoot `
            -RedirectStandardOutput $backendOut `
            -RedirectStandardError $backendErr | Out-Null
    }
}
else {
    Write-Host "[moex] Backend already running."
}

if ($CheckOnly) {
    Write-Host "[moex] CheckOnly: no requests or workers started."
    exit 0
}

if (-not (Wait-BackendReady -BaseUrl $backendBaseUrl -WaitSec $BackendWaitSec)) {
    throw "Backend did not become ready within ${BackendWaitSec}s: $backendBaseUrl"
}
Write-Host "[moex] Backend ready."

$refreshUrl = "$backendBaseUrl/api/signals/refresh"
if ($ForceFullRefresh) {
    $refreshUrl = "${refreshUrl}?force_full=1"
}
Write-Host "[moex] Triggering signal refresh: $refreshUrl"
$refresh = Invoke-RestMethod $refreshUrl -Method Post -TimeoutSec 180
Write-Host ("[moex] Refresh status={0}; rows={1}; engine={2}" -f $refresh.status, $refresh.rows, $refresh.engine)

if (-not $SkipTelegramWorker) {
    $tokenPresent = [bool][Environment]::GetEnvironmentVariable("MOEX_CARRY_TELEGRAM__BOT_TOKEN")
    $allowedPresent = [bool][Environment]::GetEnvironmentVariable("MOEX_CARRY_TELEGRAM__ALLOWED_USER_IDS")
    if (-not $tokenPresent -or -not $allowedPresent) {
        Write-Warning "[moex] Telegram worker skipped: set MOEX_CARRY_TELEGRAM__BOT_TOKEN and MOEX_CARRY_TELEGRAM__ALLOWED_USER_IDS (or scripts/moex-carry.local.ps1)."
    }
    elseif (-not (Is-ProcessRunning -NameRegex "^python" -CommandRegex "moex_carry\.cli telegram_bot")) {
        Write-Host "[moex] Starting Telegram worker..."
        Start-Process `
            -FilePath "powershell.exe" `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$workerScript`" -ConfigPath `"$configAbsolute`" -LogLevel `"$LogLevel`"" `
            -WorkingDirectory $repoRoot `
            -RedirectStandardOutput $workerOut `
            -RedirectStandardError $workerErr | Out-Null
    }
    else {
        Write-Host "[moex] Telegram worker already running."
    }
}
else {
    Write-Host "[moex] Telegram worker skipped by flag."
}

if (-not $SkipForwardStart) {
    $today = (Get-Date).ToString("yyyy-MM-dd")
    $forwardBody = @{
        request = @{
            as_of_date = $today
            test = @{
                start_date = $today
                end_date = $today
                timezone = "Europe/Moscow"
            }
        }
    } | ConvertTo-Json -Depth 8

    Write-Host "[moex] Starting forward run for $today ..."
    $forwardUrl = "$backendBaseUrl/api/forward/start"
    $runInfo = $null
    try {
        $runInfo = Invoke-RestMethod `
            $forwardUrl `
            -Method Post `
            -ContentType "application/json" `
            -Body $forwardBody `
            -TimeoutSec 60
    }
    catch {
        $errorDetails = ""
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            $errorDetails = [string]$_.ErrorDetails.Message
        }
        else {
            $errorDetails = [string]$_.Exception.Message
        }
        if ($errorDetails -notmatch "Missing raw data") {
            throw
        }

        Write-Warning "[moex] Forward start requires reference data. Running fetch before retry..."
        Push-Location $repoRoot
        try {
            & $python -m moex_carry.cli fetch --config $configAbsolute --log-level $LogLevel
            if ($LASTEXITCODE -ne 0) {
                throw "Reference data fetch failed with exit code $LASTEXITCODE"
            }
        }
        finally {
            Pop-Location
        }

        Write-Host "[moex] Retrying forward run start..."
        $runInfo = Invoke-RestMethod `
            $forwardUrl `
            -Method Post `
            -ContentType "application/json" `
            -Body $forwardBody `
            -TimeoutSec 60
    }

    $runId = [string]$runInfo.run_id
    Write-Host "[moex] Forward run_id: $runId"

    $status = Invoke-RestMethod "$backendBaseUrl/api/forward/status?run_id=$runId" -Method Get -TimeoutSec 30
    Write-Host ("[moex] Forward status={0}; config_hash={1}" -f $status.status, $status.state.config_hash)
}
else {
    Write-Host "[moex] Forward start skipped by flag."
}

Write-Host "[moex] Live paper-forward contour is up."
