# Agent Runtime Runbook (High-Load Sessions)

## Purpose
- Prevent hard reboots and unstable behavior during parallel agent workloads.
- Define strict "do" and "do not" rules for CPU, memory, and disk pressure.

## Scope
- Applies to local sessions with parallel agent execution (especially 3-agent runs).
- Applies to long-running compute, large file processing, and mixed compute plus I/O workloads.

## Safety Rules
- Do not modify drivers, firmware, BIOS, or low-level hardware settings during agent runs.
- Do not install or update system software while heavy agent workloads are active.
- Treat any unexpected reboot or freeze as a stability incident and switch to safe mode below.

## Parallelism Policy
- Maximum heavy agents at the same time: `2`.
- A third agent is allowed only in light mode.
- Heavy mode means one or more:
  - sustained CPU-intensive compute,
  - large in-memory datasets,
  - high-frequency disk reads/writes,
  - model/index build steps.

## Start Gate (Before Launch)

| Metric | Green | Yellow | Red |
|---|---:|---:|---:|
| Memory `% Committed Bytes In Use` | `< 85%` | `85-90%` | `> 90%` |
| Memory `Available MBytes` | `> 6000` | `3000-6000` | `< 3000` |
| Paging file `% Usage` | `< 60%` | `60-80%` | `> 80%` |
| CPU `% Processor Time` (5 min avg) | `< 75%` | `75-90%` | `> 90%` |
| Disk `Avg. Disk sec/Transfer` | `< 0.020` | `0.020-0.050` | `> 0.050` |
| Disk `Current Disk Queue Length` | `< 2` | `2-4` | `> 4` |

Launch policy:
1. Start agent #1 (heavy allowed).
2. Wait 2-3 minutes and recheck metrics.
3. Start agent #2 only if all metrics are Green or at most one Yellow.
4. Start agent #3 only in light mode and only if memory and disk remain Green.

## Runtime Guardrails
- Recheck critical metrics every 60 seconds.
- Do not start new heavy tasks if any Red state is present.
- Keep workloads chunked and resumable. Prefer stream processing to full in-memory loads.
- Use bounded concurrency inside each agent.

## Cursor and Agent Process Guardrails
- Keep `.cursorignore` present and updated to exclude heavy generated paths (`.venv`, `node_modules`, logs, artifacts, cache folders).
- During compute-heavy windows, avoid concurrent repository-wide reindexing.
- Archive old chats optionally for hygiene, but do not delete recent crash-context chats until RCA is complete.
- Clean old local Cursor logs periodically (for example, entries older than 7-14 days).
- Avoid running three heavy agent sessions with active indexing and background sync at the same time.

## Stop/Replan Triggers
- `Commit > 90%` for more than 60 seconds:
  - freeze new heavy tasks,
  - reduce active heavy agents to one.
- `Commit > 95%` or memory allocation failures:
  - stop all non-critical tasks immediately,
  - leave only one recovery/control process active.
- Disk queue `> 4` for more than 2 minutes:
  - pause I/O-heavy tasks,
  - switch to staged reads/writes.
- Repeated GPU watchdog or PCIe hardware warnings:
  - stop GPU-dependent or overlay-heavy tasks,
  - keep only CPU-safe tasks until stable.

## Do
- Set explicit memory budgets per task.
- Use chunks, checkpoints, and resume points.
- Sequence heavy tasks instead of stacking them.
- Keep logging lightweight under pressure.
- Preserve crash artifacts after instability (`Minidump`, `LiveKernelReports`, `WER`).

## Do Not
- Do not run 3 heavy agents in parallel.
- Do not run installer/update jobs during heavy runs.
- Do not run optional hardware utility overlays during critical sessions.
- Do not disable pagefile or force tiny pagefile size.
- Do not combine stress testing with production-critical workloads.

## Quick Checks (PowerShell)
```powershell
Get-Counter '\Memory\% Committed Bytes In Use'
Get-Counter '\Memory\Available MBytes'
Get-Counter '\PhysicalDisk(_Total)\Current Disk Queue Length'
Get-Counter '\Processor(_Total)\% Processor Time'
```

```powershell
Get-WinEvent -FilterHashtable @{LogName='System'; Id=41; StartTime=(Get-Date).AddHours(-2)}
Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-WHEA-Logger'; StartTime=(Get-Date).AddHours(-2)}
```

## RCA Load Attribution Protocol (Mandatory)
- Goal: identify the true load source, not only the crash symptom.
- Time window: analyze at least `T-30m ... T+5m` around incident time.
- Required per-process metrics (top contributors):
  - CPU: average and p95 utilization in the window.
  - Memory: commit/private bytes peak and trend.
  - Disk: read/write MB/s and I/O spikes.
  - Faulting behavior: page-fault or hard-fault spikes if available.
- Required system-level metrics in the same window:
  - `% Committed Bytes In Use`, `Commit Limit`, pagefile usage.
  - `% Processor Time` (total) and saturation duration.
  - `Avg. Disk sec/Transfer`, queue length, and sustained red-zone intervals.
- Classification rules:
  - Primary trigger: largest direct contributor that crossed a red threshold first.
  - Amplifiers: processes/subsystems that materially increased pressure after trigger.
  - Background noise: high activity with no threshold crossing or weak temporal correlation.
- Mandatory RCA output block:
  1. Incident timeline with exact timestamps.
  2. Top-5 contributors with quantitative share (CPU/RAM/Disk).
  3. Trigger vs amplifier split with confidence level.
  4. Why total commit exceeded expectation versus single-process memory.
  5. Concrete mitigation thresholds and run profile changes.

Minimal collection commands:
```powershell
Get-WinEvent -FilterHashtable @{LogName='System'; Id=41,6008,1001; StartTime=(Get-Date).AddHours(-2)} |
  Select-Object TimeCreated, Id, ProviderName, LevelDisplayName, Message
```

```powershell
Get-Process |
  Sort-Object CPU -Descending |
  Select-Object -First 15 Name, Id, CPU, PM, WS, StartTime
```

```powershell
Get-Counter '\Memory\% Committed Bytes In Use','\Memory\Committed Bytes','\Paging File(_Total)\% Usage',
'\Processor(_Total)\% Processor Time','\PhysicalDisk(_Total)\Avg. Disk sec/Transfer','\PhysicalDisk(_Total)\Current Disk Queue Length'
```

## Incident Notes
- Recent hard reset signature can appear as `Kernel-Power 41` with `BugcheckCode=0` (hang/reset without BSOD).
- Near-limit commit pressure is a major risk multiplier for mixed compute + driver stacks.
