[CmdletBinding()]
param(
    [string]$ConfigPath = "configs/default.yaml",
    [string]$LogLevel = "INFO",
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

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$configAbsolute = if ([System.IO.Path]::IsPathRooted($ConfigPath)) {
    $ConfigPath
}
else {
    Join-Path $repoRoot $ConfigPath
}
$localEnvPath = Join-Path $PSScriptRoot "moex-carry.local.ps1"
$python = Resolve-PythonExecutable -Requested $PythonExe

if ((-not $NoLocalEnv) -and (Test-Path $localEnvPath)) {
    . $localEnvPath
}

$env:PYTHONPATH = Join-Path $repoRoot "src"

Write-Host "[moex] RepoRoot: $repoRoot"
Write-Host "[moex] Config: $configAbsolute"
Write-Host "[moex] Python: $python"
Write-Host "[moex] LogLevel: $LogLevel"

if ($CheckOnly) {
    Write-Host "[moex] CheckOnly: no process started."
    exit 0
}

Set-Location $repoRoot
& $python -m moex_carry.cli server --config $configAbsolute --log-level $LogLevel
exit $LASTEXITCODE
