[CmdletBinding()]
param(
    [ValidateSet("Install", "Status", "RunFresh", "RunBackfill", "Remove")]
    [string]$Action = "Status",
    [string]$FreshTaskName = "MoexCarry-ShockLabelCycleFresh",
    [string]$BackfillTaskName = "MoexCarry-ShockLabelCycleBackfill",
    [string]$FreshStartTime = "06:00",
    [int]$FreshEveryMinutes = 30,
    [int]$FreshLookbackHours = 6,
    [string]$BackfillStartTime = "03:40",
    [int]$FreshDirectionMaxTasks = 80,
    [int]$FreshCausalMaxTasks = 200,
    [int]$BackfillDirectionMaxTasks = 300,
    [int]$BackfillCausalMaxTasks = 900,
    [string]$ShockBackfillStartTs = "2025-01-01T00:00:00Z",
    [string]$ShockBackfillCursorKey = "shock_rows_backfill_cursor_utc",
    [int]$BackfillShockWindowHours = 24,
    [int]$BackfillShockWindowsPerRun = 8,
    [int]$NewsApiDailyQuota = 100,
    [int]$NewsApiRealtimeBudget = 55,
    [int]$NewsApiBackfillBudget = 35,
    [int]$NewsApiEmergencyBuffer = 10,
    [double]$NewsApiFreshRequestsPerRunEstimate = 1.0,
    [double]$NewsApiBackfillRequestsPerRunEstimate = 20.0,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$manageScript = Join-Path $PSScriptRoot "manage_shock_label_cycle_task.ps1"
if (-not (Test-Path $manageScript)) {
    throw "Missing script: $manageScript"
}
$powerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

$budgetSum = $NewsApiRealtimeBudget + $NewsApiBackfillBudget + $NewsApiEmergencyBuffer
if ($budgetSum -gt $NewsApiDailyQuota) {
    throw "NewsAPI budgets exceed quota: $budgetSum > $NewsApiDailyQuota"
}

$freshRunsPerDay = [Math]::Floor((24.0 * 60.0) / [Math]::Max($FreshEveryMinutes, 1))
$freshEstimated = [Math]::Round($freshRunsPerDay * $NewsApiFreshRequestsPerRunEstimate, 2)
$backfillEstimated = [Math]::Round($NewsApiBackfillRequestsPerRunEstimate, 2)

Write-Host "[moex] NewsAPI budget plan"
Write-Host ("[moex] quota={0} realtime={1} backfill={2} emergency={3}" -f `
    $NewsApiDailyQuota, $NewsApiRealtimeBudget, $NewsApiBackfillBudget, $NewsApiEmergencyBuffer)
Write-Host ("[moex] estimated usage: fresh={0} req/day, backfill={1} req/day" -f `
    $freshEstimated, $backfillEstimated)
if ($freshEstimated -gt $NewsApiRealtimeBudget) {
    Write-Warning ("[moex] Fresh schedule may exceed realtime budget: {0} > {1}" -f `
        $freshEstimated, $NewsApiRealtimeBudget)
}
if ($backfillEstimated -gt $NewsApiBackfillBudget) {
    Write-Warning ("[moex] Backfill estimate may exceed backfill budget: {0} > {1}" -f `
        $backfillEstimated, $NewsApiBackfillBudget)
}

function Invoke-ManageTask {
    param([hashtable]$TaskParams)
    $argsList = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $manageScript
    )
    foreach ($entry in $TaskParams.GetEnumerator()) {
        $key = [string]$entry.Key
        $value = $entry.Value
        if ($value -is [System.Management.Automation.SwitchParameter]) {
            if ($value.IsPresent) {
                $argsList += "-$key"
            }
            continue
        }
        if ($value -is [bool]) {
            if ($value) {
                $argsList += "-$key"
            }
            continue
        }
        if ($null -eq $value) {
            continue
        }
        $text = [string]$value
        if ([string]::IsNullOrWhiteSpace($text)) {
            continue
        }
        $argsList += "-$key"
        $argsList += $text
    }
    & $powerShellExe @argsList
    if ($LASTEXITCODE -ne 0) {
        throw "manage_shock_label_cycle_task.ps1 failed for Action=$($TaskParams['Action']) TaskName=$($TaskParams['TaskName'])"
    }
}

switch ($Action) {
    "Status" {
        Invoke-ManageTask @{
            Action = "Status"
            TaskName = $FreshTaskName
        }
        Invoke-ManageTask @{
            Action = "Status"
            TaskName = $BackfillTaskName
        }
        exit 0
    }
    "RunFresh" {
        Invoke-ManageTask @{
            Action = "Run"
            TaskName = $FreshTaskName
            DryRun = $DryRun
        }
        exit 0
    }
    "RunBackfill" {
        Invoke-ManageTask @{
            Action = "Run"
            TaskName = $BackfillTaskName
            DryRun = $DryRun
        }
        exit 0
    }
    "Remove" {
        Invoke-ManageTask @{
            Action = "Remove"
            TaskName = $FreshTaskName
            DryRun = $DryRun
        }
        Invoke-ManageTask @{
            Action = "Remove"
            TaskName = $BackfillTaskName
            DryRun = $DryRun
        }
        exit 0
    }
    "Install" {
        # Fresh cycle: frequent, narrow window, produces Telegram feed.
        Invoke-ManageTask @{
            Action = "Install"
            TaskName = $FreshTaskName
            StartTime = $FreshStartTime
            ScheduleMode = "Repeat"
            RepeatMinutes = $FreshEveryMinutes
            RepeatDurationHours = 24
            FreshLookbackHours = $FreshLookbackHours
            DirectionMaxTasks = $FreshDirectionMaxTasks
            CausalMaxTasks = $FreshCausalMaxTasks
            DryRun = $DryRun
        }

        # Backfill cycle: daily, larger coverage, no Telegram feed overwrite.
        Invoke-ManageTask @{
            Action = "Install"
            TaskName = $BackfillTaskName
            StartTime = $BackfillStartTime
            ScheduleMode = "Daily"
            DirectionMaxTasks = $BackfillDirectionMaxTasks
            CausalMaxTasks = $BackfillCausalMaxTasks
            UseDbInput = $true
            RunShockBackfill = $true
            ShockBackfillStartTs = $ShockBackfillStartTs
            ShockBackfillCursorKey = $ShockBackfillCursorKey
            ShockBackfillWindowHours = $BackfillShockWindowHours
            ShockBackfillWindowsPerRun = $BackfillShockWindowsPerRun
            NoTelegramFeed = $true
            DryRun = $DryRun
        }
        exit 0
    }
}
