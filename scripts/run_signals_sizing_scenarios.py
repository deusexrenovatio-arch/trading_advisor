from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = REPO_ROOT / "artifacts" / "research"
DATE_STAMP = datetime.now(UTC).strftime("%Y%m%d")

DEFAULT_BASELINE_REFERENCE = (
    ARTIFACT_DIR / "wf_goal_v6_h24_causal_rerun_execution_fixed_O1_limitfallback10m1t_frontnearest_seed124_20260305.json"
)
DEFAULT_SCENARIO2_REFERENCE = ARTIFACT_DIR / "wf_goal_v6_h15_constrained_precision_recall_rerun_20260304.json"
DEFAULT_SCENARIO3_REFERENCE = ARTIFACT_DIR / "wf_goal_v6_h24_causal_rerun_causalfirst_seed124_tuned2_20260305.json"
DEFAULT_OUTPUT = ARTIFACT_DIR / f"wf_goal_v6_sizing_scenarios_{DATE_STAMP}.json"

EXECUTION_DEFAULTS: dict[str, Any] = {
    "break_even_rr": 0.0,
    "break_even_buffer_ticks": 0,
    "tp_rr": 0.0,
    "sl_rr": 0.0,
    "max_holding_minutes": 0,
    "max_profit_rr": 0.0,
    "max_profit_ticks": 0,
    "trail_activation_rr": 0.0,
    "trail_offset_ticks": 0,
    "same_bar_policy": "sl_first",
    "limit_entry_improve_ticks": 0,
    "limit_fallback_to_market_minutes": 0,
    "limit_fallback_slip_ticks": 0,
    "tp_cost_mult": 1.0,
    "sl_cost_mult": 1.0,
    "exit_cost_mult": 1.0,
}


@dataclass(frozen=True)
class ScenarioRun:
    scenario_id: str
    label: str
    note: str
    reference_artifact: Path
    overrides: dict[str, Any] = field(default_factory=dict)


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


def cluster_args(cluster_root_map: dict[str, str]) -> list[str]:
    grouped: dict[str, list[str]] = {}
    for root, cluster in sorted(cluster_root_map.items()):
        grouped.setdefault(str(cluster), []).append(str(root))
    args: list[str] = []
    for cluster, roots in grouped.items():
        args.extend(["--cluster", f"{cluster}={','.join(roots)}"])
    return args


def _float_or_none(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def _int_or_none(raw: Any) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def normalize_execution_policy(reference: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(EXECUTION_DEFAULTS)
    normalized.update((reference.get("tuning_points") or {}).get("execution_policy") or {})
    return normalized


def _maybe_add_arg(args: list[str], flag: str, value: Any) -> None:
    if value is None:
        return
    args.extend([flag, str(value)])


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _month_keys(period_start: date, period_end: date) -> list[str]:
    keys: list[str] = []
    cursor = _month_start(period_start)
    last = _month_start(period_end)
    while cursor <= last:
        keys.append(f"{cursor.year:04d}-{cursor.month:02d}")
        cursor = _next_month(cursor)
    return keys


def _sample_quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(float(item) for item in values)
    clipped = min(max(float(q), 0.0), 1.0)
    pos = (len(ordered) - 1) * clipped
    lower = int(math.floor(pos))
    upper = int(math.ceil(pos))
    if lower == upper:
        return float(ordered[lower])
    weight = pos - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * weight)


def _return_on_equity_pct(net_money: float, account_equity: float | None) -> float | None:
    if account_equity is None or account_equity <= 0.0:
        return None
    return float((float(net_money) / float(account_equity)) * 100.0)


def build_command(reference: dict[str, Any], overrides: dict[str, Any], output_path: Path) -> list[str]:
    tuning = reference.get("tuning_points") or {}
    period = reference.get("period") or {}
    goal = tuning.get("goal") or {}
    objective = tuning.get("objective_scoring") or {}
    acceptance = (reference.get("acceptance") or {}).get("thresholds") or {}
    costs = reference.get("cost_assumptions_ticks") or {}
    cache = reference.get("cache") or {}
    execution = normalize_execution_policy(reference)

    args = [sys.executable, str(REPO_ROOT / "scripts" / "run_morning_plan_walk_forward.py")]
    for instrument in reference.get("instruments") or []:
        args.extend(["--instrument", str(instrument)])
    args.extend(cluster_args(tuning.get("cluster_root_map") or {}))

    args.extend(
        [
            "--instrument-mode",
            str(reference.get("instrument_mode") or "fixed"),
            "--front-roll-avoid-expiry-days",
            str(int(tuning.get("front_roll_avoid_expiry_days", 3) or 3)),
            "--start-date",
            str(period.get("start_date")),
            "--end-date",
            str(period.get("end_date")),
            "--decision-times",
            ",".join(list(period.get("decision_times") or [])),
            "--train-days",
            str(int(tuning.get("train_days", 28) or 28)),
            "--test-days",
            str(int(tuning.get("test_days", 7) or 7)),
            "--step-days",
            str(int(tuning.get("step_days", 7) or 7)),
            "--embargo-days",
            str(int(tuning.get("embargo_days", 0) or 0)),
            "--purge-days",
            str(int(tuning.get("purge_days", 0) or 0)),
            "--tuning-profile",
            str(tuning.get("profile") or "baseline_v1"),
            "--search-algorithm",
            str(tuning.get("search_algorithm") or "GRID"),
            "--search-space-profile",
            str(tuning.get("search_space_profile") or "intraday_goal_v3"),
            "--hpo-trials",
            str(int(tuning.get("hpo_trials", 24) or 24)),
            "--hpo-startup-trials",
            str(int(tuning.get("hpo_startup_trials", 8) or 8)),
            "--hpo-seed",
            str(int(tuning.get("hpo_seed", 42) or 42)),
            "--retune-every-folds",
            str(int(tuning.get("retune_every_folds", 3) or 3)),
            "--cost-model-profile",
            str(tuning.get("cost_model_profile") or "fixed_v1"),
            "--selection-objective",
            str(tuning.get("objective") or "robust_normalized"),
            "--objective-concentration-penalty-weight",
            str(float(objective.get("concentration_penalty_weight", 0.0) or 0.0)),
            "--objective-concentration-top-share-soft-cap",
            str(float(objective.get("concentration_top_share_soft_cap", 0.35) or 0.35)),
            "--objective-normalization-floor-ticks",
            str(float(objective.get("normalization_floor_ticks", 1.0) or 1.0)),
            "--objective-negative-fold-penalty",
            str(float(objective.get("negative_fold_penalty", 0.0) or 0.0)),
            "--objective-subfold-days",
            str(int(objective.get("subfold_days", 7) or 7)),
            "--objective-tail-penalty-weight",
            str(float(objective.get("tail_penalty_weight", 0.0) or 0.0)),
            "--objective-tail-metric",
            str(objective.get("tail_metric") or "cvar"),
            "--objective-tail-alpha",
            str(float(objective.get("tail_alpha", 0.2) or 0.2)),
            "--objective-tail-lower-quantile",
            str(float(objective.get("tail_lower_quantile", 0.2) or 0.2)),
            "--objective-sl-rate-penalty-weight",
            str(float(objective.get("sl_rate_penalty_weight", 0.0) or 0.0)),
            "--objective-exit-rate-penalty-weight",
            str(float(objective.get("exit_rate_penalty_weight", 0.0) or 0.0)),
            "--objective-exit-rate-soft-cap",
            str(float(objective.get("exit_rate_soft_cap", 0.35) or 0.35)),
            "--objective-causal-confidence",
            str(float(objective.get("causal_confidence", 0.8) or 0.8)),
            "--objective-causal-winrate-lcb-weight",
            str(float(objective.get("causal_winrate_lcb_weight", 100.0) or 100.0)),
            "--objective-causal-tpw-lcb-weight",
            str(float(objective.get("causal_tpw_lcb_weight", 25.0) or 25.0)),
            "--objective-causal-expectancy-weight",
            str(float(objective.get("causal_expectancy_weight", 1.0) or 1.0)),
            "--objective-causal-instability-penalty-weight",
            str(float(objective.get("causal_instability_penalty_weight", 0.0) or 0.0)),
            "--goal-min-target-return-pct",
            str(float(goal.get("min_target_return_pct", 0.5) or 0.5)),
            "--goal-min-trades-per-week",
            str(float(goal.get("min_trades_per_week", 2.0) or 2.0)),
            "--goal-max-trades-per-week",
            str(float(goal.get("max_trades_per_week", 10.0) or 10.0)),
            "--goal-trade-freq-penalty",
            str(float(goal.get("trade_freq_penalty", 1.5) or 1.5)),
            "--goal-hard-min-winrate-net",
            str(float(goal.get("hard_min_win_rate_net", 0.0) or 0.0)),
            "--goal-hard-min-trades-per-week",
            str(float(goal.get("hard_min_trades_per_week", 0.0) or 0.0)),
            "--goal-hard-max-concentration-top-share",
            str(float(goal.get("hard_max_concentration_top_share", 1.0) or 1.0)),
            "--goal-hard-violation-penalty",
            str(float(goal.get("hard_violation_penalty", 1_000_000.0) or 1_000_000.0)),
            "--accept-max-negative-fold-share",
            str(float(acceptance.get("max_negative_fold_share", 0.6) or 0.6)),
            "--accept-min-median-fold-net-ticks",
            str(float(acceptance.get("min_median_fold_net_ticks", 0.0) or 0.0)),
            "--accept-min-tail-cvar-ticks",
            str(float(acceptance.get("min_tail_cvar_ticks", -999999.0) or -999999.0)),
            "--min-train-trades",
            str(int(tuning.get("min_train_trades", 80) or 80)),
            "--min-train-instruments-with-trades",
            str(int(tuning.get("min_train_instruments_with_trades", 10) or 10)),
            "--min-trades-per-instrument",
            str(int(tuning.get("min_trades_per_instrument", 5) or 5)),
            "--robust-mad-penalty",
            str(float(tuning.get("robust_mad_penalty", 0.5) or 0.5)),
            "--commission-ticks-per-side",
            str(float(costs.get("commission_ticks_per_side", 0.5) or 0.5)),
            "--slippage-ticks-per-side",
            str(float(costs.get("slippage_ticks_per_side", 1.0) or 1.0)),
            "--spread-half-ticks",
            str(float(costs.get("spread_half_ticks", 1.0) or 1.0)),
            "--cost-stress-mult",
            str(float(tuning.get("cost_stress_mult", 1.0) or 1.0)),
            "--execution-break-even-rr",
            str(float(execution.get("break_even_rr", 0.0) or 0.0)),
            "--execution-break-even-buffer-ticks",
            str(int(execution.get("break_even_buffer_ticks", 0) or 0)),
            "--execution-tp-rr",
            str(float(execution.get("tp_rr", 0.0) or 0.0)),
            "--execution-sl-rr",
            str(float(execution.get("sl_rr", 0.0) or 0.0)),
            "--execution-max-holding-minutes",
            str(int(execution.get("max_holding_minutes", 0) or 0)),
            "--execution-max-profit-rr",
            str(float(execution.get("max_profit_rr", 0.0) or 0.0)),
            "--execution-max-profit-ticks",
            str(int(execution.get("max_profit_ticks", 0) or 0)),
            "--execution-trail-activation-rr",
            str(float(execution.get("trail_activation_rr", 0.0) or 0.0)),
            "--execution-trail-offset-ticks",
            str(int(execution.get("trail_offset_ticks", 0) or 0)),
            "--execution-same-bar-policy",
            str(execution.get("same_bar_policy") or "sl_first"),
            "--execution-limit-entry-improve-ticks",
            str(int(execution.get("limit_entry_improve_ticks", 0) or 0)),
            "--execution-limit-fallback-to-market-minutes",
            str(int(execution.get("limit_fallback_to_market_minutes", 0) or 0)),
            "--execution-limit-fallback-slip-ticks",
            str(int(execution.get("limit_fallback_slip_ticks", 0) or 0)),
            "--execution-tp-cost-mult",
            str(float(execution.get("tp_cost_mult", 1.0) or 1.0)),
            "--execution-sl-cost-mult",
            str(float(execution.get("sl_cost_mult", 1.0) or 1.0)),
            "--execution-exit-cost-mult",
            str(float(execution.get("exit_cost_mult", 1.0) or 1.0)),
            "--cache-db",
            str(cache.get("cache_db") or "data/cache/morning_plan_candles.sqlite"),
            "--offline-only",
            "--disable-news-gate",
            "--out-json",
            str(output_path),
        ]
    )

    position_sizing_mode = str(overrides.get("position_sizing_mode", "fixed_lots"))
    args.extend(["--position-sizing-mode", position_sizing_mode])
    _maybe_add_arg(args, "--position-sizing-risk-pct", overrides.get("position_sizing_risk_pct"))
    _maybe_add_arg(args, "--position-sizing-max-contracts", overrides.get("position_sizing_max_contracts"))
    return args


def run_report(command: list[str]) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    subprocess.run(command, cwd=REPO_ROOT, check=True)
    out_index = command.index("--out-json")
    report_path = Path(command[out_index + 1])
    report = load_json(report_path)
    return report, time.perf_counter() - started


def monthly_metrics(report: dict[str, Any]) -> dict[str, Any]:
    period = report.get("period") or {}
    period_start = date.fromisoformat(str(period.get("start_date")))
    period_end = date.fromisoformat(str(period.get("end_date")))
    account_equity = _float_or_none(report.get("account_equity"))
    month_values = {key: 0.0 for key in _month_keys(period_start, period_end)}
    for row in report.get("planned_signals") or []:
        if not bool(row.get("simulated_filled")):
            continue
        trade_date = str(row.get("trade_date") or "")[:10]
        if not trade_date:
            continue
        month_key = trade_date[:7]
        if month_key not in month_values:
            continue
        net_money = _float_or_none(row.get("simulated_net_money"))
        if net_money is None:
            simulated_net_ticks = _float_or_none(row.get("simulated_net_ticks"))
            tick_value = _float_or_none(row.get("tick_value"))
            qty_lots = max(_int_or_none(row.get("qty_lots")) or 1, 1)
            if simulated_net_ticks is not None and tick_value is not None and tick_value > 0.0:
                net_money = float(simulated_net_ticks * tick_value * qty_lots)
        if net_money is None:
            continue
        month_values[month_key] += float(net_money)

    ordered_months = [
        {
            "month": month_key,
            "net_money": float(net_money),
            "return_on_equity_pct": _return_on_equity_pct(float(net_money), account_equity),
        }
        for month_key, net_money in sorted(month_values.items())
    ]
    net_values = [float(item["net_money"]) for item in ordered_months]
    roe_values = [float(item["return_on_equity_pct"] or 0.0) for item in ordered_months]
    positive_values = [value for value in net_values if value > 0.0]
    top_positive = sorted(positive_values, reverse=True)
    top1_net = float(top_positive[0]) if top_positive else 0.0
    top3_net = float(sum(top_positive[:3]))
    total_net = float(sum(net_values))
    positive_total = float(sum(positive_values))
    top1_share = float(top1_net / positive_total) if positive_total > 0.0 else 0.0
    top3_share = float(top3_net / positive_total) if positive_total > 0.0 else 0.0
    ex_top1_net = float(total_net - top1_net)
    ex_top3_net = float(total_net - top3_net)
    return {
        "months": ordered_months,
        "month_count": int(len(ordered_months)),
        "positive_months": int(sum(1 for value in net_values if value > 0.0)),
        "negative_months": int(sum(1 for value in net_values if value < 0.0)),
        "flat_months": int(sum(1 for value in net_values if abs(value) <= 1e-9)),
        "median_monthly_net_money": float(statistics.median(net_values)) if net_values else 0.0,
        "median_monthly_return_on_equity_pct": float(statistics.median(roe_values)) if roe_values else 0.0,
        "p25_monthly_return_on_equity_pct": float(_sample_quantile(roe_values, 0.25)) if roe_values else 0.0,
        "top1_month_return_on_equity_pct": _return_on_equity_pct(top1_net, account_equity),
        "top3_months_return_on_equity_pct": _return_on_equity_pct(top3_net, account_equity),
        "return_on_equity_ex_top1_month_pct": _return_on_equity_pct(ex_top1_net, account_equity),
        "return_on_equity_ex_top3_months_pct": _return_on_equity_pct(ex_top3_net, account_equity),
        "top1_positive_month_share": float(top1_share),
        "top3_positive_month_share": float(top3_share),
        "weak_month_floor_target_pct": 25.0,
        "weak_month_floor_pass": bool((_return_on_equity_pct(ex_top3_net, account_equity) or 0.0) >= 25.0),
    }


def scenario_metrics(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("overall_test_summary") or {}
    acceptance = report.get("acceptance") or {}
    overall = {
        "setups_total": int(summary.get("setups_total", 0) or 0),
        "filled_trades": int(summary.get("filled_trades", 0) or 0),
        "fill_rate": float(summary.get("fill_rate", 0.0) or 0.0),
        "win_rate_net": float(summary.get("win_rate_net", 0.0) or 0.0),
        "expectancy_net_ticks": float(summary.get("expectancy_net_ticks", 0.0) or 0.0),
        "expectancy_net_money": float(summary.get("expectancy_net_money", 0.0) or 0.0),
        "net_ticks_sum": float(summary.get("net_ticks_sum", 0.0) or 0.0),
        "net_money_sum": float(summary.get("net_money_sum", 0.0) or 0.0),
        "return_on_equity_pct": _float_or_none(summary.get("return_on_equity_pct")),
    }
    acceptance_metrics = {
        "passed": bool(acceptance.get("passed", False)),
        "failed_reasons": list(acceptance.get("failed_reasons") or []),
        "negative_fold_share": float(acceptance.get("negative_fold_share", 0.0) or 0.0),
        "median_fold_net_ticks": float(acceptance.get("median_fold_net_ticks", 0.0) or 0.0),
        "tail_cvar_ticks": float(acceptance.get("tail_cvar_ticks", 0.0) or 0.0),
        "overall_trades_per_week": float(acceptance.get("overall_trades_per_week", 0.0) or 0.0),
        "overall_concentration_top_share": float(acceptance.get("overall_concentration_top_share", 0.0) or 0.0),
    }
    return {
        "overall": overall,
        "acceptance": acceptance_metrics,
        "monthly": monthly_metrics(report),
    }


def comparable_metrics(metrics: dict[str, Any]) -> dict[str, float | bool | None]:
    overall = metrics.get("overall") or {}
    acceptance = metrics.get("acceptance") or {}
    monthly = metrics.get("monthly") or {}
    return {
        "net_money_sum": float(overall.get("net_money_sum", 0.0) or 0.0),
        "return_on_equity_pct": _float_or_none(overall.get("return_on_equity_pct")),
        "expectancy_net_money": float(overall.get("expectancy_net_money", 0.0) or 0.0),
        "filled_trades": float(overall.get("filled_trades", 0) or 0),
        "overall_concentration_top_share": float(acceptance.get("overall_concentration_top_share", 0.0) or 0.0),
        "median_monthly_return_on_equity_pct": float(monthly.get("median_monthly_return_on_equity_pct", 0.0) or 0.0),
        "p25_monthly_return_on_equity_pct": float(monthly.get("p25_monthly_return_on_equity_pct", 0.0) or 0.0),
        "return_on_equity_ex_top3_months_pct": float(
            monthly.get("return_on_equity_ex_top3_months_pct", 0.0) or 0.0
        ),
        "weak_month_floor_pass": bool(monthly.get("weak_month_floor_pass", False)),
    }


def metrics_delta(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    candidate_cmp = comparable_metrics(candidate)
    baseline_cmp = comparable_metrics(baseline)
    for key, value in candidate_cmp.items():
        baseline_value = baseline_cmp.get(key)
        if isinstance(value, bool):
            delta[key] = bool(value) and not bool(baseline_value)
            continue
        candidate_float = _float_or_none(value)
        baseline_float = _float_or_none(baseline_value)
        if candidate_float is None or baseline_float is None:
            delta[key] = None
        else:
            delta[key] = float(candidate_float - baseline_float)
    return delta


def run_scenarios(args: argparse.Namespace) -> dict[str, Any]:
    scenarios = [
        ScenarioRun(
            scenario_id="BASELINE_FIXED",
            label="O1 baseline, fixed lots",
            note="Frozen O1 execution baseline with legacy one-lot sizing semantics preserved.",
            reference_artifact=Path(args.baseline_reference),
            overrides={"position_sizing_mode": "fixed_lots"},
        ),
        ScenarioRun(
            scenario_id="BASELINE_RISK",
            label="O1 baseline, target risk sizing",
            note="Same O1 baseline, but lot count is sized by risk budget and instrument tick value.",
            reference_artifact=Path(args.baseline_reference),
            overrides={
                "position_sizing_mode": "target_risk_pct",
                "position_sizing_risk_pct": args.position_sizing_risk_pct,
                "position_sizing_max_contracts": args.position_sizing_max_contracts,
            },
        ),
        ScenarioRun(
            scenario_id="SCENARIO2_PRECISION_RECALL_RISK",
            label="Scenario 2, broader precision/recall families",
            note="Frozen constrained precision/recall family search rerun under risk-based lot sizing.",
            reference_artifact=Path(args.scenario2_reference),
            overrides={
                "position_sizing_mode": "target_risk_pct",
                "position_sizing_risk_pct": args.position_sizing_risk_pct,
                "position_sizing_max_contracts": args.position_sizing_max_contracts,
            },
        ),
        ScenarioRun(
            scenario_id="SCENARIO3_FLOOR_OBJECTIVE_RISK",
            label="Scenario 3, floor-oriented objective",
            note="Frozen causal-first tuned2 objective rerun under risk-based lot sizing.",
            reference_artifact=Path(args.scenario3_reference),
            overrides={
                "position_sizing_mode": "target_risk_pct",
                "position_sizing_risk_pct": args.position_sizing_risk_pct,
                "position_sizing_max_contracts": args.position_sizing_max_contracts,
            },
        ),
    ]

    scenario_payloads: list[dict[str, Any]] = []
    metrics_by_id: dict[str, dict[str, Any]] = {}
    for scenario in scenarios:
        reference = load_json(scenario.reference_artifact)
        run_artifact = ARTIFACT_DIR / f"wf_goal_v6_{scenario.scenario_id.lower()}_{DATE_STAMP}.json"
        command = build_command(reference, scenario.overrides, run_artifact)
        report, runtime_seconds = run_report(command)
        metrics = scenario_metrics(report)
        metrics_by_id[scenario.scenario_id] = metrics
        scenario_payloads.append(
            {
                "scenario_id": scenario.scenario_id,
                "label": scenario.label,
                "note": scenario.note,
                "reference_artifact": relpath(scenario.reference_artifact),
                "run_artifact": relpath(run_artifact),
                "runtime_seconds": round(runtime_seconds, 3),
                "command": command,
                "position_sizing": report.get("position_sizing") or {},
                "metrics": metrics,
            }
        )

    baseline_fixed = metrics_by_id["BASELINE_FIXED"]
    baseline_risk = metrics_by_id["BASELINE_RISK"]
    for scenario_payload in scenario_payloads:
        scenario_id = str(scenario_payload["scenario_id"])
        metrics = metrics_by_id[scenario_id]
        scenario_payload["delta_vs_baseline_fixed"] = metrics_delta(metrics, baseline_fixed)
        if scenario_id != "BASELINE_RISK":
            scenario_payload["delta_vs_baseline_risk"] = metrics_delta(metrics, baseline_risk)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "baseline_reference": relpath(Path(args.baseline_reference)),
        "scenario2_reference": relpath(Path(args.scenario2_reference)),
        "scenario3_reference": relpath(Path(args.scenario3_reference)),
        "scenarios": scenario_payloads,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rerun frozen baseline plus scenario 2/3 with corrected money-based sizing and compare weak-month metrics."
    )
    parser.add_argument("--baseline-reference", type=str, default=str(DEFAULT_BASELINE_REFERENCE))
    parser.add_argument("--scenario2-reference", type=str, default=str(DEFAULT_SCENARIO2_REFERENCE))
    parser.add_argument("--scenario3-reference", type=str, default=str(DEFAULT_SCENARIO3_REFERENCE))
    parser.add_argument("--position-sizing-risk-pct", type=float, default=None)
    parser.add_argument("--position-sizing-max-contracts", type=int, default=None)
    parser.add_argument("--out-json", type=str, default=str(DEFAULT_OUTPUT))
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    payload = run_scenarios(args)
    output_path = Path(args.out_json)
    write_json(output_path, payload)
    print("scenario_count", len(payload.get("scenarios", [])))
    print("out_json", relpath(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
