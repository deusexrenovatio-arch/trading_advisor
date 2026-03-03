[CmdletBinding()]
param(
    [ValidateSet("Install", "Status", "Run", "Remove")]
    [string]$Action = "Status",
    [string]$TaskName = "MoexCarry-ShockLabelCycleDaily",
    [string]$StartTime = "09:10",
    [ValidateSet("Daily", "Repeat")]
    [string]$ScheduleMode = "Daily",
    [int]$RepeatMinutes = 0,
    [int]$RepeatDurationHours = 24,
    [string]$RunAs = "",
    [string]$PowerShellExe = "",
    [string]$InputCsv = "data/output/news_perf_365d_5m_opt/shock_news_1h_annual_all.csv",
    [string]$OutputRoot = "data/output/shock_label_cycle_auto",
    [string]$StartTs = "",
    [string]$EndTs = "",
    [int]$FreshLookbackHours = 0,
    [double]$MinAbsZ = 2.5,
    [double]$MaxDelayMin = 60.0,
    [int]$MaxTasksPerDaySymbol = 20,
    [int]$DirectionMaxTasks = 300,
    [int]$CausalMaxTasks = 900,
    [string]$DirectionCandidateSources = "v2_clean",
    [string]$CausalCandidateSources = "broad,none",
    [double]$IngestMinConfidence = 0.60,
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
    [switch]$NoLocalEnv,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $PowerShellExe) {
    $PowerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
}
if ([string]::IsNullOrWhiteSpace($RunAs)) {
    $RunAs = $env:USERNAME
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$startScript = Join-Path $PSScriptRoot "start_shock_label_cycle.ps1"
if (-not (Test-Path $startScript)) {
    throw "Missing script: $startScript"
}

function Get-TaskOrNull {
    param([string]$Name)
    try {
        return Get-ScheduledTask -TaskName $Name -ErrorAction Stop
    }
    catch {
        return $null
    }
}

function Build-TaskArguments {
    param()

    $parts = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$startScript`"",
        "-InputCsv", "`"$InputCsv`"",
        "-OutputRoot", "`"$OutputRoot`"",
        "-MinAbsZ", "$MinAbsZ",
        "-MaxDelayMin", "$MaxDelayMin",
        "-MaxTasksPerDaySymbol", "$MaxTasksPerDaySymbol",
        "-DirectionMaxTasks", "$DirectionMaxTasks",
        "-CausalMaxTasks", "$CausalMaxTasks",
        "-DirectionCandidateSources", "`"$DirectionCandidateSources`"",
        "-CausalCandidateSources", "`"$CausalCandidateSources`"",
        "-IngestMinConfidence", "$IngestMinConfidence",
        "-TelegramFeedPath", "`"$TelegramFeedPath`"",
        "-TelegramFeedMinAbsZ", "$TelegramFeedMinAbsZ",
        "-TelegramFeedMaxRows", "$TelegramFeedMaxRows",
        "-PrimaryZ", "$PrimaryZ",
        "-AftershockZ", "$AftershockZ",
        "-EpisodeWindowMin", "$EpisodeWindowMin",
        "-MaxGapMin", "$MaxGapMin"
    )

    if (-not [string]::IsNullOrWhiteSpace($StartTs)) {
        $parts += @("-StartTs", "`"$StartTs`"")
    }
    if (-not [string]::IsNullOrWhiteSpace($EndTs)) {
        $parts += @("-EndTs", "`"$EndTs`"")
    }
    if ($FreshLookbackHours -gt 0 -and [string]::IsNullOrWhiteSpace($StartTs)) {
        $parts += @("-FreshLookbackHours", "$FreshLookbackHours")
    }
    if (-not [string]::IsNullOrWhiteSpace($DirectionLabelsJsonl)) {
        $parts += @("-DirectionLabelsJsonl", "`"$DirectionLabelsJsonl`"")
    }
    if (-not [string]::IsNullOrWhiteSpace($CausalLabelsJsonl)) {
        $parts += @("-CausalLabelsJsonl", "`"$CausalLabelsJsonl`"")
    }
    if ($NoTelegramFeed) {
        $parts += "-NoTelegramFeed"
    }
    if ($RunReadiness) {
        $parts += "-RunReadiness"
    }
    if ($NoLocalEnv) {
        $parts += "-NoLocalEnv"
    }

    return ($parts -join " ")
}

function New-ShockTaskTrigger {
    param(
        [string]$Mode,
        [string]$AtTime,
        [int]$EveryMinutes,
        [int]$DurationHours
    )

    if ($Mode -eq "Repeat" -or $EveryMinutes -gt 0) {
        $intervalMinutes = [Math]::Max($EveryMinutes, 1)
        $durationHoursSafe = [Math]::Max($DurationHours, 1)
        if ($durationHoursSafe * 60 -lt $intervalMinutes) {
            throw "RepeatDurationHours must be >= RepeatMinutes/60."
        }

        $parts = $AtTime.Split(":")
        if ($parts.Count -ne 2) {
            throw "Invalid StartTime format: '$AtTime'. Use HH:mm."
        }
        $hour = [int]$parts[0]
        $minute = [int]$parts[1]
        if ($hour -lt 0 -or $hour -gt 23 -or $minute -lt 0 -or $minute -gt 59) {
            throw "Invalid StartTime value: '$AtTime'. Use HH:mm."
        }

        $now = Get-Date
        $startAt = Get-Date -Year $now.Year -Month $now.Month -Day $now.Day -Hour $hour -Minute $minute -Second 0
        if ($startAt -le $now) {
            $startAt = $startAt.AddDays(1)
        }

        return New-ScheduledTaskTrigger `
            -Once `
            -At $startAt `
            -RepetitionInterval (New-TimeSpan -Minutes $intervalMinutes) `
            -RepetitionDuration (New-TimeSpan -Hours $durationHoursSafe)
    }

    return New-ScheduledTaskTrigger -Daily -At $AtTime
}

switch ($Action) {
    "Status" {
        $task = Get-TaskOrNull -Name $TaskName
        if ($null -eq $task) {
            Write-Host "[moex] Task not found: $TaskName"
            exit 0
        }
        Get-ScheduledTask -TaskName $TaskName | Format-List TaskName, State, Actions, Triggers, Principal
        exit 0
    }

    "Run" {
        $task = Get-TaskOrNull -Name $TaskName
        if ($null -eq $task) {
            throw "Task not found: $TaskName"
        }
        Write-Host "[moex] Starting task: $TaskName"
        if ($DryRun) {
            Write-Host "[moex] DryRun enabled: task was not started."
            exit 0
        }
        Start-ScheduledTask -TaskName $TaskName
        exit 0
    }

    "Remove" {
        $task = Get-TaskOrNull -Name $TaskName
        if ($null -eq $task) {
            Write-Host "[moex] Task not found: $TaskName"
            exit 0
        }
        Write-Host "[moex] Removing task: $TaskName"
        if ($DryRun) {
            Write-Host "[moex] DryRun enabled: task was not removed."
            exit 0
        }
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "[moex] Removed: $TaskName"
        exit 0
    }

    "Install" {
        $taskArguments = Build-TaskArguments
        $taskAction = New-ScheduledTaskAction -Execute $PowerShellExe -Argument $taskArguments
        $taskTrigger = New-ShockTaskTrigger `
            -Mode $ScheduleMode `
            -AtTime $StartTime `
            -EveryMinutes $RepeatMinutes `
            -DurationHours $RepeatDurationHours
        $taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

        if ($RunAs.Trim().ToUpperInvariant() -eq "SYSTEM") {
            $taskPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
        }
        else {
            $taskPrincipal = New-ScheduledTaskPrincipal -UserId $RunAs -LogonType Interactive -RunLevel Limited
        }

        Write-Host "[moex] RepoRoot: $repoRoot"
        Write-Host "[moex] TaskName: $TaskName"
        if ($ScheduleMode -eq "Repeat" -or $RepeatMinutes -gt 0) {
            Write-Host "[moex] Schedule: repeat every $([Math]::Max($RepeatMinutes,1))m from $StartTime (duration ${RepeatDurationHours}h)"
        }
        else {
            Write-Host "[moex] Schedule: daily at $StartTime"
        }
        Write-Host "[moex] RunAs: $RunAs"
        Write-Host "[moex] Command: $PowerShellExe $taskArguments"

        if ($DryRun) {
            Write-Host "[moex] DryRun enabled: task was not installed."
            exit 0
        }

        Register-ScheduledTask `
            -TaskName $TaskName `
            -Action $taskAction `
            -Trigger $taskTrigger `
            -Principal $taskPrincipal `
            -Settings $taskSettings `
            -Force | Out-Null

        Write-Host "[moex] Installed: $TaskName"
        Get-ScheduledTask -TaskName $TaskName | Format-List TaskName, State, Actions, Triggers, Principal
        exit 0
    }
}
