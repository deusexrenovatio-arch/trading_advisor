[CmdletBinding()]
param(
    [string]$TaskPrefix = "MoexCarry",
    [string]$ConfigPath = "configs/default.yaml",
    [string]$LogLevel = "INFO",
    [string]$RunAs = "SYSTEM",
    [string]$WorkerDelay = "0000:30",
    [string]$PowerShellExe = "",
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-SchtasksCommand {
    param([string[]]$Arguments)

    $commandPreview = "schtasks " + ($Arguments -join " ")
    Write-Host $commandPreview
    if ($DryRun) {
        return
    }

    & schtasks.exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "schtasks failed with exit code $LASTEXITCODE"
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendScript = Join-Path $PSScriptRoot "start_backend.ps1"
$workerScript = Join-Path $PSScriptRoot "start_telegram_worker.ps1"

if (-not (Test-Path $backendScript)) {
    throw "Missing script: $backendScript"
}
if (-not (Test-Path $workerScript)) {
    throw "Missing script: $workerScript"
}

if (-not $PowerShellExe) {
    $PowerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
}

$backendTaskName = "$TaskPrefix-Backend"
$workerTaskName = "$TaskPrefix-TelegramWorker"

$backendTriggerCommand = "`"$PowerShellExe`" -NoProfile -ExecutionPolicy Bypass -File `"$backendScript`" -ConfigPath `"$ConfigPath`" -LogLevel `"$LogLevel`""
$workerTriggerCommand = "`"$PowerShellExe`" -NoProfile -ExecutionPolicy Bypass -File `"$workerScript`" -ConfigPath `"$ConfigPath`" -LogLevel `"$LogLevel`""

Write-Host "[moex] RepoRoot: $repoRoot"
Write-Host "[moex] RunAs: $RunAs"
Write-Host "[moex] BackendTask: $backendTaskName"
Write-Host "[moex] WorkerTask: $workerTaskName"

$backendCreateArgs = @(
    "/Create", "/F",
    "/TN", $backendTaskName,
    "/SC", "ONSTART",
    "/RL", "HIGHEST",
    "/RU", $RunAs,
    "/TR", $backendTriggerCommand
)

$workerCreateArgs = @(
    "/Create", "/F",
    "/TN", $workerTaskName,
    "/SC", "ONSTART",
    "/DELAY", $WorkerDelay,
    "/RL", "HIGHEST",
    "/RU", $RunAs,
    "/TR", $workerTriggerCommand
)

Invoke-SchtasksCommand -Arguments $backendCreateArgs
Invoke-SchtasksCommand -Arguments $workerCreateArgs

Write-Host "[moex] Tasks installed."
Write-Host "[moex] Query command:"
Write-Host "schtasks /Query /TN `"$backendTaskName`" /V /FO LIST"
Write-Host "schtasks /Query /TN `"$workerTaskName`" /V /FO LIST"
