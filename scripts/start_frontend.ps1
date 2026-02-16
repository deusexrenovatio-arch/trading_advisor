[CmdletBinding()]
param(
    [string]$FrontendHost = "127.0.0.1",
    [int]$FrontendPort = 5176,
    [string]$NpmCmd = "",
    [switch]$AllowMultiple,
    [switch]$CheckOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-NpmCmd {
    param([string]$Requested)

    if ($Requested) {
        return $Requested
    }

    $defaultCmd = Join-Path $env:ProgramFiles "nodejs\npm.cmd"
    if (Test-Path $defaultCmd) {
        return $defaultCmd
    }

    $programFilesX86 = ${env:ProgramFiles(x86)}
    if ($programFilesX86) {
        $fallbackCmd = Join-Path $programFilesX86 "nodejs\npm.cmd"
        if (Test-Path $fallbackCmd) {
            return $fallbackCmd
        }
    }

    return "npm"
}

function Get-RunningFrontend {
    param(
        [string]$RepoRoot,
        [string]$HostValue,
        [int]$PortValue
    )

    $frontendRoot = Join-Path $RepoRoot "ui-web"
    $frontendRegex = [regex]::Escape($frontendRoot)
    $commandRegex = "$frontendRegex.*vite[\\/]+bin[\\/]+vite\.js.*--host\s+$([regex]::Escape($HostValue)).*--port\s+$PortValue"
    try {
        return Get-CimInstance Win32_Process |
            Where-Object {
                $_.Name -match "^node" -and
                $_.CommandLine -match $commandRegex
            }
    }
    catch {
        Write-Warning "[moex] Could not query process list: $($_.Exception.Message)"
        return @()
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$frontendRoot = Join-Path $repoRoot "ui-web"
if (-not (Test-Path $frontendRoot)) {
    throw "Missing frontend directory: $frontendRoot"
}

$npmCmdResolved = Resolve-NpmCmd -Requested $NpmCmd

if (-not $AllowMultiple) {
    $runningFrontend = @(Get-RunningFrontend -RepoRoot $repoRoot -HostValue $FrontendHost -PortValue $FrontendPort)
    if ($runningFrontend.Count -gt 0) {
        $pids = ($runningFrontend | ForEach-Object { $_.ProcessId }) -join ","
        Write-Host "[moex] Frontend is already running. PID: $pids"
        Write-Host "[moex] Exit without starting a second frontend process."
        exit 0
    }
}

Write-Host "[moex] RepoRoot: $repoRoot"
Write-Host "[moex] FrontendRoot: $frontendRoot"
Write-Host "[moex] npm: $npmCmdResolved"
Write-Host "[moex] Host: $FrontendHost"
Write-Host "[moex] Port: $FrontendPort"

if ($CheckOnly) {
    Write-Host "[moex] CheckOnly: no process started."
    exit 0
}

Set-Location $frontendRoot
& $npmCmdResolved run dev -- --host $FrontendHost --port $FrontendPort
exit $LASTEXITCODE
