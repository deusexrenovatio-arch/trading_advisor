[CmdletBinding()]
param(
    [ValidateSet("Install", "Status", "RunLive", "RunBackfill", "Remove")]
    [string]$Action = "Status",
    [string]$LiveTaskName = "MoexCarry-NewsIngestLive",
    [string]$BackfillTaskName = "MoexCarry-NewsIngestBackfill",
    [string]$LiveStartTime = "06:00",
    [int]$LiveEveryMinutes = 5,
    [string]$BackfillStartTime = "03:15",
    [string]$NewsConfig = "configs/news-livecheck-ng.yaml",
    [string]$RunAs = "",
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$startScript = Join-Path $PSScriptRoot "start_news_ingest_cycle.ps1"
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

function Invoke-TaskScript {
    param(
        [string]$ScriptAction,
        [string]$TaskName
    )
    & $powerShellExe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "manage_shock_label_cycle_task.ps1") `
        -Action $ScriptAction `
        -TaskName $TaskName
}

function Install-NewsTask {
    param(
        [string]$TaskName,
        [string]$Mode,
        [string]$StartTime,
        [string]$ScheduleMode,
        [int]$RepeatMinutes
    )
    $arguments = @(
        "-NoProfile",
        "-WindowStyle", "Hidden",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$startScript`"",
        "-Mode", $Mode,
        "-NewsConfig", "`"$NewsConfig`""
    ) -join " "
    $taskAction = New-ScheduledTaskAction -Execute $powerShellExe -Argument $arguments
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
            -RepetitionInterval (New-TimeSpan -Minutes ([Math]::Max($RepeatMinutes,1))) `
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
    Write-Host "[moex] Install task '$TaskName' mode=$Mode schedule=$ScheduleMode start=$StartTime repeat=$RepeatMinutes"
    Write-Host "[moex] Command: $powerShellExe $arguments"
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
        $liveTask = Get-TaskOrNull -Name $LiveTaskName
        if ($null -eq $liveTask) {
            Write-Host "[moex] Task not found: $LiveTaskName"
        }
        else {
            Get-ScheduledTask -TaskName $LiveTaskName | Format-List TaskName, State, Actions, Triggers, Principal
        }
        $backfillTask = Get-TaskOrNull -Name $BackfillTaskName
        if ($null -eq $backfillTask) {
            Write-Host "[moex] Task not found: $BackfillTaskName"
        }
        else {
            Get-ScheduledTask -TaskName $BackfillTaskName | Format-List TaskName, State, Actions, Triggers, Principal
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
        Install-NewsTask `
            -TaskName $LiveTaskName `
            -Mode "live" `
            -StartTime $LiveStartTime `
            -ScheduleMode "Repeat" `
            -RepeatMinutes $LiveEveryMinutes
        Install-NewsTask `
            -TaskName $BackfillTaskName `
            -Mode "backfill" `
            -StartTime $BackfillStartTime `
            -ScheduleMode "Daily" `
            -RepeatMinutes 0
    }
}
