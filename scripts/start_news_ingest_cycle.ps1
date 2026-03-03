[CmdletBinding()]
param(
    [ValidateSet("live", "backfill")]
    [string]$Mode = "live",
    [string]$NewsConfig = "configs/news-livecheck-ng.yaml",
    [string]$PythonExe = "",
    [switch]$NoLocalEnv,
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

function Resolve-RepoPath {
    param(
        [string]$RepoRoot,
        [string]$PathValue
    )
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return ""
    }
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return $PathValue
    }
    return (Join-Path $RepoRoot $PathValue)
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$localEnvPath = Join-Path $PSScriptRoot "moex-carry.local.ps1"
$python = Resolve-PythonExecutable -Requested $PythonExe
$newsConfigAbs = Resolve-RepoPath -RepoRoot $repoRoot -PathValue $NewsConfig

if ((-not $NoLocalEnv) -and (Test-Path $localEnvPath)) {
    . $localEnvPath
}

$env:PYTHONPATH = Join-Path $repoRoot "src"
$argsList = @(
    "scripts/run_news_ingest_cycle.py",
    "--news-config", $newsConfigAbs,
    "--mode", $Mode
)

Write-Host "[moex] RepoRoot: $repoRoot"
Write-Host "[moex] Python: $python"
Write-Host "[moex] NewsConfig: $newsConfigAbs"
Write-Host "[moex] Mode: $Mode"
Write-Host "[moex] Command: $python $($argsList -join ' ')"

if ($CheckOnly) {
    Write-Host "[moex] CheckOnly: no process started."
    exit 0
}

Set-Location $repoRoot
& $python @argsList
exit $LASTEXITCODE

