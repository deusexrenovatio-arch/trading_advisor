[CmdletBinding()]
param(
    [ValidateSet("live", "backfill")]
    [string]$Mode = "live",
    [string]$NewsConfig = "configs/news-livecheck-ng.yaml",
    [string]$PythonExe = "",
    [int]$LookbackHours = 6,
    [int]$BarMinutes = 5,
    [double]$MinAbsZ = 2.0,
    [double]$RootMinFundamentalScore = 0.45,
    [double]$RootMinCauseConfidence = 0.45,
    [double]$AftershockMaxGapMin = 2880.0,
    [switch]$EnableCandidateNewsApiEnrichment,
    [int]$EnrichmentWindowMin = 90,
    [int]$EnrichmentMaxRequestsPerSymbol = 4,
    [switch]$NoRootMaintenance,
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
    "-m", "moex_carry.cli",
    "news_root_cycle",
    "--news-config", $newsConfigAbs,
    "--ingest-mode", $Mode,
    "--lookback-hours", [string]$LookbackHours,
    "--bar-minutes", [string]$BarMinutes,
    "--min-abs-z", [string]$MinAbsZ,
    "--root-min-fundamental-score", [string]$RootMinFundamentalScore,
    "--root-min-cause-confidence", [string]$RootMinCauseConfidence,
    "--aftershock-max-gap-min", [string]$AftershockMaxGapMin,
    "--enrichment-window-min", [string]$EnrichmentWindowMin,
    "--enrichment-max-requests-per-symbol", [string]$EnrichmentMaxRequestsPerSymbol
)

if ($EnableCandidateNewsApiEnrichment) {
    $argsList += "--enable-candidate-newsapi-enrichment"
}
if ($NoRootMaintenance) {
    $argsList += "--no-root-maintenance"
}

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
