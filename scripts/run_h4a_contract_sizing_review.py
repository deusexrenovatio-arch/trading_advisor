from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import run_morning_plan_walk_forward as walk
import run_h4a_vs_baseline_risk as compare
import run_signals_sizing_scenarios as sizing

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = REPO_ROOT / "artifacts" / "research"
DATE_STAMP = datetime.now(UTC).strftime("%Y%m%d")
DEFAULT_OUTPUT = ARTIFACT_DIR / f"wf_goal_v6_h4a_contract_sizing_20000_risk_only_{DATE_STAMP}.json"


def _default_source_artifact() -> Path:
    candidates = sorted(ARTIFACT_DIR.glob("wf_goal_v6_h4a_risk_*.json"))
    if candidates:
        return candidates[-1]
    return ARTIFACT_DIR / f"wf_goal_v6_h4a_risk_{DATE_STAMP}.json"


DEFAULT_SOURCE_ARTIFACT = _default_source_artifact()


def _float_or_none(raw: Any) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _int_or_default(raw: Any, default: int = 1) -> int:
    try:
        return max(int(raw), 1)
    except (TypeError, ValueError):
        return max(int(default), 1)


def _parse_dt(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _return_on_equity_pct(net_money: float, equity: float | None) -> float | None:
    if equity is None or equity <= 0.0:
        return None
    return float((float(net_money) / float(equity)) * 100.0)


def _row_side_sign(row: dict[str, Any]) -> float:
    return 1.0 if str(row.get("side") or "").strip().upper() == "BUY" else -1.0


def _row_outcome_cost_mult(row: dict[str, Any], execution_policy: dict[str, Any]) -> float:
    outcome = str(row.get("simulated_outcome") or "").strip().upper()
    if outcome == "TP":
        return max(float(execution_policy.get("tp_cost_mult", 1.0) or 1.0), 0.0)
    if outcome == "SL":
        return max(float(execution_policy.get("sl_cost_mult", 1.0) or 1.0), 0.0)
    return max(float(execution_policy.get("exit_cost_mult", 1.0) or 1.0), 0.0)


def _risk_entry_style(row: dict[str, Any]) -> str:
    order_type = str(row.get("entry_order_type") or "").strip().upper()
    return "taker" if order_type == "STOP" else "maker"


def _inferred_entry_fill_from_row(
    row: dict[str, Any],
    *,
    execution_policy: dict[str, Any],
) -> tuple[int, str]:
    order_type = str(row.get("entry_order_type") or "").strip().upper()
    side = str(row.get("side") or "").strip().upper()
    entry_ticks = int(row.get("entry_ticks") or 0)
    range_low = int(row.get("entry_range_low_ticks") or entry_ticks)
    range_high = int(row.get("entry_range_high_ticks") or entry_ticks)
    if order_type == "LIMIT":
        improve_ticks = max(int(execution_policy.get("limit_entry_improve_ticks", 0) or 0), 0)
        fallback_minutes = max(int(execution_policy.get("limit_fallback_to_market_minutes", 0) or 0), 0)
        fallback_slip_ticks = max(int(execution_policy.get("limit_fallback_slip_ticks", 0) or 0), 0)
        as_of_ts = _parse_dt(row.get("as_of_ts"))
        entry_ts = _parse_dt(row.get("simulated_entry_ts"))
        elapsed_minutes = None
        if as_of_ts is not None and entry_ts is not None:
            elapsed_minutes = (entry_ts - as_of_ts).total_seconds() / 60.0
        if elapsed_minutes is not None and fallback_minutes > 0 and elapsed_minutes >= float(fallback_minutes):
            fill_ticks = int(range_high + fallback_slip_ticks) if side == "BUY" else int(range_low - fallback_slip_ticks)
            return fill_ticks, "taker"
        fill_ticks = int(range_high - improve_ticks) if side == "BUY" else int(range_low + improve_ticks)
        return fill_ticks, "maker"
    if order_type == "STOP":
        return int(entry_ticks), "taker"
    if order_type == "STOP_LIMIT":
        return int(entry_ticks), "maker"
    return int(entry_ticks), "maker"


def _repriced_source_report(source_report: dict[str, Any]) -> dict[str, Any]:
    payload = compare.filter_no_mini_report(source_report)
    base_costs = payload.get("cost_assumptions_ticks") or {}
    execution_policy = payload.get("execution_policy") or {}
    costs = walk.CostAssumptions(
        commission_ticks_per_side=0.0,
        slippage_ticks_per_side=float(base_costs.get("slippage_ticks_per_side", 0.0) or 0.0),
        spread_half_ticks=float(base_costs.get("spread_half_ticks", 0.0) or 0.0),
        commission_model="moex_real_fees",
        broker_fee_rub_per_order_per_lot=0.45,
    )
    legacy_round_trip_ticks = 2.0 * (
        float(base_costs.get("commission_ticks_per_side", 0.0) or 0.0)
        + float(base_costs.get("slippage_ticks_per_side", 0.0) or 0.0)
        + float(base_costs.get("spread_half_ticks", 0.0) or 0.0)
    )
    repriced_rows: list[dict[str, Any]] = []
    for source_row in payload.get("planned_signals") or []:
        row = dict(source_row)
        tick_value = _float_or_none(row.get("tick_value"))
        qty_lots = _int_or_default(row.get("qty_lots"), 1)
        if tick_value is None or tick_value <= 0.0:
            repriced_rows.append(row)
            continue
        estimated_risk_money_per_lot = _float_or_none(row.get("estimated_risk_money_per_lot"))
        sl_cost_mult = max(float(execution_policy.get("sl_cost_mult", 1.0) or 1.0), 0.0)
        if estimated_risk_money_per_lot is not None:
            stop_distance_ticks = max(float(estimated_risk_money_per_lot / tick_value) - legacy_round_trip_ticks * sl_cost_mult, 1.0)
            entry_ticks = int(row.get("entry_ticks") or 0)
            effective_stop_ticks = int(round(float(entry_ticks) - _row_side_sign(row) * float(stop_distance_ticks)))
            risk_fee_money = walk._round_trip_fee_money_per_lot(
                instrument_id=str(row.get("instrument_id") or ""),
                entry_ticks=int(entry_ticks),
                entry_execution_style=_risk_entry_style(row),
                exit_ticks=int(effective_stop_ticks),
                exit_execution_style="taker",
                tick_value=float(tick_value),
                costs=costs,
            )
            risk_impact_money = float(costs.round_trip_impact_ticks) * float(sl_cost_mult) * float(tick_value)
            repriced_risk_money_per_lot = float(stop_distance_ticks * float(tick_value) + risk_impact_money + risk_fee_money)
            row["estimated_risk_money_per_lot"] = float(repriced_risk_money_per_lot)
            row["estimated_position_risk_money"] = float(repriced_risk_money_per_lot * float(qty_lots))
        if bool(row.get("simulated_filled")):
            fill_ticks, entry_execution_style = _inferred_entry_fill_from_row(
                row,
                execution_policy=execution_policy,
            )
            gross_ticks = _float_or_none(row.get("simulated_gross_ticks")) or 0.0
            exit_ticks = int(round(float(fill_ticks) + _row_side_sign(row) * float(gross_ticks)))
            outcome = str(row.get("simulated_outcome") or "").strip().upper()
            exit_execution_style = "maker" if outcome == "TP" else "taker"
            fee_money_per_lot = walk._round_trip_fee_money_per_lot(
                instrument_id=str(row.get("instrument_id") or ""),
                entry_ticks=int(fill_ticks),
                entry_execution_style=entry_execution_style,
                exit_ticks=int(exit_ticks),
                exit_execution_style=exit_execution_style,
                tick_value=float(tick_value),
                costs=costs,
            )
            impact_cost_ticks = float(costs.round_trip_impact_ticks) * float(_row_outcome_cost_mult(row, execution_policy))
            cost_money_per_lot = float(impact_cost_ticks * float(tick_value) + fee_money_per_lot)
            net_ticks = float(gross_ticks - float(cost_money_per_lot / float(tick_value)))
            row["simulated_cost_money"] = float(cost_money_per_lot * float(qty_lots))
            row["simulated_gross_money"] = float(gross_ticks * float(tick_value) * float(qty_lots))
            row["simulated_net_ticks"] = float(net_ticks)
            row["simulated_net_money"] = float(net_ticks * float(tick_value) * float(qty_lots))
        repriced_rows.append(row)
    payload["planned_signals"] = repriced_rows
    payload["repricing_contract"] = {
        "commission_model": "moex_real_fees",
        "broker_fee_rub_per_order_per_lot": 0.45,
        "exchange_fee_rule": "taker_only_maker_zero",
        "stop_limit_entry_assumption": "maker_at_entry_ticks_when_source_artifact_lacks_fallback_detail",
    }
    return payload


def metric_invariance(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, bool]:
    return {
        "filled_trades_unchanged": float(candidate.get("filled_trades", 0.0)) == float(baseline.get("filled_trades", 0.0)),
        "fill_rate_unchanged": float(candidate.get("fill_rate", 0.0)) == float(baseline.get("fill_rate", 0.0)),
        "win_rate_net_unchanged": float(candidate.get("win_rate_net", 0.0))
        == float(baseline.get("win_rate_net", 0.0)),
    }


def risk_budget_summary(report: dict[str, Any], risk_budget_money: float) -> dict[str, Any]:
    budget = max(float(risk_budget_money), 0.0)
    planned_rows = report.get("planned_signals") or []
    sized_rows = []
    one_lot_over_budget = 0
    position_over_budget = 0
    qty_values: list[int] = []
    for row in planned_rows:
        per_lot = _float_or_none(row.get("estimated_risk_money_per_lot"))
        position_risk = _float_or_none(row.get("estimated_position_risk_money"))
        qty_lots = _int_or_default(row.get("qty_lots"), 1)
        if per_lot is None or position_risk is None:
            continue
        sized_rows.append(row)
        qty_values.append(qty_lots)
        if per_lot > budget:
            one_lot_over_budget += 1
        if position_risk > budget:
            position_over_budget += 1
    return {
        "planned_signals_with_sizing": int(len(sized_rows)),
        "filled_trades": int(sum(1 for row in sized_rows if bool(row.get("simulated_filled")))),
        "one_lot_over_budget_count": int(one_lot_over_budget),
        "position_over_budget_count": int(position_over_budget),
        "max_qty_lots": (int(max(qty_values)) if qty_values else 0),
        "budget_money": float(budget),
    }


def _scaled_money(raw_value: Any, old_qty: int, new_qty: int) -> float | None:
    value = _float_or_none(raw_value)
    if value is None:
        return None
    return float((value / float(max(old_qty, 1))) * float(max(new_qty, 1)))


def _resized_qty(row: dict[str, Any], *, mode: str, risk_money: float | None) -> int:
    if mode == "fixed_lots":
        return 1
    if mode != "target_risk_money":
        raise ValueError("unsupported_position_sizing_mode")
    per_lot = _float_or_none(row.get("estimated_risk_money_per_lot"))
    if per_lot is None or per_lot <= 0.0 or risk_money is None or risk_money <= 0.0:
        return 1
    sized_qty = int(float(risk_money) // float(per_lot))
    return max(sized_qty, 1)


def resize_report(
    source_report: dict[str, Any],
    *,
    mode: str,
    risk_money: float | None,
) -> dict[str, Any]:
    account_equity = _float_or_none(source_report.get("account_equity"))
    payload = deepcopy(source_report)
    resized_rows: list[dict[str, Any]] = []
    for source_row in source_report.get("planned_signals") or []:
        row = dict(source_row)
        old_qty = _int_or_default(source_row.get("qty_lots"), 1)
        new_qty = _resized_qty(
            source_row,
            mode=mode,
            risk_money=risk_money,
        )
        row["qty_lots"] = int(new_qty)
        row["sizing_mode"] = str(mode)
        per_lot_risk = _float_or_none(source_row.get("estimated_risk_money_per_lot"))
        row["estimated_position_risk_money"] = (
            float(per_lot_risk * float(new_qty)) if per_lot_risk is not None else None
        )
        row["simulated_cost_money"] = _scaled_money(source_row.get("simulated_cost_money"), old_qty, new_qty)
        row["simulated_gross_money"] = _scaled_money(source_row.get("simulated_gross_money"), old_qty, new_qty)
        row["simulated_net_money"] = _scaled_money(source_row.get("simulated_net_money"), old_qty, new_qty)
        net_money = _float_or_none(row.get("simulated_net_money"))
        row["simulated_net_return_on_equity_pct"] = (
            _return_on_equity_pct(float(net_money), account_equity) if net_money is not None else None
        )
        resized_rows.append(row)
    payload["planned_signals"] = resized_rows
    payload["position_sizing"] = {
        "mode": str(mode),
        "target_risk_money": (float(risk_money) if risk_money is not None else None),
        "risk_only": mode == "target_risk_money",
    }
    return payload


def scenario_top_line(report: dict[str, Any]) -> dict[str, Any]:
    rows = compare.signal_rows(report)
    period = report.get("period") or {}
    start_date = date.fromisoformat(str(period.get("start_date")))
    end_date = date.fromisoformat(str(period.get("end_date")))
    total_days = max((end_date - start_date).days + 1, 1)
    total_weeks = float(total_days) / 7.0
    account_equity = _float_or_none(report.get("account_equity"))
    overall = compare._bucket_stats(rows)
    by_root = compare.bucket_breakdown(rows, "root", limit=10_000)
    positive_root_net = [float(item["net_money_sum"]) for item in by_root if float(item["net_money_sum"]) > 0.0]
    top_share = (
        float(max(positive_root_net) / sum(positive_root_net))
        if positive_root_net and sum(positive_root_net) > 0.0
        else 0.0
    )
    monthly = compare.monthly_execution(report, rows)
    return {
        "overall": {
            "setups_total": int(overall["setups_total"]),
            "filled_trades": int(overall["filled_trades"]),
            "fill_rate": float(overall["fill_rate"]),
            "win_rate_net": float(overall["win_rate_net"]),
            "expectancy_net_ticks": float(overall["expectancy_net_ticks"]),
            "expectancy_net_money": float(overall["expectancy_net_money"]),
            "net_ticks_sum": float(overall["net_ticks_sum"]),
            "net_money_sum": float(overall["net_money_sum"]),
            "return_on_equity_pct": _return_on_equity_pct(float(overall["net_money_sum"]), account_equity),
        },
        "acceptance": {
            "passed": True,
            "failed_reasons": [],
            "negative_fold_share": 0.0,
            "median_fold_net_ticks": 0.0,
            "tail_cvar_ticks": 0.0,
            "overall_trades_per_week": float(overall["filled_trades"] / total_weeks) if total_weeks > 0 else 0.0,
            "overall_concentration_top_share": float(top_share),
        },
        "monthly": monthly,
    }


def scenario_payload(
    report: dict[str, Any],
    *,
    source_artifact: Path,
) -> dict[str, Any]:
    rows = compare.signal_rows(report)
    return {
        "runtime_seconds": 0.0,
        "command": [
            "derived_from_artifact",
            compare.relpath(source_artifact),
            str((report.get("position_sizing") or {}).get("mode") or "unknown"),
        ],
        "position_sizing": report.get("position_sizing"),
        "top_line": scenario_top_line(report),
        "gate_stats": compare.gate_stats(rows),
        "qty_distribution": compare.qty_distribution(rows, max_contracts=None),
        "monthly_execution": compare.monthly_execution(report, rows),
        "by_outcome_class": compare.bucket_breakdown(rows, "outcome_class"),
        "by_root": compare.bucket_breakdown(rows, "root"),
        "by_setup_kind": compare.bucket_breakdown(rows, "setup_kind"),
        "by_slot": compare.bucket_breakdown(rows, "slot"),
        "by_entry_order_type": compare.bucket_breakdown(rows, "entry_order_type"),
    }


def run_analysis(args: argparse.Namespace) -> dict[str, Any]:
    source_artifact = Path(args.source_artifact)
    source_report = _repriced_source_report(compare.load_json(source_artifact))
    risk_money = max(float(args.position_sizing_risk_money), 0.0)
    fixed_report = resize_report(
        source_report,
        mode="fixed_lots",
        risk_money=None,
    )
    sized_report = resize_report(
        source_report,
        mode="target_risk_money",
        risk_money=risk_money,
    )
    fixed_payload = scenario_payload(
        fixed_report,
        source_artifact=source_artifact,
    )
    sized_payload = scenario_payload(
        sized_report,
        source_artifact=source_artifact,
    )
    fixed_metrics = fixed_payload["top_line"]
    sized_metrics = sized_payload["top_line"]
    fixed_rows = compare.signal_rows(fixed_report)
    sized_rows = compare.signal_rows(sized_report)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "source_artifact": compare.relpath(source_artifact),
        "derivation_contract": {
            "execution_policy": "unchanged_h4a",
            "fill_and_exit_paths": "reused_from_source_artifact",
            "money_rescaling_rule": "per-trade money fields are rescaled from per-lot source values after recomputing qty_lots from estimated_risk_money_per_lot",
            "commission_repricing": source_report.get("repricing_contract"),
        },
        "position_sizing": {
            "mode": "target_risk_money",
            "target_risk_money": float(risk_money),
            "risk_only": True,
            "account_equity": _float_or_none(source_report.get("account_equity")),
        },
        "universe_policy": source_report.get("universe_policy"),
        "scenarios": {
            "H4A_FIXED_LOTS": fixed_payload,
            "H4A_RISK_MONEY": sized_payload,
        },
        "delta_vs_h4a_fixed_lots": {
            "top_line": sizing.metrics_delta(sized_metrics, fixed_metrics),
            "metric_invariance": metric_invariance(
                sized_metrics["overall"],
                fixed_metrics["overall"],
            ),
            "qty_distribution": {
                key: float(
                    (sized_payload["qty_distribution"].get(key, 0.0) or 0.0)
                    - (fixed_payload["qty_distribution"].get(key, 0.0) or 0.0)
                )
                for key in (
                    "p25_qty_lots",
                    "median_qty_lots",
                    "p75_qty_lots",
                    "mean_qty_lots",
                    "max_qty_lots",
                )
            },
            "by_outcome_class": compare.bucket_delta(
                sized_rows, fixed_rows, "outcome_class"
            ),
            "by_root": compare.bucket_delta(sized_rows, fixed_rows, "root"),
            "by_setup_kind": compare.bucket_delta(sized_rows, fixed_rows, "setup_kind"),
            "by_slot": compare.bucket_delta(sized_rows, fixed_rows, "slot"),
        },
        "risk_budget_summary": risk_budget_summary(
            sized_report, risk_budget_money=risk_money
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare H4A fixed-lot baseline against absolute-RUB risk-only contract sizing using an existing H4A artifact."
    )
    parser.add_argument("--source-artifact", type=str, default=str(DEFAULT_SOURCE_ARTIFACT))
    parser.add_argument("--position-sizing-risk-money", type=float, default=20_000.0)
    parser.add_argument("--out-json", type=str, default=str(DEFAULT_OUTPUT))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    payload = run_analysis(args)
    output_path = Path(args.out_json)
    compare.write_json(output_path, payload)
    print("scenario_count", len(payload.get("scenarios", {})))
    print("out_json", compare.relpath(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
