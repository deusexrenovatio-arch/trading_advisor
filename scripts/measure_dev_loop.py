from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class CommandSpec:
    name: str
    cmd: tuple[str, ...]


@dataclass(frozen=True)
class ProfileSpec:
    name: str
    description: str
    commands: tuple[CommandSpec, ...]


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected YAML object in {path.as_posix()}")
    return payload


def _resolve_token(value: str) -> str:
    if value == "{python}":
        return sys.executable
    return value


def _load_profiles(config_path: Path) -> dict[str, ProfileSpec]:
    payload = _load_yaml(config_path)
    raw_profiles = payload.get("profiles")
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise ValueError("Timing config is missing non-empty 'profiles' mapping")

    profiles: dict[str, ProfileSpec] = {}
    for profile_name, raw_profile in raw_profiles.items():
        if not isinstance(raw_profile, dict):
            raise ValueError(f"profile '{profile_name}' must be a mapping")
        description = str(raw_profile.get("description") or "").strip()
        raw_commands = raw_profile.get("commands")
        if not isinstance(raw_commands, list) or not raw_commands:
            raise ValueError(f"profile '{profile_name}' must define non-empty commands list")
        commands: list[CommandSpec] = []
        for idx, raw_command in enumerate(raw_commands):
            if not isinstance(raw_command, dict):
                raise ValueError(f"profile '{profile_name}' command #{idx + 1} must be a mapping")
            name = str(raw_command.get("name") or "").strip()
            cmd = raw_command.get("cmd")
            if not name:
                raise ValueError(f"profile '{profile_name}' command #{idx + 1} missing non-empty name")
            if not isinstance(cmd, list) or not cmd or not all(isinstance(part, str) for part in cmd):
                raise ValueError(
                    f"profile '{profile_name}' command '{name}' must define non-empty string cmd list"
                )
            commands.append(CommandSpec(name=name, cmd=tuple(_resolve_token(part) for part in cmd)))
        profiles[profile_name] = ProfileSpec(
            name=profile_name,
            description=description,
            commands=tuple(commands),
        )
    return profiles


def _summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        p95 = ordered[0]
    else:
        raw_index = 0.95 * (len(ordered) - 1)
        lower = int(raw_index)
        upper = min(lower + 1, len(ordered) - 1)
        weight = raw_index - lower
        p95 = ordered[lower] * (1.0 - weight) + ordered[upper] * weight
    return {
        "median_sec": round(float(statistics.median(ordered)), 3),
        "mean_sec": round(float(statistics.mean(ordered)), 3),
        "min_sec": round(float(min(ordered)), 3),
        "max_sec": round(float(max(ordered)), 3),
        "p95_sec": round(float(p95), 3),
    }


def _build_timing_stats(values: list[float]) -> dict[str, Any]:
    summary = _summary(values)
    summary["samples_sec"] = [round(float(value), 3) for value in values]
    summary["cold_sec"] = round(float(values[0]), 3)
    if len(values) > 1:
        summary["warm_summary"] = _summary(values[1:])
    else:
        summary["warm_summary"] = None
    return summary


def _run_command(command: CommandSpec, iteration: int, total_iterations: int) -> tuple[int, float]:
    printable = " ".join(command.cmd)
    print(
        f"[measure_dev_loop] [{iteration}/{total_iterations}] "
        f"{command.name}: {printable}",
        flush=True,
    )
    started = time.perf_counter()
    completed = subprocess.run(list(command.cmd), check=False)
    duration = time.perf_counter() - started
    print(
        f"[measure_dev_loop] -> rc={completed.returncode} duration_sec={duration:.3f}",
        flush=True,
    )
    return int(completed.returncode), duration


def _render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Dev Loop Timing Baseline",
        "",
        f"- Generated UTC: {payload['generated_at_utc']}",
        f"- Iterations per profile: {payload['iterations']}",
        f"- Config: `{payload['config_path']}`",
        "",
    ]
    for profile in payload["profiles"]:
        lines.extend(
            [
                f"## Profile: `{profile['name']}`",
                "",
                profile["description"] or "No description.",
                "",
                "| Metric | Median (s) | Mean (s) | Min (s) | Max (s) | P95 (s) |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for item in profile["command_stats"]:
            lines.append(
                f"| `{item['name']}` | {item['median_sec']:.3f} | {item['mean_sec']:.3f} | "
                f"{item['min_sec']:.3f} | {item['max_sec']:.3f} | {item['p95_sec']:.3f} |"
            )
            if item.get("warm_summary"):
                lines.append(
                    f"| `{item['name']}: cold/warm` | {item['cold_sec']:.3f} | "
                    f"{item['warm_summary']['median_sec']:.3f} | {item['warm_summary']['min_sec']:.3f} | "
                    f"{item['warm_summary']['max_sec']:.3f} | {item['warm_summary']['p95_sec']:.3f} |"
                )
        total = profile["profile_total"]
        lines.append(
            f"| `profile_total` | {total['median_sec']:.3f} | {total['mean_sec']:.3f} | "
            f"{total['min_sec']:.3f} | {total['max_sec']:.3f} | {total['p95_sec']:.3f} |"
        )
        if total.get("warm_summary"):
            lines.append(
                f"| `profile_total: cold/warm` | {total['cold_sec']:.3f} | "
                f"{total['warm_summary']['median_sec']:.3f} | {total['warm_summary']['min_sec']:.3f} | "
                f"{total['warm_summary']['max_sec']:.3f} | {total['warm_summary']['p95_sec']:.3f} |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure local harness timing baselines for session, loop, pre-push, and CI profiles."
    )
    parser.add_argument("--config", default="configs/dev_loop_timing_profiles.yaml")
    parser.add_argument(
        "--profiles",
        nargs="+",
        default=None,
        help="Profile names to execute (default: all).",
    )
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--json-out", default=None, help="Optional output path for JSON report.")
    parser.add_argument("--report-out", default=None, help="Optional output path for markdown report.")
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue measuring even if a command fails.",
    )
    args = parser.parse_args()

    if args.iterations < 1:
        print("ERROR: --iterations must be >= 1", file=sys.stderr)
        return 2

    config_path = Path(args.config)
    profiles = _load_profiles(config_path)
    selected = args.profiles or sorted(profiles.keys())

    missing_profiles = [name for name in selected if name not in profiles]
    if missing_profiles:
        print(f"ERROR: unknown profiles requested: {', '.join(missing_profiles)}", file=sys.stderr)
        return 2

    report_profiles: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for profile_name in selected:
        profile = profiles[profile_name]
        command_durations: dict[str, list[float]] = {item.name: [] for item in profile.commands}
        profile_totals: list[float] = []

        for iteration in range(1, args.iterations + 1):
            total = 0.0
            for command in profile.commands:
                rc, duration = _run_command(command, iteration, args.iterations)
                command_durations[command.name].append(duration)
                total += duration
                if rc != 0:
                    failure = {
                        "profile": profile.name,
                        "command": command.name,
                        "return_code": rc,
                        "iteration": iteration,
                    }
                    failures.append(failure)
                    if not args.continue_on_error:
                        print(
                            "ERROR: command failed during measurement "
                            f"(profile={profile.name} command={command.name} rc={rc})",
                            file=sys.stderr,
                        )
                        return rc
            profile_totals.append(total)

        command_stats = [
            {"name": name, **_build_timing_stats(values)}
            for name, values in sorted(command_durations.items(), key=lambda item: item[0])
        ]
        report_profiles.append(
            {
                "name": profile.name,
                "description": profile.description,
                "command_stats": command_stats,
                "profile_total": _build_timing_stats(profile_totals),
            }
        )

    payload: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "iterations": args.iterations,
        "config_path": config_path.as_posix(),
        "profiles": report_profiles,
        "failures": failures,
    }

    if args.json_out:
        json_path = Path(args.json_out)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[measure_dev_loop] wrote JSON report: {json_path.as_posix()}")

    rendered = _render_report(payload)
    if args.report_out:
        report_path = Path(args.report_out)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered + "\n", encoding="utf-8")
        print(f"[measure_dev_loop] wrote markdown report: {report_path.as_posix()}")
    else:
        print(rendered)

    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
