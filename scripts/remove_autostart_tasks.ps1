[CmdletBinding()]
param(
    [string]$TaskPrefix = "MoexCarry",
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Remove-TaskIfExists {
    param([string]$TaskName)

    cmd.exe /c "schtasks /Query /TN `"$TaskName`" >NUL 2>NUL" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[moex] Task not found: $TaskName"
        return
    }

    $deleteArgs = @("/Delete", "/F", "/TN", $TaskName)
    Write-Host "schtasks $($deleteArgs -join " ")"
    if ($DryRun) {
        return
    }
    cmd.exe /c "schtasks /Delete /F /TN `"$TaskName`""
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to delete task: $TaskName"
    }
    Write-Host "[moex] Deleted: $TaskName"
}

Remove-TaskIfExists -TaskName "$TaskPrefix-Backend"
Remove-TaskIfExists -TaskName "$TaskPrefix-TelegramWorker"
