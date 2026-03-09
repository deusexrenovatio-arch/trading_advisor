param(
    [ValidateSet("Init", "Check", "Show", "Clear")]
    [string]$Action = "Check",
    [string]$WorktreePath,
    [string]$Branch,
    [string]$ContextFile = ".worktree-context.local.json",
    [int]$ContextTtlHours = 12,
    [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-AbsolutePath {
    param([string]$PathValue)
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return $null
    }
    try {
        return [System.IO.Path]::GetFullPath($PathValue)
    } catch {
        return $null
    }
}

function Get-RepoRoot {
    try {
        $root = (git rev-parse --show-toplevel 2>$null)
    } catch {
        $root = $null
    }
    if ([string]::IsNullOrWhiteSpace($root)) {
        throw "Not inside a git repository."
    }
    $resolved = Resolve-AbsolutePath -PathValue $root.Trim()
    if (-not $resolved) {
        throw "Unable to resolve repository root path."
    }
    return $resolved
}

function Get-CurrentBranch {
    try {
        $name = (git branch --show-current 2>$null)
    } catch {
        $name = $null
    }
    if ([string]::IsNullOrWhiteSpace($name)) {
        return "<detached>"
    }
    return $name.Trim()
}

function Invoke-ContextRouterHint {
    param(
        [string]$RepoRootPath,
        [switch]$QuietMode
    )
    if ($QuietMode) {
        return
    }
    if ($env:MOEX_CARRY_SKIP_CONTEXT_ROUTER -eq "1") {
        return
    }

    $routerPath = Join-Path $RepoRootPath "scripts/context_router.py"
    if (-not (Test-Path -LiteralPath $routerPath)) {
        return
    }

    $pythonExe = "python"
    if (-not [string]::IsNullOrWhiteSpace($env:PYTHON)) {
        $pythonExe = $env:PYTHON.Trim()
    }

    try {
        $routerArgs = @(
            $routerPath,
            "--from-git",
            "--format",
            "text",
            "--session-handoff-path",
            (Join-Path $RepoRootPath "docs/session_handoff.md")
        )
        if (-not [string]::IsNullOrWhiteSpace($env:MOEX_CARRY_CONTEXT_ROUTER_REQUEST)) {
            $routerArgs += @("--request", $env:MOEX_CARRY_CONTEXT_ROUTER_REQUEST.Trim())
        }
        if (-not [string]::IsNullOrWhiteSpace($env:MOEX_CARRY_CONTEXT_ROUTER_TARGET_MODULES)) {
            foreach ($targetModule in $env:MOEX_CARRY_CONTEXT_ROUTER_TARGET_MODULES.Split(",")) {
                $trimmed = $targetModule.Trim()
                if (-not [string]::IsNullOrWhiteSpace($trimmed)) {
                    $routerArgs += @("--target-module", $trimmed)
                }
            }
        }

        $routerOutput = & $pythonExe @routerArgs 2>$null
        $routerExitCode = $LASTEXITCODE
        if ($routerExitCode -ne 0) {
            Write-Host "context_router: skipped (exit_code=$routerExitCode)"
            return
        }
        if ($null -eq $routerOutput) {
            return
        }

        $lines = @()
        foreach ($line in $routerOutput) {
            $text = [string]$line
            if (-not [string]::IsNullOrWhiteSpace($text)) {
                $lines += $text
            }
        }
        if ($lines.Count -eq 0) {
            return
        }

        Write-Host "context_router: start-of-work context"
        foreach ($textLine in $lines) {
            Write-Host "  $textLine"
        }
    } catch {
        Write-Host "context_router: skipped (python/context_router unavailable)"
    }
}

function Invoke-AgentProcessTelemetryStart {
    param(
        [string]$RepoRootPath,
        [switch]$QuietMode
    )
    if ($QuietMode) {
        return
    }
    $telemetryPath = Join-Path $RepoRootPath "scripts/agent_process_telemetry.py"
    if (-not (Test-Path -LiteralPath $telemetryPath)) {
        return
    }
    $pythonExe = "python"
    if (-not [string]::IsNullOrWhiteSpace($env:PYTHON)) {
        $pythonExe = $env:PYTHON.Trim()
    }
    try {
        $telemetryOutput = & $pythonExe $telemetryPath "start" "--session-handoff-path" (Join-Path $RepoRootPath "docs/session_handoff.md") 2>&1
        $telemetryExitCode = $LASTEXITCODE
        if ($telemetryExitCode -ne 0) {
            Write-Host "agent_process_telemetry: start failed (exit_code=$telemetryExitCode)"
            foreach ($line in $telemetryOutput) {
                $text = [string]$line
                if (-not [string]::IsNullOrWhiteSpace($text)) {
                    Write-Host "  $text"
                }
            }
            return
        }
        foreach ($line in $telemetryOutput) {
            $text = [string]$line
            if (-not [string]::IsNullOrWhiteSpace($text)) {
                Write-Host $text
            }
        }
    } catch {
        Write-Host "agent_process_telemetry: skipped (python/telemetry unavailable)"
    }
}

function Read-Context {
    param([string]$PathValue)
    if (-not (Test-Path -LiteralPath $PathValue)) {
        return $null
    }
    $raw = Get-Content -LiteralPath $PathValue -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $null
    }
    return ($raw | ConvertFrom-Json)
}

function Write-Context {
    param(
        [string]$PathValue,
        [string]$ExpectedWorktree,
        [string]$ExpectedBranch,
        [int]$TtlHours
    )
    $ttl = [Math]::Max($TtlHours, 1)
    $setAt = [DateTime]::UtcNow
    $payload = [ordered]@{
        version          = 1
        expected_worktree = $ExpectedWorktree
        expected_branch   = $ExpectedBranch
        set_at_utc       = $setAt.ToString("o")
        valid_until_utc  = $setAt.AddHours($ttl).ToString("o")
        ttl_hours        = $ttl
    }
    $json = $payload | ConvertTo-Json -Depth 4
    Set-Content -LiteralPath $PathValue -Encoding UTF8 -Value $json
}

$repoRoot = Get-RepoRoot
$contextPath = Resolve-AbsolutePath -PathValue (Join-Path $repoRoot $ContextFile)
$currentWorktree = $repoRoot
$currentBranch = Get-CurrentBranch

switch ($Action) {
    "Init" {
        $expectedWorktree = Resolve-AbsolutePath -PathValue ($(if ($WorktreePath) { $WorktreePath } else { $currentWorktree }))
        if (-not $expectedWorktree) {
            throw "Unable to resolve expected worktree path."
        }
        $expectedBranch = if ($Branch) { $Branch.Trim() } else { $currentBranch }
        if ([string]::IsNullOrWhiteSpace($expectedBranch)) {
            throw "Expected branch is empty."
        }

        Write-Context -PathValue $contextPath -ExpectedWorktree $expectedWorktree -ExpectedBranch $expectedBranch -TtlHours $ContextTtlHours
        if (-not $Quiet) {
            Write-Host "worktree_guard: initialized"
            Write-Host "  context_file: $contextPath"
            Write-Host "  expected_worktree: $expectedWorktree"
            Write-Host "  expected_branch: $expectedBranch"
            Write-Host "  ttl_hours: $([Math]::Max($ContextTtlHours, 1))"
        }
        exit 0
    }
    "Show" {
        $ctx = Read-Context -PathValue $contextPath
        Write-Host "worktree_guard: status"
        Write-Host "  context_file: $contextPath"
        Write-Host "  current_worktree: $currentWorktree"
        Write-Host "  current_branch: $currentBranch"
        if ($null -eq $ctx) {
            Write-Host "  expected_worktree: <not set>"
            Write-Host "  expected_branch: <not set>"
            exit 0
        }
        Write-Host "  expected_worktree: $($ctx.expected_worktree)"
        Write-Host "  expected_branch: $($ctx.expected_branch)"
        Write-Host "  set_at_utc: $($ctx.set_at_utc)"
        Write-Host "  valid_until_utc: $($ctx.valid_until_utc)"
        Write-Host "  ttl_hours: $($ctx.ttl_hours)"
        exit 0
    }
    "Clear" {
        if (Test-Path -LiteralPath $contextPath) {
            Remove-Item -LiteralPath $contextPath -Force
            if (-not $Quiet) {
                Write-Host "worktree_guard: cleared context file $contextPath"
            }
        } elseif (-not $Quiet) {
            Write-Host "worktree_guard: context file not found ($contextPath)"
        }
        exit 0
    }
    "Check" {
        $ctx = Read-Context -PathValue $contextPath
        if ($null -eq $ctx) {
            Write-Error "worktree_guard: context is not set. Run: ./scripts/worktree_guard.ps1 -Action Init -WorktreePath `"<path>`" -Branch `"<branch>`""
            exit 2
        }

        $expectedWorktree = Resolve-AbsolutePath -PathValue ([string]$ctx.expected_worktree)
        $expectedBranch = ([string]$ctx.expected_branch).Trim()
        if (-not $expectedWorktree -or [string]::IsNullOrWhiteSpace($expectedBranch)) {
            Write-Error "worktree_guard: context file is invalid. Re-initialize it."
            exit 2
        }
        $validUntilRaw = [string]$ctx.valid_until_utc
        if ([string]::IsNullOrWhiteSpace($validUntilRaw)) {
            Write-Error "worktree_guard: context TTL is missing. Re-initialize context."
            exit 2
        }
        try {
            $validUntil = [DateTime]::Parse($validUntilRaw).ToUniversalTime()
        } catch {
            Write-Error "worktree_guard: invalid context TTL format. Re-initialize context."
            exit 2
        }
        if ([DateTime]::UtcNow -gt $validUntil) {
            Write-Error "worktree_guard: context expired at $validUntilRaw. Re-run Init for current session."
            exit 2
        }

        $okPath = $currentWorktree.ToLowerInvariant() -eq $expectedWorktree.ToLowerInvariant()
        $okBranch = $currentBranch -eq $expectedBranch

        if ($okPath -and $okBranch) {
            if (-not $Quiet) {
                Write-Host "worktree_guard: OK"
                Write-Host "  worktree: $currentWorktree"
                Write-Host "  branch: $currentBranch"
            }
            Invoke-ContextRouterHint -RepoRootPath $repoRoot -QuietMode:$Quiet
            Invoke-AgentProcessTelemetryStart -RepoRootPath $repoRoot -QuietMode:$Quiet
            exit 0
        }

        Write-Error "worktree_guard: mismatch detected."
        Write-Host "  expected_worktree: $expectedWorktree"
        Write-Host "  expected_branch: $expectedBranch"
        Write-Host "  current_worktree: $currentWorktree"
        Write-Host "  current_branch: $currentBranch"
        exit 3
    }
}
