from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Sequence


def _load_verify_module():
    script_path = Path(__file__).resolve().parent / "verify_wf_hypothesis.py"
    spec = importlib.util.spec_from_file_location("verify_wf_hypothesis_module_for_batch", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed_to_load_verify_wf_hypothesis")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


VERIFY = _load_verify_module()
HypothesisFilters = VERIFY.HypothesisFilters
HypothesisGates = VERIFY.HypothesisGates
_compile_signal_tape = VERIFY._compile_signal_tape
_parse_side_slot_rules = VERIFY._parse_side_slot_rules
build_hypothesis_report = VERIFY.build_hypothesis_report


def _coerce_tokens(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [token.strip() for token in value.split(",") if token.strip()]
    if isinstance(value, (list, tuple, set)):
        tokens: list[str] = []
        for item in value:
            tokens.extend(_coerce_tokens(item))
        return tokens
    return [str(value).strip()] if str(value).strip() else []


def _upper_set(value: Any) -> frozenset[str]:
    return frozenset(token.upper() for token in _coerce_tokens(value))


def _lower_set(value: Any) -> frozenset[str]:
    return frozenset(token.lower() for token in _coerce_tokens(value))


def _slot_set(value: Any) -> frozenset[str]:
    tokens = [token for token in _coerce_tokens(value) if len(token) == 5 and token[2] == ":"]
    return frozenset(tokens)


def _with_gate_profile(gates: HypothesisGates, profile: str | None) -> HypothesisGates:
    if profile is None:
        return gates
    if profile == "stage_go":
        defaults = {
            "min_win_rate_net": 0.70,
            "min_trades_per_week": 1.50,
            "min_net_ticks_sum": 0.0,
            "max_concentration_top_share": 0.50,
        }
    elif profile == "final_go":
        defaults = {
            "min_win_rate_net": 0.75,
            "min_trades_per_week": 2.00,
            "min_net_ticks_sum": 0.0,
            "max_concentration_top_share": 0.35,
        }
    else:
        raise ValueError(f"unknown_gate_profile:{profile}")
    for key, value in defaults.items():
        if getattr(gates, key) is None:
            setattr(gates, key, value)
    return gates


def _build_global_gates(args: argparse.Namespace) -> HypothesisGates:
    gates = HypothesisGates(
        min_setups_total=args.gate_min_setups_total,
        min_filled_trades=args.gate_min_filled_trades,
        min_win_rate_net=args.gate_min_winrate_net,
        min_trades_per_week=args.gate_min_trades_per_week,
        max_trades_per_week=args.gate_max_trades_per_week,
        min_net_ticks_sum=args.gate_min_net_ticks_sum,
        min_expectancy_net_ticks=args.gate_min_expectancy_net_ticks,
        max_concentration_top_share=args.gate_max_concentration_top_share,
    )
    return _with_gate_profile(gates, args.gate_profile)


def _build_filters(candidate: dict[str, Any], *, args: argparse.Namespace) -> HypothesisFilters:
    payload = candidate.get("filters") if isinstance(candidate.get("filters"), dict) else candidate
    default_energy = _upper_set(args.cluster_energy_roots)
    default_metals = _upper_set(args.cluster_metals_roots)
    return HypothesisFilters(
        include_setup_kinds=_upper_set(payload.get("include_setup_kinds")),
        include_sides=_upper_set(payload.get("include_sides")),
        include_slots=_slot_set(payload.get("include_slots")),
        include_clusters=_lower_set(payload.get("include_clusters")),
        include_roots=_upper_set(payload.get("include_roots")),
        include_instrument_ids=_upper_set(payload.get("include_instrument_ids")),
        exclude_setup_kinds=_upper_set(payload.get("exclude_setup_kinds")),
        exclude_sides=_upper_set(payload.get("exclude_sides")),
        exclude_slots=_slot_set(payload.get("exclude_slots")),
        exclude_clusters=_lower_set(payload.get("exclude_clusters")),
        exclude_roots=_upper_set(payload.get("exclude_roots")),
        exclude_instrument_ids=_upper_set(payload.get("exclude_instrument_ids")),
        exclude_side_slots=_parse_side_slot_rules(_coerce_tokens(payload.get("exclude_side_slots"))),
        energy_roots=_upper_set(payload.get("energy_roots")) or default_energy,
        metals_roots=_upper_set(payload.get("metals_roots")) or default_metals,
    )


def _merge_gates(base_gates: HypothesisGates, candidate: dict[str, Any]) -> HypothesisGates:
    overrides = candidate.get("gates")
    if not isinstance(overrides, dict) or not overrides:
        return base_gates
    merged = copy.deepcopy(base_gates)
    for key, value in overrides.items():
        if hasattr(merged, key):
            setattr(merged, key, value)
    return merged


def _candidate_record(
    idx: int,
    candidate: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    summary = report.get("summary", {})
    acceptance = report.get("acceptance", {})
    selection = report.get("selection", {})
    return {
        "index": int(idx),
        "candidate_id": candidate.get("id"),
        "filters": candidate.get("filters", candidate),
        "selected_rows": int(selection.get("selected_rows", 0)),
        "filled_trades": int(summary.get("filled_trades", 0)),
        "win_rate_net": float(summary.get("win_rate_net", 0.0)),
        "trades_per_week": float(summary.get("trades_per_week", 0.0)),
        "net_ticks_sum": float(summary.get("net_ticks_sum", 0.0)),
        "expectancy_net_ticks": float(summary.get("expectancy_net_ticks", 0.0)),
        "concentration_top_share": float(summary.get("concentration_top_share", 0.0)),
        "passed": bool(acceptance.get("passed", False)),
        "failed_checks": [
            str(check.get("id"))
            for check in acceptance.get("checks", [])
            if isinstance(check, dict) and not bool(check.get("passed", False))
        ],
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch-evaluate many WF hypotheses on one precompiled signal tape.",
    )
    parser.add_argument("--in-json", required=True, help="Path to walk-forward report JSON.")
    parser.add_argument("--candidates-json", required=True, help="Path to candidate list JSON.")
    parser.add_argument("--out-json", required=True, help="Output path for batch results JSON.")
    parser.add_argument(
        "--tpw-period-scope",
        choices=("report", "filtered"),
        default="report",
        help="How to compute trades/week denominator.",
    )
    parser.add_argument("--gate-profile", choices=("stage_go", "final_go"), default="final_go")
    parser.add_argument("--gate-min-setups-total", type=int, default=None)
    parser.add_argument("--gate-min-filled-trades", type=int, default=None)
    parser.add_argument("--gate-min-winrate-net", type=float, default=None)
    parser.add_argument("--gate-min-trades-per-week", type=float, default=None)
    parser.add_argument("--gate-max-trades-per-week", type=float, default=None)
    parser.add_argument("--gate-min-net-ticks-sum", type=float, default=None)
    parser.add_argument("--gate-min-expectancy-net-ticks", type=float, default=None)
    parser.add_argument("--gate-max-concentration-top-share", type=float, default=None)
    parser.add_argument("--cluster-energy-roots", default="BR,NG")
    parser.add_argument("--cluster-metals-roots", default="GD,SV,PL,PT")
    parser.add_argument("--include-breakdowns", action="store_true")
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    in_path = Path(args.in_json)
    candidates_path = Path(args.candidates_json)
    report_payload = json.loads(in_path.read_text(encoding="utf-8"))
    if not isinstance(report_payload, dict):
        raise ValueError("report_json_root_must_be_object")
    raw_candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    if not isinstance(raw_candidates, list):
        raise ValueError("candidates_json_root_must_be_array")
    candidates = [item for item in raw_candidates if isinstance(item, dict)]
    base_gates = _build_global_gates(args)
    planned = report_payload.get("planned_signals")
    if not isinstance(planned, list):
        raise ValueError("report_missing_planned_signals")
    planned_rows = [row for row in planned if isinstance(row, dict)]
    tape = _compile_signal_tape(planned_rows)
    started = perf_counter()
    rows: list[dict[str, Any]] = []
    for idx, candidate in enumerate(candidates):
        filters = _build_filters(candidate, args=args)
        gates = _merge_gates(base_gates, candidate)
        result = build_hypothesis_report(
            report=report_payload,
            filters=filters,
            gates=gates,
            gate_profile=None,
            tpw_period_scope=str(args.tpw_period_scope),
            source_report_path=str(in_path),
            use_signal_tape=True,
            precompiled_tape=tape,
            collect_rejected_by_reason=False,
            include_breakdowns=bool(args.include_breakdowns),
        )
        rows.append(_candidate_record(idx, candidate, result))
    elapsed = float(perf_counter() - started)
    passed_count = int(sum(1 for row in rows if bool(row.get("passed", False))))
    ranked = sorted(
        rows,
        key=lambda row: (
            bool(row.get("passed", False)),
            float(row.get("win_rate_net", 0.0)),
            float(row.get("trades_per_week", 0.0)),
            float(row.get("net_ticks_sum", 0.0)),
            -float(row.get("concentration_top_share", 0.0)),
        ),
        reverse=True,
    )
    out_payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_report_path": str(in_path),
        "source_candidates_path": str(candidates_path),
        "engine": "tape",
        "tpw_period_scope": str(args.tpw_period_scope),
        "include_breakdowns": bool(args.include_breakdowns),
        "candidates_total": int(len(candidates)),
        "evaluated_total": int(len(rows)),
        "passed_total": int(passed_count),
        "elapsed_seconds": float(elapsed),
        "throughput_candidates_per_sec": float(len(rows) / elapsed) if elapsed > 0 else 0.0,
        "top": ranked[: max(int(args.top_k), 0)],
        "results": rows,
    }
    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.quiet:
        print("engine", "tape")
        print("candidates_total", int(len(candidates)))
        print("passed_total", int(passed_count))
        print("elapsed_seconds", round(float(elapsed), 6))
        print("throughput_candidates_per_sec", round(float(out_payload["throughput_candidates_per_sec"]), 2))
        print("out_json", str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
