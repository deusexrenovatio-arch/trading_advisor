[CmdletBinding()]
param(
    [ValidateSet("Install", "Status", "RunLive", "RunBackfill", "Remove")]
    [string]$Action = "Status",
    [string]$LiveTaskName = "MoexCarry-NewsRootLive",
    [string]$BackfillTaskName = "MoexCarry-NewsRootBackfill",
    [string]$LiveStartTime = "06:00",
    [int]$LiveEveryMinutes = 5,
    [string]$BackfillStartTime = "03:15",
    [string]$NewsConfig = "configs/news-livecheck-ng.yaml",
    [int]$LiveLookbackHours = 6,
    [int]$BackfillLookbackHours = 24,
    [int]$BarMinutes = 5,
    [double]$MinAbsZ = 2.0,
    [double]$RootMinFundamentalScore = 0.45,
    [double]$RootMinCauseConfidence = 0.45,
    [double]$AftershockMaxGapMin = 2880.0,
    [switch]$EnableCandidateNewsApiEnrichment,
    [int]$EnrichmentWindowMin = 90,
    [int]$EnrichmentMaxRequestsPerSymbol = 4,
    [switch]$NoRootMaintenance,
    [string]$RunAs = "",
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$startScript = Join-Path $PSScriptRoot "start_news_root_cycle.ps1"
if (-not (Test-Path $startScript)) {
    throw "Missing script: $startScript"
}
$powerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if ([string]::IsNullOrWhiteSpace($RunAs)) {
    $RunAs = $env:USERNAME
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

function Install-RootTask {
    param(
        [string]$TaskName,
        [string]$Mode,
        [string]$StartTime,
        [string]$ScheduleMode,
        [int]$RepeatMinutes,
        [int]$LookbackHours
    )

    $arguments = @(
        "-NoProfile",
        "-WindowStyle", "Hidden",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$startScript`"",
        "-Mode", $Mode,
        "-NewsConfig", "`"$NewsConfig`"",
        "-LookbackHours", [string]$LookbackHours,
        "-BarMinutes", [string]$BarMinutes,
        "-MinAbsZ", [string]$MinAbsZ,
        "-RootMinFundamentalScore", [string]$RootMinFundamentalScore,
        "-RootMinCauseConfidence", [string]$RootMinCauseConfidence,
        "-AftershockMaxGapMin", [string]$AftershockMaxGapMin,
        "-EnrichmentWindowMin", [string]$EnrichmentWindowMin,
        "-EnrichmentMaxRequestsPerSymbol", [string]$EnrichmentMaxRequestsPerSymbol
    )
    if ($EnableCandidateNewsApiEnrichment) {
        $arguments += "-EnableCandidateNewsApiEnrichment"
    }
    if ($NoRootMaintenance) {
        $arguments += "-NoRootMaintenance"
    }
    $taskAction = New-ScheduledTaskAction -Execute $powerShellExe -Argument ($arguments -join " ")
    if ($ScheduleMode -eq "Repeat") {
        $parts = $StartTime.Split(":")
        if ($parts.Count -ne 2) {
            throw "Invalid StartTime: $StartTime"
        }
        $hour = [int]$parts[0]
        $minute = [int]$parts[1]
        $now = Get-Date
        $startAt = Get-Date -Year $now.Year -Month $now.Month -Day $now.Day -Hour $hour -Minute $minute -Second 0
        if ($startAt -le $now) {
            $startAt = $startAt.AddDays(1)
        }
        $trigger = New-ScheduledTaskTrigger `
            -Once `
            -At $startAt `
            -RepetitionInterval (New-TimeSpan -Minutes ([Math]::Max($RepeatMinutes, 1))) `
            -RepetitionDuration (New-TimeSpan -Hours 24)
    }
    else {
        $trigger = New-ScheduledTaskTrigger -Daily -At $StartTime
    }
    if ($RunAs.Trim().ToUpperInvariant() -eq "SYSTEM") {
        $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    }
    else {
        $principal = New-ScheduledTaskPrincipal -UserId $RunAs -LogonType Interactive -RunLevel Limited
    }
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew
    Write-Host "[moex] Install task '$TaskName' mode=$Mode schedule=$ScheduleMode start=$StartTime"
    Write-Host "[moex] Command: $powerShellExe $($arguments -join ' ')"
    if ($DryRun) {
        return
    }
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $taskAction `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Force | Out-Null
}

switch ($Action) {
    "Status" {
        foreach ($taskName in @($LiveTaskName, $BackfillTaskName)) {
            $task = Get-TaskOrNull -Name $taskName
            if ($null -eq $task) {
                Write-Host "[moex] Task not found: $taskName"
            }
            else {
                Get-ScheduledTask -TaskName $taskName | Format-List TaskName, State, Actions, Triggers, Principal
            }
        }
    }
    "RunLive" {
        if ($DryRun) {
            Write-Host "[moex] DryRun: skip Start-ScheduledTask $LiveTaskName"
        }
        else {
            Start-ScheduledTask -TaskName $LiveTaskName
        }
    }
    "RunBackfill" {
        if ($DryRun) {
            Write-Host "[moex] DryRun: skip Start-ScheduledTask $BackfillTaskName"
        }
        else {
            Start-ScheduledTask -TaskName $BackfillTaskName
        }
    }
    "Remove" {
        if ($DryRun) {
            Write-Host "[moex] DryRun: skip remove tasks"
        }
        else {
            if (Get-TaskOrNull -Name $LiveTaskName) {
                Unregister-ScheduledTask -TaskName $LiveTaskName -Confirm:$false
            }
            if (Get-TaskOrNull -Name $BackfillTaskName) {
                Unregister-ScheduledTask -TaskName $BackfillTaskName -Confirm:$false
            }
        }
    }
    "Install" {
        Install-RootTask `
            -TaskName $LiveTaskName `
            -Mode "live" `
            -StartTime $LiveStartTime `
            -ScheduleMode "Repeat" `
            -RepeatMinutes $LiveEveryMinutes `
            -LookbackHours $LiveLookbackHours
        Install-RootTask `
            -TaskName $BackfillTaskName `
            -Mode "backfill" `
            -StartTime $BackfillStartTime `
            -ScheduleMode "Daily" `
            -RepeatMinutes 0 `
            -LookbackHours $BackfillLookbackHours
    }
}
