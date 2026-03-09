from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import run_o1_execution_hypothesis_program as o1prog
import run_signals_sizing_scenarios as sizing

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = REPO_ROOT / "artifacts" / "research"
DATE_STAMP = datetime.now(UTC).strftime("%Y%m%d")
DEFAULT_REFERENCE = o1prog.DEFAULT_REFERENCE
DEFAULT_OUTPUT = ARTIFACT_DIR / f"wf_goal_v6_h4a_vs_baseline_risk_{DATE_STAMP}.json"
EXCLUDED_MINI_ROOTS = frozenset({"BM", "GN", "NR", "RM", "S1"})


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    label: str
    execution_overrides: dict[str, Any]
    artifact_name: str


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def relpath(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _float_or_none(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return float(value)


def _int_or_none(raw: Any) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _sample_quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(float(item) for item in values)
    pos = (len(ordered) - 1) * float(q)
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    frac = float(pos - low)
    return float(ordered[low] + (ordered[high] - ordered[low]) * frac)


def instrument_root(instrument_id: str) -> str:
    token = str(instrument_id or "").strip().upper()
    matched = re.match(r"^([A-Z0-9]+?)[FGHJKMNQUVXZ]\d$", token)
    if matched:
        return str(matched.group(1)).upper()
    return token


def is_excluded_mini_instrument(instrument_id: str) -> bool:
    return instrument_root(instrument_id) in EXCLUDED_MINI_ROOTS


def filter_no_mini_report(report: dict[str, Any]) -> dict[str, Any]:
    payload = dict(report)
    planned_rows = []
    for row in report.get("planned_signals") or []:
        if is_excluded_mini_instrument(str(row.get("instrument_id") or "")):
            continue
        planned_rows.append(dict(row))
    payload["planned_signals"] = planned_rows
    payload["universe_policy"] = {
        "exclude_mini_roots": sorted(EXCLUDED_MINI_ROOTS),
    }
    return payload


def _month_keys(start_date: date, end_date: date) -> list[str]:
    year = start_date.year
    month = start_date.month
    result: list[str] = []
    while (year, month) <= (end_date.year, end_date.month):
        result.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            month = 1
            year += 1
    return result


def build_command(
    *,
    reference: dict[str, Any],
    execution_overrides: dict[str, Any],
    output_path: Path,
    risk_pct: float | None,
    max_contracts: int | None,
) -> list[str]:
    filtered_reference = dict(reference)
    filtered_reference["instruments"] = [
        instrument_id
        for instrument_id in list(reference.get("instruments") or [])
        if not is_excluded_mini_instrument(str(instrument_id))
    ]
    command = o1prog.build_command(filtered_reference, execution_overrides)
    command.extend(["--out-json", str(output_path), "--position-sizing-mode", "target_risk_pct"])
    command.extend(
        [
            "--commission-model",
            "moex_real_fees",
            "--broker-fee-rub-per-order-per-lot",
            "0.45",
            "--commission-ticks-per-side",
            "0.0",
        ]
    )
    if risk_pct is not None:
        command.extend(["--position-sizing-risk-pct", str(float(risk_pct))])
    if max_contracts is not None:
        command.extend(["--position-sizing-max-contracts", str(max(int(max_contracts), 1))])
    return command


def run_report(command: list[str]) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    subprocess.run(command, cwd=REPO_ROOT, check=True, env=subprocess_env())
    out_index = command.index("--out-json")
    report = load_json(Path(command[out_index + 1]))
    return report, time.perf_counter() - started


def execution_delta(
    baseline_execution: dict[str, Any], candidate_execution: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    delta: dict[str, dict[str, Any]] = {}
    for key in sorted(set(baseline_execution) | set(candidate_execution)):
        baseline_value = baseline_execution.get(key)
        candidate_value = candidate_execution.get(key)
        if baseline_value == candidate_value:
            continue
        delta[key] = {
            "baseline_risk": baseline_value,
            "candidate": candidate_value,
        }
    return delta


def classify_signal_row(row: dict[str, Any]) -> str:
    if bool(row.get("simulated_filled")):
        outcome = str(row.get("simulated_outcome") or "").strip().upper()
        return outcome or "FILLED"
    gate_status = str(row.get("gate_status") or "").strip().upper()
    if gate_status == "BLOCK":
        return "GATED_OUT"
    return "NO_FILL"


def signal_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in report.get("planned_signals") or []:
        trade_date = str(item.get("trade_date") or "")[:10]
        root = str(item.get("instrument_id") or "").strip().upper()
        if not trade_date or not root:
            continue
        if is_excluded_mini_instrument(root):
            continue
        net_money = _float_or_none(item.get("simulated_net_money"))
        gross_money = _float_or_none(item.get("simulated_gross_money"))
        cost_money = _float_or_none(item.get("simulated_cost_money"))
        net_ticks = _float_or_none(item.get("simulated_net_ticks")) or 0.0
        gross_ticks = _float_or_none(item.get("simulated_gross_ticks")) or 0.0
        qty_lots = max(_int_or_none(item.get("qty_lots")) or 1, 1)
        rows.append(
            {
                "trade_date": trade_date,
                "trade_month": trade_date[:7],
                "root": root,
                "slot": str(item.get("as_of_ts") or "")[11:16],
                "setup_kind": str(item.get("setup_kind") or ""),
                "side": str(item.get("side") or ""),
                "entry_order_type": str(item.get("entry_order_type") or ""),
                "gate_status": str(item.get("gate_status") or ""),
                "gate_reason": str(item.get("gate_reason") or ""),
                "simulated_filled": bool(item.get("simulated_filled")),
                "outcome_class": classify_signal_row(item),
                "net_ticks": float(net_ticks),
                "gross_ticks": float(gross_ticks),
                "net_money": float(net_money or 0.0),
                "gross_money": float(gross_money or 0.0),
                "cost_money": float(cost_money or max((gross_money or 0.0) - (net_money or 0.0), 0.0)),
                "qty_lots": int(qty_lots),
                "roe_pct": _float_or_none(item.get("simulated_net_return_on_equity_pct")) or 0.0,
            }
        )
    return rows


def subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    src_path = str(REPO_ROOT / "src")
    repo_path = str(REPO_ROOT)
    current = str(env.get("PYTHONPATH", "") or "")
    env["PYTHONPATH"] = os.pathsep.join([part for part in [src_path, repo_path, current] if part])
    return env


def _bucket_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    setups_total = int(len(rows))
    filled_rows = [row for row in rows if bool(row["simulated_filled"])]
    filled_count = int(len(filled_rows))
    blocked_count = int(sum(1 for row in rows if row["outcome_class"] == "GATED_OUT"))
    no_fill_count = int(sum(1 for row in rows if row["outcome_class"] == "NO_FILL"))
    net_money_values = [float(row["net_money"]) for row in filled_rows]
    net_tick_values = [float(row["net_ticks"]) for row in filled_rows]
    qty_values = [int(row["qty_lots"]) for row in filled_rows]
    tp_count = int(sum(1 for row in filled_rows if row["outcome_class"] == "TP"))
    sl_count = int(sum(1 for row in filled_rows if row["outcome_class"] == "SL"))
    exit_count = int(sum(1 for row in filled_rows if row["outcome_class"] == "EXIT"))
    return {
        "setups_total": setups_total,
        "filled_trades": filled_count,
        "gated_out": blocked_count,
        "no_fill": no_fill_count,
        "fill_rate": float(filled_count / setups_total) if setups_total > 0 else 0.0,
        "gated_share": float(blocked_count / setups_total) if setups_total > 0 else 0.0,
        "no_fill_share": float(no_fill_count / setups_total) if setups_total > 0 else 0.0,
        "tp_rate": float(tp_count / filled_count) if filled_count > 0 else 0.0,
        "sl_rate": float(sl_count / filled_count) if filled_count > 0 else 0.0,
        "exit_rate": float(exit_count / filled_count) if filled_count > 0 else 0.0,
        "win_rate_net": float(sum(1 for value in net_tick_values if value > 0.0) / filled_count)
        if filled_count > 0
        else 0.0,
        "net_money_sum": float(sum(net_money_values)),
        "net_ticks_sum": float(sum(net_tick_values)),
        "expectancy_net_money": float(sum(net_money_values) / filled_count) if filled_count > 0 else 0.0,
        "expectancy_net_ticks": float(sum(net_tick_values) / filled_count) if filled_count > 0 else 0.0,
        "avg_qty_lots": float(statistics.mean(qty_values)) if qty_values else 0.0,
        "median_qty_lots": float(statistics.median(qty_values)) if qty_values else 0.0,
    }


def bucket_breakdown(rows: list[dict[str, Any]], key: str, *, limit: int = 15) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "")].append(row)
    payload: list[dict[str, Any]] = []
    for bucket_key, bucket_rows in grouped.items():
        if not bucket_key:
            continue
        stats = _bucket_stats(bucket_rows)
        payload.append({key: bucket_key, **stats})
    payload.sort(key=lambda item: (abs(float(item["net_money_sum"])), float(item["filled_trades"])), reverse=True)
    return payload[:limit]


def bucket_delta(
    candidate_rows: list[dict[str, Any]],
    baseline_rows: list[dict[str, Any]],
    key: str,
    *,
    limit: int = 10,
) -> dict[str, list[dict[str, Any]]]:
    candidate_map = {str(item[key]): item for item in bucket_breakdown(candidate_rows, key, limit=10_000)}
    baseline_map = {str(item[key]): item for item in bucket_breakdown(baseline_rows, key, limit=10_000)}
    merged: list[dict[str, Any]] = []
    for bucket_key in sorted(set(candidate_map) | set(baseline_map)):
        candidate = candidate_map.get(bucket_key, {})
        baseline = baseline_map.get(bucket_key, {})
        merged.append(
            {
                key: bucket_key,
                "candidate_net_money_sum": float(candidate.get("net_money_sum", 0.0) or 0.0),
                "baseline_net_money_sum": float(baseline.get("net_money_sum", 0.0) or 0.0),
                "delta_net_money_sum": float(candidate.get("net_money_sum", 0.0) or 0.0)
                - float(baseline.get("net_money_sum", 0.0) or 0.0),
                "candidate_filled_trades": int(candidate.get("filled_trades", 0) or 0),
                "baseline_filled_trades": int(baseline.get("filled_trades", 0) or 0),
                "delta_filled_trades": int(candidate.get("filled_trades", 0) or 0)
                - int(baseline.get("filled_trades", 0) or 0),
                "candidate_fill_rate": float(candidate.get("fill_rate", 0.0) or 0.0),
                "baseline_fill_rate": float(baseline.get("fill_rate", 0.0) or 0.0),
                "delta_fill_rate": float(candidate.get("fill_rate", 0.0) or 0.0)
                - float(baseline.get("fill_rate", 0.0) or 0.0),
            }
        )
    positive = sorted(
        [item for item in merged if float(item["delta_net_money_sum"]) > 0.0],
        key=lambda item: float(item["delta_net_money_sum"]),
        reverse=True,
    )
    negative = sorted(
        [item for item in merged if float(item["delta_net_money_sum"]) < 0.0],
        key=lambda item: float(item["delta_net_money_sum"]),
    )
    return {"top_positive": positive[:limit], "top_negative": negative[:limit]}


def gate_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    outcome_counts = Counter(str(row["outcome_class"]) for row in rows)
    gate_status_counts = Counter(str(row["gate_status"] or "EMPTY") for row in rows)
    blocked_reasons = Counter(str(row["gate_reason"]) for row in rows if str(row["gate_reason"]))
    return {
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "gate_status_counts": dict(sorted(gate_status_counts.items())),
        "top_block_reasons": [
            {"gate_reason": reason, "count": int(count)}
            for reason, count in blocked_reasons.most_common(10)
        ],
    }


def qty_distribution(rows: list[dict[str, Any]], *, max_contracts: int | None = None) -> dict[str, Any]:
    filled_qtys = [int(row["qty_lots"]) for row in rows if bool(row["simulated_filled"])]
    cap_hit_share = (
        float(sum(1 for item in filled_qtys if int(item) >= int(max_contracts)) / len(filled_qtys))
        if filled_qtys and max_contracts is not None and int(max_contracts) > 0
        else None
    )
    if not filled_qtys:
        return {
            "filled_trades": 0,
            "min_qty_lots": 0,
            "p25_qty_lots": 0.0,
            "median_qty_lots": 0.0,
            "p75_qty_lots": 0.0,
            "max_qty_lots": 0,
            "mean_qty_lots": 0.0,
            "cap_hit_share": cap_hit_share,
        }
    return {
        "filled_trades": int(len(filled_qtys)),
        "min_qty_lots": int(min(filled_qtys)),
        "p25_qty_lots": float(_sample_quantile([float(item) for item in filled_qtys], 0.25)),
        "median_qty_lots": float(statistics.median(filled_qtys)),
        "p75_qty_lots": float(_sample_quantile([float(item) for item in filled_qtys], 0.75)),
        "max_qty_lots": int(max(filled_qtys)),
        "mean_qty_lots": float(statistics.mean(filled_qtys)),
        "cap_hit_share": cap_hit_share,
    }


def monthly_execution(report: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    period = report.get("period") or {}
    start_date = date.fromisoformat(str(period.get("start_date")))
    end_date = date.fromisoformat(str(period.get("end_date")))
    months = {key: [] for key in _month_keys(start_date, end_date)}
    for row in rows:
        month_key = str(row["trade_month"])
        if month_key in months:
            months[month_key].append(row)
    account_equity = _float_or_none(report.get("account_equity"))
    payload: list[dict[str, Any]] = []
    for month_key, month_rows in sorted(months.items()):
        stats = _bucket_stats(month_rows)
        net_money_sum = float(stats["net_money_sum"])
        payload.append(
            {
                "month": month_key,
                **stats,
                "return_on_equity_pct": sizing._return_on_equity_pct(net_money_sum, account_equity),
            }
        )
    return {
        "months": payload,
        "summary": {
            "positive_months": int(sum(1 for item in payload if float(item["net_money_sum"]) > 0.0)),
            "negative_months": int(sum(1 for item in payload if float(item["net_money_sum"]) < 0.0)),
            "flat_months": int(sum(1 for item in payload if abs(float(item["net_money_sum"])) <= 1e-9)),
            "median_monthly_net_money": float(statistics.median([float(item["net_money_sum"]) for item in payload]))
            if payload
            else 0.0,
        },
    }


def fold_money_stats(report: dict[str, Any]) -> dict[str, Any]:
    fold_rows = [fold.get("test_summary") or {} for fold in report.get("folds") or []]
    net_money_values = [float((row.get("net_money_sum", 0.0) or 0.0)) for row in fold_rows]
    roe_values = [float((row.get("return_on_equity_pct", 0.0) or 0.0)) for row in fold_rows]
    fill_rate_values = [float((row.get("fill_rate", 0.0) or 0.0)) for row in fold_rows]
    trades_values = [int((row.get("filled_trades", 0) or 0)) for row in fold_rows]
    if not fold_rows:
        return {
            "fold_count": 0,
            "positive_folds": 0,
            "negative_folds": 0,
            "zero_folds": 0,
            "negative_fold_share": 0.0,
            "median_net_money_sum": 0.0,
            "p25_net_money_sum": 0.0,
            "p75_net_money_sum": 0.0,
            "median_return_on_equity_pct": 0.0,
            "median_fill_rate": 0.0,
            "median_filled_trades": 0.0,
        }
    negative = int(sum(1 for value in net_money_values if value < 0.0))
    positive = int(sum(1 for value in net_money_values if value > 0.0))
    zero = int(len(net_money_values) - positive - negative)
    return {
        "fold_count": int(len(fold_rows)),
        "positive_folds": positive,
        "negative_folds": negative,
        "zero_folds": zero,
        "negative_fold_share": float(negative / len(fold_rows)),
        "median_net_money_sum": float(statistics.median(net_money_values)),
        "p25_net_money_sum": float(_sample_quantile(net_money_values, 0.25)),
        "p75_net_money_sum": float(_sample_quantile(net_money_values, 0.75)),
        "median_return_on_equity_pct": float(statistics.median(roe_values)) if roe_values else 0.0,
        "median_fill_rate": float(statistics.median(fill_rate_values)) if fill_rate_values else 0.0,
        "median_filled_trades": float(statistics.median(trades_values)) if trades_values else 0.0,
    }


def scenario_payload(
    *,
    report: dict[str, Any],
    runtime_seconds: float,
    command: list[str],
    max_contracts: int,
) -> dict[str, Any]:
    rows = signal_rows(report)
    return {
        "runtime_seconds": round(float(runtime_seconds), 3),
        "command": command,
        "position_sizing": report.get("position_sizing"),
        "top_line": sizing.scenario_metrics(report),
        "fold_stats": fold_money_stats(report),
        "gate_stats": gate_stats(rows),
        "qty_distribution": qty_distribution(rows, max_contracts=max_contracts),
        "monthly_execution": monthly_execution(report, rows),
        "by_outcome_class": bucket_breakdown(rows, "outcome_class"),
        "by_root": bucket_breakdown(rows, "root"),
        "by_setup_kind": bucket_breakdown(rows, "setup_kind"),
        "by_slot": bucket_breakdown(rows, "slot"),
        "by_entry_order_type": bucket_breakdown(rows, "entry_order_type"),
    }


def run_analysis(args: argparse.Namespace) -> dict[str, Any]:
    reference_path = Path(args.reference_artifact)
    reference = load_json(reference_path)
    baseline_execution = o1prog.normalize_execution_policy(reference)
    target_risk_pct = (
        float(args.position_sizing_risk_pct)
        if args.position_sizing_risk_pct is not None
        else _float_or_none((reference.get("position_sizing") or {}).get("target_risk_pct"))
    )
    if target_risk_pct is None:
        target_risk_pct = 0.5
    max_contracts = (
        max(int(args.position_sizing_max_contracts), 1)
        if args.position_sizing_max_contracts is not None
        else int((reference.get("position_sizing") or {}).get("max_contracts_per_instrument") or 10)
    )
    scenarios = [
        ScenarioSpec(
            scenario_id="BASELINE_RISK_RECHECK",
            label="O1 baseline with target risk sizing",
            execution_overrides={},
            artifact_name=f"wf_goal_v6_baseline_risk_recheck_{DATE_STAMP}.json",
        ),
        ScenarioSpec(
            scenario_id="H4A_RISK",
            label="H4A (RR cap off) with target risk sizing",
            execution_overrides={"max_profit_rr": 0.0},
            artifact_name=f"wf_goal_v6_h4a_risk_{DATE_STAMP}.json",
        ),
    ]
    scenario_reports: dict[str, dict[str, Any]] = {}
    scenario_rows: dict[str, list[dict[str, Any]]] = {}
    scenario_metrics: dict[str, dict[str, Any]] = {}
    scenario_commands: dict[str, list[str]] = {}
    scenario_runtimes: dict[str, float] = {}
    for scenario in scenarios:
        artifact_path = ARTIFACT_DIR / scenario.artifact_name
        command = build_command(
            reference=reference,
            execution_overrides=scenario.execution_overrides,
            output_path=artifact_path,
            risk_pct=target_risk_pct,
            max_contracts=max_contracts,
        )
        report, runtime_seconds = run_report(command)
        report = filter_no_mini_report(report)
        write_json(artifact_path, report)
        scenario_reports[scenario.scenario_id] = report
        scenario_rows[scenario.scenario_id] = signal_rows(report)
        scenario_metrics[scenario.scenario_id] = sizing.scenario_metrics(report)
        scenario_commands[scenario.scenario_id] = command
        scenario_runtimes[scenario.scenario_id] = runtime_seconds

    baseline_key = "BASELINE_RISK_RECHECK"
    h4a_key = "H4A_RISK"
    h4a_execution = dict(baseline_execution)
    h4a_execution.update({"max_profit_rr": 0.0})
    scenario_payloads = {
        baseline_key: scenario_payload(
            report=scenario_reports[baseline_key],
            runtime_seconds=scenario_runtimes[baseline_key],
            command=scenario_commands[baseline_key],
            max_contracts=max_contracts,
        ),
        h4a_key: scenario_payload(
            report=scenario_reports[h4a_key],
            runtime_seconds=scenario_runtimes[h4a_key],
            command=scenario_commands[h4a_key],
            max_contracts=max_contracts,
        ),
    }
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "reference_artifact": relpath(reference_path),
        "position_sizing": {
            "mode": "target_risk_pct",
            "target_risk_pct": float(target_risk_pct) if target_risk_pct is not None else None,
            "max_contracts_per_instrument": int(max_contracts),
            "account_equity": _float_or_none(reference.get("account_equity")),
        },
        "execution": {
            "baseline_risk": baseline_execution,
            "h4a_risk": h4a_execution,
            "changed_params": execution_delta(baseline_execution, h4a_execution),
        },
        "scenarios": scenario_payloads,
        "delta_vs_baseline_risk": {
            "top_line": sizing.metrics_delta(scenario_metrics[h4a_key], scenario_metrics[baseline_key]),
            "fold_stats": {
                key: float(
                    (scenario_payloads[h4a_key]["fold_stats"].get(key, 0.0) or 0.0)
                    - (scenario_payloads[baseline_key]["fold_stats"].get(key, 0.0) or 0.0)
                )
                for key in (
                    "negative_fold_share",
                    "median_net_money_sum",
                    "p25_net_money_sum",
                    "p75_net_money_sum",
                    "median_return_on_equity_pct",
                    "median_fill_rate",
                    "median_filled_trades",
                )
            },
            "qty_distribution": {
                key: float(
                    (scenario_payloads[h4a_key]["qty_distribution"].get(key, 0.0) or 0.0)
                    - (scenario_payloads[baseline_key]["qty_distribution"].get(key, 0.0) or 0.0)
                )
                for key in (
                    "p25_qty_lots",
                    "median_qty_lots",
                    "p75_qty_lots",
                    "mean_qty_lots",
                    "cap_hit_share",
                )
            },
            "by_outcome_class": bucket_delta(
                scenario_rows[h4a_key], scenario_rows[baseline_key], "outcome_class"
            ),
            "by_root": bucket_delta(scenario_rows[h4a_key], scenario_rows[baseline_key], "root"),
            "by_setup_kind": bucket_delta(scenario_rows[h4a_key], scenario_rows[baseline_key], "setup_kind"),
            "by_slot": bucket_delta(scenario_rows[h4a_key], scenario_rows[baseline_key], "slot"),
            "by_entry_order_type": bucket_delta(
                scenario_rows[h4a_key], scenario_rows[baseline_key], "entry_order_type"
            ),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay H4A on the money-sizing path and compare it deeply against baseline risk."
    )
    parser.add_argument("--reference-artifact", type=str, default=str(DEFAULT_REFERENCE))
    parser.add_argument("--position-sizing-risk-pct", type=float, default=None)
    parser.add_argument("--position-sizing-max-contracts", type=int, default=None)
    parser.add_argument("--out-json", type=str, default=str(DEFAULT_OUTPUT))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    payload = run_analysis(args)
    output_path = Path(args.out_json)
    write_json(output_path, payload)
    print("scenario_count", len(payload.get("scenarios", {})))
    print("out_json", relpath(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
