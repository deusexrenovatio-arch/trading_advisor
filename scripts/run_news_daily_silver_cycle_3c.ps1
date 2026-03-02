param(
    [string]$Config = "configs/default.yaml",
    [string]$Date = "",
    [string]$Horizon = "1h",
    [int]$FreshDays = 2,
    [int]$FreshChunkDays = 1,
    [int]$FreshMaxWindows = 40,
    [string]$BacklogFromDate = "",
    [int]$BacklogChunkDays = 30,
    [int]$BacklogMaxWindows = 1,
    [switch]$RunInference,
    [switch]$UseMidpoint,
    [double]$MinModelConfidence = 0.40,
    [switch]$AllowModelDisagreement,
    [switch]$AllowTargetMismatch,
    [switch]$AllowNoModelScores,
    [switch]$IncludeOverlap,
    [string]$V2Selector = "hybrid",
    [double]$V2MinTargetConfidence = 0.20,
    [int]$V2MinImpactBin = 0,
    [double]$V2MinAbsZ = 0.60,
    [double]$V2MinAbsAr = 0.0002,
    [string]$SourceV2 = "auto_target_v2",
    [string]$QualityV2 = "silver",
    [string]$LabelSchemaVersion = "v2"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Path $PSScriptRoot -Parent
$symbols = @("NG_US", "BRN", "GOLD")

$env:PYTHONPATH = Join-Path $repoRoot "src"

foreach ($symbol in $symbols) {
    $args = @(
        "-m", "moex_carry.cli",
        "news_daily_silver_cycle",
        "--config", $Config,
        "--symbol", $symbol,
        "--horizon", $Horizon,
        "--fresh-days", $FreshDays,
        "--fresh-chunk-days", $FreshChunkDays,
        "--fresh-max-windows", $FreshMaxWindows,
        "--backlog-chunk-days", $BacklogChunkDays,
        "--backlog-max-windows", $BacklogMaxWindows,
        "--min-model-confidence", $MinModelConfidence,
        "--v2-selector", $V2Selector,
        "--v2-min-target-confidence", $V2MinTargetConfidence,
        "--v2-min-impact-bin", $V2MinImpactBin,
        "--v2-min-abs-z", $V2MinAbsZ,
        "--v2-min-abs-ar", $V2MinAbsAr,
        "--source-v2", $SourceV2,
        "--quality-v2", $QualityV2,
        "--label-schema-version", $LabelSchemaVersion
    )

    if ($Date -ne "") {
        $args += @("--date", $Date)
    }
    if ($BacklogFromDate -ne "") {
        $args += @("--backlog-from-date", $BacklogFromDate)
    }
    if ($RunInference.IsPresent) {
        $args += "--run-inference"
    }
    if ($UseMidpoint.IsPresent) {
        $args += "--use-midpoint"
    }
    if ($AllowModelDisagreement.IsPresent) {
        $args += "--allow-model-disagreement"
    }
    if ($AllowTargetMismatch.IsPresent) {
        $args += "--allow-target-mismatch"
    }
    if ($AllowNoModelScores.IsPresent) {
        $args += "--allow-no-model-scores"
    }
    if ($IncludeOverlap.IsPresent) {
        $args += "--include-overlap"
    }

    Write-Host ("[news_daily_silver_cycle_3c] symbol={0} horizon={1}" -f $symbol, $Horizon)
    python @args
}

Write-Host "[news_daily_silver_cycle_3c] done"
