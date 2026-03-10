[CmdletBinding()]
param(
    [string]$ConfigPath = "configs/default.yaml",
    [string]$LogLevel = "INFO"
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

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$configAbsolute = if ([System.IO.Path]::IsPathRooted($ConfigPath)) {
    $ConfigPath
}
else {
    Join-Path $repoRoot $ConfigPath
}
$backendScript = Join-Path $repoRoot "scripts\start_backend.ps1"
$workerScript = Join-Path $repoRoot "scripts\start_telegram_worker.ps1"
$frontendScript = Join-Path $repoRoot "scripts\start_frontend.ps1"
$powerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$logDir = Join-Path $repoRoot "data\runtime-logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$backendOut = Join-Path $logDir "backend.out.log"
$backendErr = Join-Path $logDir "backend.err.log"
$workerOut = Join-Path $logDir "worker.out.log"
$workerErr = Join-Path $logDir "worker.err.log"
$frontendOut = Join-Path $logDir "frontend.out.log"
$frontendErr = Join-Path $logDir "frontend.err.log"

if (-not (Is-ProcessRunning -NameRegex "^python" -CommandRegex "moex_carry\.cli server")) {
    Start-Process `
        -FilePath $powerShellExe `
        -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$backendScript`" -ConfigPath `"$configAbsolute`" -LogLevel `"$LogLevel`"" `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput $backendOut `
        -RedirectStandardError $backendErr `
        -WindowStyle Hidden | Out-Null
}

if (-not (Is-ProcessRunning -NameRegex "^python" -CommandRegex "moex_carry\.cli telegram_bot")) {
    Start-Process `
        -FilePath $powerShellExe `
        -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$workerScript`" -ConfigPath `"$configAbsolute`" -LogLevel `"$LogLevel`"" `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput $workerOut `
        -RedirectStandardError $workerErr `
        -WindowStyle Hidden | Out-Null
}

$vitePathRegex = [regex]::Escape((Join-Path $repoRoot "ui-web")) + ".*vite[\\/]+bin[\\/]+vite\.js"
if (-not (Is-ProcessRunning -NameRegex "^node" -CommandRegex $vitePathRegex)) {
    Start-Process `
        -FilePath $powerShellExe `
        -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$frontendScript`" -FrontendHost `"127.0.0.1`" -FrontendPort `"5176`"" `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput $frontendOut `
        -RedirectStandardError $frontendErr `
        -WindowStyle Hidden | Out-Null
}
