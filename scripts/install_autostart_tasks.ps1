[CmdletBinding()]
param(
    [string]$TaskPrefix = "MoexCarry",
    [string]$ConfigPath = "configs/default.yaml",
    [string]$LogLevel = "INFO",
    [string]$RunAs = "SYSTEM",
    [int]$WorkerDelaySeconds = 30,
    [int]$FrontendDelaySeconds = 45,
    [string]$FrontendHost = "127.0.0.1",
    [int]$FrontendPort = 5176,
    [string]$PowerShellExe = "",
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $PowerShellExe) {
    $PowerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendScript = Join-Path $PSScriptRoot "start_backend.ps1"
$workerScript = Join-Path $PSScriptRoot "start_telegram_worker.ps1"
$frontendScript = Join-Path $PSScriptRoot "start_frontend.ps1"

if (-not (Test-Path $backendScript)) {
    throw "Missing script: $backendScript"
}
if (-not (Test-Path $workerScript)) {
    throw "Missing script: $workerScript"
}
if (-not (Test-Path $frontendScript)) {
    throw "Missing script: $frontendScript"
}

$backendTaskName = "$TaskPrefix-Backend"
$workerTaskName = "$TaskPrefix-TelegramWorker"
$frontendTaskName = "$TaskPrefix-Frontend"

$backendArguments = "-NoProfile -ExecutionPolicy Bypass -File `"$backendScript`" -ConfigPath `"$ConfigPath`" -LogLevel `"$LogLevel`""
$workerArguments = "-NoProfile -ExecutionPolicy Bypass -File `"$workerScript`" -ConfigPath `"$ConfigPath`" -LogLevel `"$LogLevel`""
$frontendArguments = "-NoProfile -ExecutionPolicy Bypass -File `"$frontendScript`" -FrontendHost `"$FrontendHost`" -FrontendPort `"$FrontendPort`""

$backendAction = New-ScheduledTaskAction -Execute $PowerShellExe -Argument $backendArguments
$workerAction = New-ScheduledTaskAction -Execute $PowerShellExe -Argument $workerArguments
$frontendAction = New-ScheduledTaskAction -Execute $PowerShellExe -Argument $frontendArguments

$backendTrigger = New-ScheduledTaskTrigger -AtStartup
$workerTrigger = New-ScheduledTaskTrigger -AtStartup
$frontendTrigger = New-ScheduledTaskTrigger -AtStartup
$workerTrigger.Delay = "PT${WorkerDelaySeconds}S"
$frontendTrigger.Delay = "PT${FrontendDelaySeconds}S"

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $RunAs -LogonType ServiceAccount -RunLevel Highest

Write-Host "[moex] RepoRoot: $repoRoot"
Write-Host "[moex] RunAs: $RunAs"
Write-Host "[moex] BackendTask: $backendTaskName"
Write-Host "[moex] WorkerTask: $workerTaskName"
Write-Host "[moex] FrontendTask: $frontendTaskName"
Write-Host "[moex] WorkerDelaySeconds: $WorkerDelaySeconds"
Write-Host "[moex] FrontendDelaySeconds: $FrontendDelaySeconds"
Write-Host "[moex] Backend command: $PowerShellExe $backendArguments"
Write-Host "[moex] Worker command: $PowerShellExe $workerArguments"
Write-Host "[moex] Frontend command: $PowerShellExe $frontendArguments"

if ($DryRun) {
    Write-Host "[moex] DryRun enabled: tasks were not created."
    exit 0
}

Register-ScheduledTask `
    -TaskName $backendTaskName `
    -Action $backendAction `
    -Trigger $backendTrigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Register-ScheduledTask `
    -TaskName $workerTaskName `
    -Action $workerAction `
    -Trigger $workerTrigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Register-ScheduledTask `
    -TaskName $frontendTaskName `
    -Action $frontendAction `
    -Trigger $frontendTrigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Write-Host "[moex] Tasks installed."
Write-Host "Get-ScheduledTask -TaskName '$backendTaskName' | Format-List TaskName,State,Actions,Triggers,Principal"
Write-Host "Get-ScheduledTask -TaskName '$workerTaskName' | Format-List TaskName,State,Actions,Triggers,Principal"
Write-Host "Get-ScheduledTask -TaskName '$frontendTaskName' | Format-List TaskName,State,Actions,Triggers,Principal"
