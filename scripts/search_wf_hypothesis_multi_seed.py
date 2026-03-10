from __future__ import annotations

import argparse
import importlib.util
import json
import random
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Sequence


def _load_verify_module():
    script_path = Path(__file__).resolve().parent / "verify_wf_hypothesis.py"
    spec = importlib.util.spec_from_file_location("verify_wf_hypothesis_module_for_multiseed", script_path)
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
_instrument_root = VERIFY._instrument_root
build_hypothesis_report = VERIFY.build_hypothesis_report


@dataclass(frozen=True)
class ReportRuntime:
    path: str
    payload: dict[str, Any]
    tape: Any


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
    text = str(value).strip()
    return [text] if text else []


def _parse_gate_profile(profile: str) -> HypothesisGates:
    gate = HypothesisGates()
    if profile == "stage_go":
        gate.min_win_rate_net = 0.70
        gate.min_trades_per_week = 1.50
        gate.min_net_ticks_sum = 0.0
        gate.max_concentration_top_share = 0.50
    elif profile == "final_go":
        gate.min_win_rate_net = 0.75
        gate.min_trades_per_week = 2.00
        gate.min_net_ticks_sum = 0.0
        gate.max_concentration_top_share = 0.35
    else:
        raise ValueError(f"unknown_gate_profile:{profile}")
    return gate


def _collect_universe(payloads: list[dict[str, Any]]) -> dict[str, list[str]]:
    setup_kinds: set[str] = set()
    slots: set[str] = set()
    roots: set[str] = set()
    instruments: set[str] = set()
    for payload in payloads:
        planned = payload.get("planned_signals")
        if not isinstance(planned, list):
            continue
        for row in planned:
            if not isinstance(row, dict):
                continue
            setup = str(row.get("setup_kind", "")).strip().upper()
            if setup:
                setup_kinds.add(setup)
            as_of = str(row.get("as_of_ts", "")).strip()
            if "T" in as_of and len(as_of) >= 16:
                slots.add(as_of.split("T", 1)[1][:5])
            instrument = str(row.get("instrument_id", "")).strip().upper()
            if instrument:
                instruments.add(instrument)
                roots.add(_instrument_root(instrument))
    return {
        "setup_kinds": sorted(setup_kinds),
        "slots": sorted(slots),
        "roots": sorted(roots),
        "instruments": sorted(instruments),
        "sides": ["BUY", "SELL"],
        "clusters": ["energy", "metals", "other"],
    }


def _sample_subset(
    rng: random.Random,
    values: list[str],
    *,
    min_size: int,
    max_size: int,
    preferred: list[str] | None = None,
) -> list[str]:
    if not values:
        return []
    upper = min(max_size, len(values))
    lower = min(max(min_size, 0), upper)
    if upper <= 0:
        return []
    size = rng.randint(lower, upper)
    if size <= 0:
        return []
    if preferred and rng.random() < 0.65:
        pref = [item for item in preferred if item in values]
        if pref:
            pref_count = min(len(pref), max(size - 1, 1))
            picked_pref = rng.sample(pref, pref_count)
            remaining = [item for item in values if item not in picked_pref]
            extra = rng.sample(remaining, max(0, size - len(picked_pref))) if remaining else []
            return sorted(picked_pref + extra)
    return sorted(rng.sample(values, size))


def _candidate_signature(candidate: dict[str, Any]) -> str:
    return json.dumps(candidate, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def _candidate_to_filters(candidate: dict[str, Any]) -> Any:
    exclude_side_slots = frozenset(
        tuple(token.split("@", 1))
        for token in _coerce_tokens(candidate.get("exclude_side_slots"))
        if "@" in token
    )
    return HypothesisFilters(
        include_setup_kinds=frozenset(token.upper() for token in _coerce_tokens(candidate.get("include_setup_kinds"))),
        include_sides=frozenset(token.upper() for token in _coerce_tokens(candidate.get("include_sides"))),
        include_slots=frozenset(_coerce_tokens(candidate.get("include_slots"))),
        include_clusters=frozenset(token.lower() for token in _coerce_tokens(candidate.get("include_clusters"))),
        include_roots=frozenset(token.upper() for token in _coerce_tokens(candidate.get("include_roots"))),
        include_instrument_ids=frozenset(token.upper() for token in _coerce_tokens(candidate.get("include_instrument_ids"))),
        exclude_setup_kinds=frozenset(token.upper() for token in _coerce_tokens(candidate.get("exclude_setup_kinds"))),
        exclude_sides=frozenset(token.upper() for token in _coerce_tokens(candidate.get("exclude_sides"))),
        exclude_slots=frozenset(_coerce_tokens(candidate.get("exclude_slots"))),
        exclude_clusters=frozenset(token.lower() for token in _coerce_tokens(candidate.get("exclude_clusters"))),
        exclude_roots=frozenset(token.upper() for token in _coerce_tokens(candidate.get("exclude_roots"))),
        exclude_instrument_ids=frozenset(token.upper() for token in _coerce_tokens(candidate.get("exclude_instrument_ids"))),
        exclude_side_slots=exclude_side_slots,
    )


def _candidate_generator(
    *,
    universe: dict[str, list[str]],
    count: int,
    seed: int,
) -> list[dict[str, Any]]:
    rng = random.Random(int(seed))
    side_slots = [f"{side}@{slot}" for side in universe["sides"] for slot in universe["slots"]]
    emitted: list[dict[str, Any]] = []
    seen: set[str] = set()
    attempts = 0
    max_attempts = max(int(count) * 20, 2000)
    while len(emitted) < int(count) and attempts < max_attempts:
        attempts += 1
        include_setup_kinds = _sample_subset(
            rng,
            universe["setup_kinds"],
            min_size=1,
            max_size=min(2, len(universe["setup_kinds"])),
            preferred=["ORB_BREAKOUT", "EMA_PULLBACK_LIMIT"],
        )
        include_slots = _sample_subset(
            rng,
            universe["slots"],
            min_size=1,
            max_size=min(3, len(universe["slots"])),
            preferred=["12:00", "14:15"],
        )
        include_clusters = _sample_subset(
            rng,
            universe["clusters"],
            min_size=1,
            max_size=min(2, len(universe["clusters"])),
            preferred=["other", "energy"],
        )
        include_roots = _sample_subset(
            rng,
            universe["roots"],
            min_size=min(6, len(universe["roots"])),
            max_size=min(22, len(universe["roots"])),
        )
        include_instrument_ids: list[str] = []
        if rng.random() < 0.1:
            include_instrument_ids = _sample_subset(
                rng,
                universe["instruments"],
                min_size=1,
                max_size=min(4, len(universe["instruments"])),
            )
        exclude_side_slots: list[str] = []
        if side_slots and rng.random() < 0.35:
            exclude_side_slots = _sample_subset(
                rng,
                side_slots,
                min_size=1,
                max_size=1,
            )
        candidate = {
            "include_setup_kinds": include_setup_kinds,
            "include_slots": include_slots,
            "include_clusters": include_clusters,
            "include_roots": include_roots,
            "include_instrument_ids": include_instrument_ids,
            "exclude_side_slots": exclude_side_slots,
        }
        signature = _candidate_signature(candidate)
        if signature in seen:
            continue
        seen.add(signature)
        emitted.append(candidate)
    return emitted


def _objective_row(
    *,
    candidate: dict[str, Any],
    per_report: list[dict[str, Any]],
) -> dict[str, Any]:
    passes = int(sum(1 for row in per_report if bool(row.get("passed", False))))
    wins = [float(row.get("win_rate_net", 0.0)) for row in per_report]
    tpws = [float(row.get("trades_per_week", 0.0)) for row in per_report]
    nets = [float(row.get("net_ticks_sum", 0.0)) for row in per_report]
    tops = [float(row.get("concentration_top_share", 0.0)) for row in per_report]
    min_win = min(wins) if wins else 0.0
    min_tpw = min(tpws) if tpws else 0.0
    min_net = min(nets) if nets else 0.0
    max_top = max(tops) if tops else 1.0
    win_std = float(statistics.pstdev(wins)) if len(wins) > 1 else 0.0
    tpw_std = float(statistics.pstdev(tpws)) if len(tpws) > 1 else 0.0
    score = (
        float(passes) * 1000.0
        + float(min_win) * 100.0
        + float(min_tpw) * 50.0
        + float(min_net) * 0.005
        - max(float(max_top) - 0.35, 0.0) * 120.0
        - float(win_std) * 30.0
        - float(tpw_std) * 10.0
    )
    return {
        "candidate": candidate,
        "per_report": per_report,
        "passes": int(passes),
        "min_win_rate_net": float(min_win),
        "min_trades_per_week": float(min_tpw),
        "min_net_ticks_sum": float(min_net),
        "max_concentration_top_share": float(max_top),
        "win_rate_std": float(win_std),
        "trades_per_week_std": float(tpw_std),
        "score": float(score),
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Multi-seed causal-first search for WF hypothesis filters using tape engine.",
    )
    parser.add_argument(
        "--in-json",
        action="append",
        required=True,
        help="Path to a walk-forward report JSON; provide multiple times for multi-seed robustness.",
    )
    parser.add_argument("--out-json", required=True, help="Output artifact path.")
    parser.add_argument("--gate-profile", choices=("stage_go", "final_go"), default="final_go")
    parser.add_argument("--tpw-period-scope", choices=("report", "filtered"), default="report")
    parser.add_argument("--candidates", type=int, default=50000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--require-passes", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report_paths = [Path(item) for item in args.in_json]
    runtimes: list[ReportRuntime] = []
    for path in report_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"report_json_root_must_be_object:{path}")
        planned = payload.get("planned_signals")
        if not isinstance(planned, list):
            raise ValueError(f"report_missing_planned_signals:{path}")
        planned_rows = [row for row in planned if isinstance(row, dict)]
        runtimes.append(
            ReportRuntime(
                path=str(path),
                payload=payload,
                tape=_compile_signal_tape(planned_rows),
            )
        )
    if not runtimes:
        raise ValueError("empty_reports")
    gate = _parse_gate_profile(str(args.gate_profile))
    require_passes = int(args.require_passes) if int(args.require_passes) > 0 else len(runtimes)
    universe = _collect_universe([item.payload for item in runtimes])
    candidates = _candidate_generator(
        universe=universe,
        count=max(int(args.candidates), 1),
        seed=int(args.seed),
    )
    started = perf_counter()
    evaluated = 0
    pruned = 0
    all_rows: list[dict[str, Any]] = []
    feasible_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        evaluated += 1
        filters = _candidate_to_filters(candidate)
        per_report: list[dict[str, Any]] = []
        passes = 0
        pruned_now = False
        for idx, runtime in enumerate(runtimes):
            report = build_hypothesis_report(
                report=runtime.payload,
                filters=filters,
                gates=gate,
                gate_profile=None,
                tpw_period_scope=str(args.tpw_period_scope),
                source_report_path=str(runtime.path),
                use_signal_tape=True,
                precompiled_tape=runtime.tape,
                collect_rejected_by_reason=False,
                include_breakdowns=False,
            )
            summary = report.get("summary", {})
            acceptance = report.get("acceptance", {})
            passed = bool(acceptance.get("passed", False))
            if passed:
                passes += 1
            per_report.append(
                {
                    "path": runtime.path,
                    "passed": passed,
                    "selected_rows": int(report.get("selection", {}).get("selected_rows", 0)),
                    "filled_trades": int(summary.get("filled_trades", 0)),
                    "win_rate_net": float(summary.get("win_rate_net", 0.0)),
                    "trades_per_week": float(summary.get("trades_per_week", 0.0)),
                    "net_ticks_sum": float(summary.get("net_ticks_sum", 0.0)),
                    "concentration_top_share": float(summary.get("concentration_top_share", 0.0)),
                }
            )
            remaining = len(runtimes) - (idx + 1)
            if (passes + remaining) < require_passes:
                pruned += 1
                pruned_now = True
                break
        row = _objective_row(candidate=candidate, per_report=per_report)
        row["pruned"] = bool(pruned_now)
        all_rows.append(row)
        if row["passes"] >= require_passes:
            feasible_rows.append(row)
    elapsed = float(perf_counter() - started)
    ranked = sorted(
        all_rows,
        key=lambda row: (
            int(row.get("passes", 0)),
            float(row.get("score", float("-inf"))),
            float(row.get("min_win_rate_net", 0.0)),
            float(row.get("min_trades_per_week", 0.0)),
            float(row.get("min_net_ticks_sum", 0.0)),
        ),
        reverse=True,
    )
    out = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "engine": "tape",
        "gate_profile": str(args.gate_profile),
        "require_passes": int(require_passes),
        "reports": [runtime.path for runtime in runtimes],
        "candidates_total": int(len(candidates)),
        "evaluated_total": int(evaluated),
        "pruned_early_total": int(pruned),
        "feasible_total": int(len(feasible_rows)),
        "elapsed_seconds": float(elapsed),
        "throughput_candidates_per_sec": float(evaluated / elapsed) if elapsed > 0 else 0.0,
        "top": ranked[: max(int(args.top_k), 0)],
    }
    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.quiet:
        print("reports", len(runtimes))
        print("require_passes", int(require_passes))
        print("candidates_total", int(len(candidates)))
        print("feasible_total", int(len(feasible_rows)))
        print("pruned_early_total", int(pruned))
        print("elapsed_seconds", round(float(elapsed), 6))
        print("throughput_candidates_per_sec", round(float(out["throughput_candidates_per_sec"]), 2))
        print("out_json", str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
