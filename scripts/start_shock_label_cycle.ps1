[CmdletBinding()]
param(
    [string]$InputCsv = "data/output/news_perf_365d_5m_opt/shock_news_1h_annual_all.csv",
    [switch]$UseDbInput,
    [string]$InputDatabaseUrl = "sqlite:///./data/news_livecheck_ng.db",
    [string]$InputDataDir = "./data",
    [int]$InputBarMinutes = 5,
    [int]$InputMaxRows = 0,
    [switch]$RunShockBackfill,
    [string]$ShockBackfillCursorKey = "shock_rows_backfill_cursor_utc",
    [string]$ShockBackfillStartTs = "2025-01-01T00:00:00Z",
    [string]$ShockBackfillEndTs = "",
    [int]$ShockBackfillWindowHours = 24,
    [int]$ShockBackfillWindowsPerRun = 5,
    [switch]$ShockBackfillWriteSnapshotCsv,
    [string]$ShockBackfillSnapshotDir = "data/output/shock_backfill_snapshots",
    [string]$OutputRoot = "data/output/shock_label_cycle_auto",
    [string]$MainConfig = "",
    [string]$NewsConfig = "configs/news-livecheck-ng.yaml",
    [string]$StartTs = "",
    [string]$EndTs = "",
    [int]$FreshLookbackHours = 0,
    [double]$MinAbsZ = 2.5,
    [double]$MaxDelayMin = 60.0,
    [double]$StrictPreShockMin = 10.0,
    [int]$MaxTasksPerDaySymbol = 20,
    [int]$DirectionMaxTasks = 300,
    [int]$CausalMaxTasks = 900,
    [string]$DirectionCandidateSources = "v2_clean",
    [string]$CausalCandidateSources = "broad,none",
    [double]$IngestMinConfidence = 0.60,
    [string]$SilverDatabaseUrl = "sqlite:///./data/news_livecheck_ng.db",
    [string]$SilverDataDir = "./data",
    [switch]$NoPersistSilverDb,
    [switch]$NoAutoDeriveSilver,
    [double]$AutoDeriveSilverMinAbsZ = 2.5,
    [double]$AutoDeriveSilverMaxDelayMin = 120.0,
    [int]$AutoDeriveSilverMinSamples = 2,
    [double]$AutoDeriveSilverMinConfidence = 0.60,
    [string]$TelegramFeedPath = "data/output/shock_alerts/live_shocks.csv",
    [double]$TelegramFeedMinAbsZ = 2.0,
    [int]$TelegramFeedMaxRows = 5000,
    [switch]$NoTelegramFeed,
    [switch]$RunReadiness,
    [double]$PrimaryZ = 2.5,
    [double]$AftershockZ = 2.0,
    [int]$EpisodeWindowMin = 10080,
    [int]$MaxGapMin = 2880,
    [string]$DirectionLabelsJsonl = "",
    [string]$CausalLabelsJsonl = "",
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

if ((-not $NoLocalEnv) -and (Test-Path $localEnvPath)) {
    . $localEnvPath
}

$env:PYTHONPATH = Join-Path $repoRoot "src"
$inputCsvAbs = Resolve-RepoPath -RepoRoot $repoRoot -PathValue $InputCsv
$outputRootAbs = Resolve-RepoPath -RepoRoot $repoRoot -PathValue $OutputRoot
$directionLabelsAbs = Resolve-RepoPath -RepoRoot $repoRoot -PathValue $DirectionLabelsJsonl
$causalLabelsAbs = Resolve-RepoPath -RepoRoot $repoRoot -PathValue $CausalLabelsJsonl
$telegramFeedAbs = Resolve-RepoPath -RepoRoot $repoRoot -PathValue $TelegramFeedPath
$mainConfigAbs = Resolve-RepoPath -RepoRoot $repoRoot -PathValue $MainConfig
$newsConfigAbs = Resolve-RepoPath -RepoRoot $repoRoot -PathValue $NewsConfig

if ((-not $UseDbInput) -and $FreshLookbackHours -le 0 -and -not (Test-Path $inputCsvAbs)) {
    throw "Input CSV not found: $inputCsvAbs"
}
if (-not (Test-Path $newsConfigAbs)) {
    throw "News config not found: $newsConfigAbs"
}

$stamp = [DateTime]::UtcNow.ToString("yyyyMMdd_HHmmss")
$outputDir = Join-Path $outputRootAbs $stamp
$liveInputCsvAbs = Join-Path $outputDir "live_shocks_input.csv"

$buildLiveInput = (-not $UseDbInput) -and ($FreshLookbackHours -gt 0)
if ($buildLiveInput) {
    $inputCsvAbs = $liveInputCsvAbs
    $liveArgs = @(
        "scripts/build_live_shock_input.py",
        "--news-config", $newsConfigAbs,
        "--output-csv", $liveInputCsvAbs,
        "--lookback-hours", "$FreshLookbackHours",
        "--bar-minutes", "5",
        "--min-abs-z", "$MinAbsZ",
        "--max-delay-min", "$MaxDelayMin",
        "--strict-pre-shock-min", "$StrictPreShockMin",
        "--news-min-confidence", "$IngestMinConfidence"
    )
    if (-not [string]::IsNullOrWhiteSpace($mainConfigAbs)) {
        $liveArgs += @("--config", $mainConfigAbs)
    }
}

$argsList = @(
    "scripts/run_shock_label_cycle.py",
    "--output-dir", $outputDir,
    "--min-abs-z", "$MinAbsZ",
    "--max-delay-min", "$MaxDelayMin",
    "--max-tasks-per-day-symbol", "$MaxTasksPerDaySymbol",
    "--direction-max-tasks", "$DirectionMaxTasks",
    "--causal-max-tasks", "$CausalMaxTasks",
    "--direction-candidate-sources", $DirectionCandidateSources,
    "--causal-candidate-sources", $CausalCandidateSources,
    "--ingest-min-confidence", "$IngestMinConfidence",
    "--silver-database-url", $SilverDatabaseUrl,
    "--silver-data-dir", $SilverDataDir,
    "--auto-derive-silver-min-abs-z", "$AutoDeriveSilverMinAbsZ",
    "--auto-derive-silver-max-delay-min", "$AutoDeriveSilverMaxDelayMin",
    "--auto-derive-silver-min-samples", "$AutoDeriveSilverMinSamples",
    "--auto-derive-silver-min-confidence", "$AutoDeriveSilverMinConfidence",
    "--telegram-feed-min-abs-z", "$TelegramFeedMinAbsZ",
    "--telegram-feed-max-rows", "$TelegramFeedMaxRows",
    "--primary-z", "$PrimaryZ",
    "--aftershock-z", "$AftershockZ",
    "--episode-window-min", "$EpisodeWindowMin",
    "--max-gap-min", "$MaxGapMin"
)
if (-not [string]::IsNullOrWhiteSpace($mainConfigAbs)) {
    $argsList += @("--config", $mainConfigAbs)
}
if (-not [string]::IsNullOrWhiteSpace($newsConfigAbs)) {
    $argsList += @("--news-config", $newsConfigAbs)
}

if ($UseDbInput) {
    $argsList += @(
        "--input-database-url", $InputDatabaseUrl,
        "--input-data-dir", $InputDataDir,
        "--input-bar-minutes", "$InputBarMinutes",
        "--input-max-rows", "$InputMaxRows"
    )
}
else {
    $argsList += @("--input-csv", $inputCsvAbs)
}

if (-not [string]::IsNullOrWhiteSpace($StartTs)) {
    $argsList += @("--start-ts", $StartTs)
}
elseif ($FreshLookbackHours -gt 0) {
    $autoStartTs = [DateTime]::UtcNow.AddHours(-1 * $FreshLookbackHours).ToString("yyyy-MM-ddTHH:mm:ssZ")
    $argsList += @("--start-ts", $autoStartTs)
}
if (-not [string]::IsNullOrWhiteSpace($EndTs)) {
    $argsList += @("--end-ts", $EndTs)
}
if (-not [string]::IsNullOrWhiteSpace($directionLabelsAbs)) {
    $argsList += @("--direction-labels-jsonl", $directionLabelsAbs)
}
if (-not [string]::IsNullOrWhiteSpace($causalLabelsAbs)) {
    $argsList += @("--causal-labels-jsonl", $causalLabelsAbs)
}
if ($NoPersistSilverDb) {
    $argsList += "--no-persist-silver-db"
}
if ($NoAutoDeriveSilver) {
    $argsList += "--no-auto-derive-silver"
}
if ($NoTelegramFeed) {
    $argsList += "--no-telegram-feed"
}
elseif (-not [string]::IsNullOrWhiteSpace($telegramFeedAbs)) {
    $argsList += @("--telegram-feed-path", $telegramFeedAbs)
}
if ($RunReadiness) {
    $argsList += "--run-readiness"
}
if ($RunShockBackfill) {
    $argsList += @(
        "--run-shock-backfill",
        "--shock-backfill-cursor-key", $ShockBackfillCursorKey,
        "--shock-backfill-start-ts", $ShockBackfillStartTs,
        "--shock-backfill-window-hours", "$ShockBackfillWindowHours",
        "--shock-backfill-windows-per-run", "$ShockBackfillWindowsPerRun",
        "--shock-backfill-snapshot-dir", $ShockBackfillSnapshotDir
    )
    if (-not [string]::IsNullOrWhiteSpace($ShockBackfillEndTs)) {
        $argsList += @("--shock-backfill-end-ts", $ShockBackfillEndTs)
    }
    if ($ShockBackfillWriteSnapshotCsv) {
        $argsList += "--shock-backfill-write-snapshot-csv"
    }
}

Write-Host "[moex] RepoRoot: $repoRoot"
Write-Host "[moex] Python: $python"
Write-Host "[moex] InputCsv: $inputCsvAbs"
Write-Host "[moex] OutputDir: $outputDir"
if ($FreshLookbackHours -gt 0 -and [string]::IsNullOrWhiteSpace($StartTs)) {
    Write-Host "[moex] AutoStartTs: $autoStartTs (FreshLookbackHours=$FreshLookbackHours)"
}
Write-Host "[moex] Command: $python $($argsList -join ' ')"

if ($CheckOnly) {
    Write-Host "[moex] CheckOnly: no process started."
    exit 0
}

New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
if ($buildLiveInput) {
    Write-Host "[moex] Building live shock input: $python $($liveArgs -join ' ')"
    Set-Location $repoRoot
    & $python @liveArgs
    if ($LASTEXITCODE -ne 0) {
        throw "build_live_shock_input.py failed with exit code $LASTEXITCODE"
    }
    if (-not (Test-Path $liveInputCsvAbs)) {
        throw "Live shock input was not created: $liveInputCsvAbs"
    }
}
Set-Location $repoRoot
& $python @argsList
exit $LASTEXITCODE
