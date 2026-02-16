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
$logDir = Join-Path $repoRoot "data\runtime-logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$backendOut = Join-Path $logDir "backend.out.log"
$backendErr = Join-Path $logDir "backend.err.log"
$workerOut = Join-Path $logDir "worker.out.log"
$workerErr = Join-Path $logDir "worker.err.log"
$frontendOut = Join-Path $logDir "frontend.out.log"
$frontendErr = Join-Path $logDir "frontend.err.log"

if (-not (Is-ProcessRunning -NameRegex "^python" -CommandRegex "moex_carry\.cli ui")) {
    Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            (Join-Path $repoRoot "scripts\start_backend.ps1"),
            "-ConfigPath",
            $ConfigPath,
            "-LogLevel",
            $LogLevel
        ) `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput $backendOut `
        -RedirectStandardError $backendErr | Out-Null
}

if (-not (Is-ProcessRunning -NameRegex "^python" -CommandRegex "moex_carry\.cli telegram_bot")) {
    Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            (Join-Path $repoRoot "scripts\start_telegram_worker.ps1"),
            "-ConfigPath",
            $ConfigPath,
            "-LogLevel",
            $LogLevel
        ) `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput $workerOut `
        -RedirectStandardError $workerErr | Out-Null
}

$vitePathRegex = [regex]::Escape((Join-Path $repoRoot "ui-web")) + ".*vite[\\/]+bin[\\/]+vite\.js"
if (-not (Is-ProcessRunning -NameRegex "^node" -CommandRegex $vitePathRegex)) {
    Start-Process `
        -FilePath "cmd.exe" `
        -ArgumentList @(
            "/c",
            "npm run dev -- --host 127.0.0.1 --port 5176"
        ) `
        -WorkingDirectory (Join-Path $repoRoot "ui-web") `
        -RedirectStandardOutput $frontendOut `
        -RedirectStandardError $frontendErr | Out-Null
}
