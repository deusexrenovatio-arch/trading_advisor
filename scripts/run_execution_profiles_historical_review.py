from __future__ import annotations

import argparse
import copy
import json
import os
import statistics
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import run_o1_execution_hypothesis_program as o1prog

PROFILES: dict[str, dict[str, Any]] = {
    "O1": {
        "label": "O1 baseline",
        "overrides": {},
    },
    "H3B_SL_3P0": {
        "label": "Wider stop at 3.0R",
        "overrides": {"sl_rr": 3.0},
    },
    "H4A_CAP_OFF": {
        "label": "Disable RR profit cap",
        "overrides": {"max_profit_rr": 0.0},
    },
}


def subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    src_path = str(o1prog.REPO_ROOT / "src")
    repo_path = str(o1prog.REPO_ROOT)
    current = str(env.get("PYTHONPATH", "") or "")
    env["PYTHONPATH"] = os.pathsep.join([part for part in [src_path, repo_path, current] if part])
    return env


def parse_csv_tokens(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [token.strip().upper() for token in str(raw).split(",") if token.strip()]


def clone_reference_with_period(reference: dict[str, Any], start_date: date, end_date: date) -> dict[str, Any]:
    cloned = copy.deepcopy(reference)
    cloned["period"]["start_date"] = start_date.isoformat()
    cloned["period"]["end_date"] = end_date.isoformat()
    return cloned


def expand_instruments(reference: dict[str, Any], prefetch_paths: list[Path]) -> list[str]:
    instruments = {str(item) for item in reference.get("instruments") or []}
    for path in prefetch_paths:
        if not path.exists():
            continue
        payload = o1prog.load_json(path)
        for secid in (payload.get("active_payload_sizes") or {}).keys():
            instruments.add(str(secid))
    return sorted(instruments)


def run_report(reference: dict[str, Any], overrides: dict[str, Any], artifact_path: Path) -> tuple[dict[str, Any], list[str]]:
    command = o1prog.build_command(reference, overrides)
    command.extend(["--out-json", str(artifact_path)])
    subprocess.run(command, cwd=o1prog.REPO_ROOT, check=True, env=subprocess_env())
    return o1prog.load_json(artifact_path), command


def filled_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in report.get("planned_signals") or []:
        if not bool(item.get("simulated_filled")):
            continue
        trade_date = str(item.get("trade_date") or "")
        if not trade_date:
            continue
        net_ticks = float(item.get("simulated_net_ticks", 0.0) or 0.0)
        gross_ticks = float(item.get("simulated_gross_ticks", 0.0) or 0.0)
        rows.append(
            {
                "trade_date": trade_date,
                "trade_month": trade_date[:7],
                "trade_year": trade_date[:4],
                "root": str(item.get("instrument_id") or ""),
                "setup_kind": str(item.get("setup_kind") or ""),
                "outcome": str(item.get("simulated_outcome") or ""),
                "side": str(item.get("side") or ""),
                "net_ticks": net_ticks,
                "gross_ticks": gross_ticks,
            }
        )
    return rows


def rows_in_window(rows: list[dict[str, Any]], start_date: date, end_date: date) -> list[dict[str, Any]]:
    start_text = start_date.isoformat()
    end_text = end_date.isoformat()
    return [row for row in rows if start_text <= row["trade_date"] <= end_text]


def positive_share(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(sum(1 for value in values if value > 0.0) / len(values))


def summary_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "filled_trades": 0,
            "net_ticks_sum": 0.0,
            "gross_ticks_sum": 0.0,
            "expectancy_net_ticks": 0.0,
            "win_rate_net": 0.0,
        }
    net_values = [float(row["net_ticks"]) for row in rows]
    gross_values = [float(row["gross_ticks"]) for row in rows]
    return {
        "filled_trades": len(rows),
        "net_ticks_sum": float(sum(net_values)),
        "gross_ticks_sum": float(sum(gross_values)),
        "expectancy_net_ticks": float(sum(net_values) / len(net_values)),
        "win_rate_net": positive_share(net_values),
    }


def by_root_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["root"], []).append(row)
    result: list[dict[str, Any]] = []
    for root, root_rows in grouped.items():
        net_values = [float(item["net_ticks"]) for item in root_rows]
        gross_values = [float(item["gross_ticks"]) for item in root_rows]
        months = sorted({item["trade_month"] for item in root_rows})
        result.append(
            {
                "root": root,
                "filled_trades": len(root_rows),
                "net_ticks_sum": float(sum(net_values)),
                "gross_ticks_sum": float(sum(gross_values)),
                "expectancy_net_ticks": float(sum(net_values) / len(net_values)),
                "win_rate_net": positive_share(net_values),
                "active_months": len(months),
                "first_month": months[0] if months else None,
                "last_month": months[-1] if months else None,
            }
        )
    result.sort(key=lambda item: float(item["net_ticks_sum"]), reverse=True)
    return result


def monthly_calendar(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["trade_month"], []).append(row)
    months: list[dict[str, Any]] = []
    month_nets: list[float] = []
    for month in sorted(grouped):
        month_rows = grouped[month]
        net_ticks = float(sum(float(item["net_ticks"]) for item in month_rows))
        gross_ticks = float(sum(float(item["gross_ticks"]) for item in month_rows))
        month_nets.append(net_ticks)
        months.append(
            {
                "month": month,
                "filled_trades": len(month_rows),
                "net_ticks_sum": net_ticks,
                "gross_ticks_sum": gross_ticks,
                "win_rate_net": positive_share([float(item["net_ticks"]) for item in month_rows]),
            }
        )
    if not months:
        return {
            "months": [],
            "summary": {
                "months_total": 0,
                "profitable_months": 0,
                "losing_months": 0,
                "flat_months": 0,
                "best_month": None,
                "worst_month": None,
                "net_ticks_min": 0.0,
                "net_ticks_max": 0.0,
                "net_ticks_range": 0.0,
                "net_ticks_mean": 0.0,
                "net_ticks_median": 0.0,
            },
        }
    best_month = max(months, key=lambda item: float(item["net_ticks_sum"]))
    worst_month = min(months, key=lambda item: float(item["net_ticks_sum"]))
    profitable_months = sum(1 for item in months if float(item["net_ticks_sum"]) > 0.0)
    losing_months = sum(1 for item in months if float(item["net_ticks_sum"]) < 0.0)
    flat_months = len(months) - profitable_months - losing_months
    return {
        "months": months,
        "summary": {
            "months_total": len(months),
            "profitable_months": profitable_months,
            "losing_months": losing_months,
            "flat_months": flat_months,
            "best_month": {"month": best_month["month"], "net_ticks_sum": float(best_month["net_ticks_sum"])},
            "worst_month": {"month": worst_month["month"], "net_ticks_sum": float(worst_month["net_ticks_sum"])},
            "net_ticks_min": float(min(month_nets)),
            "net_ticks_max": float(max(month_nets)),
            "net_ticks_range": float(max(month_nets) - min(month_nets)),
            "net_ticks_mean": float(statistics.mean(month_nets)),
            "net_ticks_median": float(statistics.median(month_nets)),
        },
    }


def yearly_calendar(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["trade_year"], []).append(row)
    years: list[dict[str, Any]] = []
    for year in sorted(grouped):
        year_rows = grouped[year]
        years.append(
            {
                "year": year,
                "filled_trades": len(year_rows),
                "net_ticks_sum": float(sum(float(item["net_ticks"]) for item in year_rows)),
                "gross_ticks_sum": float(sum(float(item["gross_ticks"]) for item in year_rows)),
                "win_rate_net": positive_share([float(item["net_ticks"]) for item in year_rows]),
            }
        )
    return years


def subset_payload(rows: list[dict[str, Any]], start_date: date, end_date: date) -> dict[str, Any]:
    filtered = rows_in_window(rows, start_date, end_date)
    return {
        "period": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        "summary": summary_from_rows(filtered),
        "by_root": by_root_summary(filtered),
        "monthly": monthly_calendar(filtered),
        "yearly": yearly_calendar(filtered),
    }


def delta_summary(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    return {
        "filled_trades": int(candidate["filled_trades"]) - int(baseline["filled_trades"]),
        "net_ticks_sum": float(candidate["net_ticks_sum"]) - float(baseline["net_ticks_sum"]),
        "gross_ticks_sum": float(candidate["gross_ticks_sum"]) - float(baseline["gross_ticks_sum"]),
        "expectancy_net_ticks": float(candidate["expectancy_net_ticks"]) - float(baseline["expectancy_net_ticks"]),
        "win_rate_net": float(candidate["win_rate_net"]) - float(baseline["win_rate_net"]),
    }


def root_compare(profile_payloads: dict[str, dict[str, Any]], window_key: str) -> list[dict[str, Any]]:
    roots = set()
    for payload in profile_payloads.values():
        roots.update(item["root"] for item in payload[window_key]["by_root"])
    comparison: list[dict[str, Any]] = []
    o1_rows = {
        item["root"]: item
        for item in profile_payloads["O1"][window_key]["by_root"]
    }
    for root in sorted(roots):
        row: dict[str, Any] = {"root": root}
        o1_item = o1_rows.get(root, {})
        row["O1_net_ticks_sum"] = float(o1_item.get("net_ticks_sum", 0.0) or 0.0)
        row["O1_filled_trades"] = int(o1_item.get("filled_trades", 0) or 0)
        for profile_id, payload in profile_payloads.items():
            profile_rows = {item["root"]: item for item in payload[window_key]["by_root"]}
            item = profile_rows.get(root, {})
            row[f"{profile_id}_net_ticks_sum"] = float(item.get("net_ticks_sum", 0.0) or 0.0)
            row[f"{profile_id}_filled_trades"] = int(item.get("filled_trades", 0) or 0)
            if profile_id != "O1":
                row[f"{profile_id}_delta_vs_O1"] = float(item.get("net_ticks_sum", 0.0) or 0.0) - float(o1_item.get("net_ticks_sum", 0.0) or 0.0)
        comparison.append(row)
    comparison.sort(key=lambda item: float(item.get("O1_net_ticks_sum", 0.0)), reverse=True)
    return comparison


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run long-window historical review for execution profiles.")
    parser.add_argument("--reference-artifact", default=str(o1prog.DEFAULT_REFERENCE))
    parser.add_argument("--profiles", default="O1,H3B_SL_3P0,H4A_CAP_OFF")
    parser.add_argument("--prefetch-artifact", action="append", default=[])
    parser.add_argument("--run-start-date", default="2020-01-01")
    parser.add_argument("--run-end-date", default="2026-03-02")
    parser.add_argument("--subset-end-date", default="2024-12-31")
    parser.add_argument(
        "--out-json",
        default=str(o1prog.ARTIFACT_DIR / "wf_goal_v6_execution_profiles_historical_review_2020_2026_20260306.json"),
    )
    args = parser.parse_args()

    reference = o1prog.load_json(Path(args.reference_artifact))
    prefetch_paths = [Path(item) for item in args.prefetch_artifact]
    run_start = date.fromisoformat(args.run_start_date)
    run_end = date.fromisoformat(args.run_end_date)
    subset_start = run_start
    subset_end = date.fromisoformat(args.subset_end_date)
    active_profiles = parse_csv_tokens(args.profiles)
    unknown = [profile_id for profile_id in active_profiles if profile_id not in PROFILES]
    if unknown:
        raise ValueError(f"unknown_profiles={unknown}")

    historical_reference = clone_reference_with_period(reference, run_start, run_end)
    historical_reference["instruments"] = expand_instruments(reference, prefetch_paths)
    profile_payloads: dict[str, dict[str, Any]] = {}
    commands: dict[str, list[str]] = {}
    for profile_id in active_profiles:
        spec = PROFILES[profile_id]
        artifact_path = o1prog.ARTIFACT_DIR / f"wf_goal_v6_{profile_id.lower()}_full_2020_2026_20260306.json"
        report, command = run_report(historical_reference, dict(spec["overrides"]), artifact_path)
        rows = filled_rows(report)
        profile_payloads[profile_id] = {
            "label": str(spec["label"]),
            "overrides": dict(spec["overrides"]),
            "artifact_path": o1prog.relpath(artifact_path),
            "acceptance": report.get("acceptance") or {},
            "full_2020_2026": subset_payload(rows, run_start, run_end),
            "subset_2020_2024": subset_payload(rows, subset_start, subset_end),
        }
        commands[profile_id] = command

    comparison_full: dict[str, Any] = {}
    comparison_subset: dict[str, Any] = {}
    baseline_full = profile_payloads["O1"]["full_2020_2026"]["summary"]
    baseline_subset = profile_payloads["O1"]["subset_2020_2024"]["summary"]
    for profile_id in active_profiles:
        if profile_id == "O1":
            continue
        comparison_full[profile_id] = delta_summary(profile_payloads[profile_id]["full_2020_2026"]["summary"], baseline_full)
        comparison_subset[profile_id] = delta_summary(profile_payloads[profile_id]["subset_2020_2024"]["summary"], baseline_subset)

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "reference_artifact": o1prog.relpath(Path(args.reference_artifact)),
        "prefetch_artifacts": [o1prog.relpath(path) for path in prefetch_paths],
        "profiles": active_profiles,
        "run_period": {"start_date": run_start.isoformat(), "end_date": run_end.isoformat()},
        "subset_period": {"start_date": subset_start.isoformat(), "end_date": subset_end.isoformat()},
        "instrument_count": len(historical_reference["instruments"]),
        "profile_results": profile_payloads,
        "comparison_vs_O1": {
            "full_2020_2026": comparison_full,
            "subset_2020_2024": comparison_subset,
        },
        "per_root_compare_vs_O1": {
            "full_2020_2026": root_compare(profile_payloads, "full_2020_2026"),
            "subset_2020_2024": root_compare(profile_payloads, "subset_2020_2024"),
        },
        "commands": commands,
    }
    write_json(Path(args.out_json), payload)


if __name__ == "__main__":
    main()
