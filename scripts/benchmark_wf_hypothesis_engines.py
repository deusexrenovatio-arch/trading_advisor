from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Sequence


def _load_verify_module():
    script_path = Path(__file__).resolve().parent / "verify_wf_hypothesis.py"
    spec = importlib.util.spec_from_file_location("verify_wf_hypothesis_module_for_benchmark", script_path)
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


def _collect_universe(report: dict[str, Any]) -> dict[str, list[str]]:
    planned = report.get("planned_signals")
    if not isinstance(planned, list):
        raise ValueError("report_missing_planned_signals")
    rows = [row for row in planned if isinstance(row, dict)]
    setup_kinds = sorted({str(row.get("setup_kind", "")).strip().upper() for row in rows if row.get("setup_kind")})
    slots = sorted(
        {
            str(row.get("as_of_ts", "")).split("T", 1)[1][:5]
            for row in rows
            if isinstance(row.get("as_of_ts"), str) and "T" in str(row.get("as_of_ts"))
        }
    )
    roots = sorted(
        {
            _instrument_root(str(row.get("instrument_id", "")).strip().upper())
            for row in rows
            if str(row.get("instrument_id", "")).strip()
        }
    )
    instruments = sorted({str(row.get("instrument_id", "")).strip().upper() for row in rows if row.get("instrument_id")})
    return {
        "setup_kinds": setup_kinds,
        "slots": slots,
        "roots": roots,
        "instruments": instruments,
        "clusters": ["energy", "metals", "other"],
        "sides": ["BUY", "SELL"],
    }


def _sample_subset(rng: random.Random, values: list[str], *, min_size: int, max_size: int) -> list[str]:
    if not values:
        return []
    upper = min(max_size, len(values))
    lower = min(max(min_size, 0), upper)
    if upper <= 0:
        return []
    size = rng.randint(lower, upper)
    if size <= 0:
        return []
    return sorted(rng.sample(values, size))


def _generate_candidates(
    *,
    universe: dict[str, list[str]],
    candidates_total: int,
    seed: int,
) -> list[dict[str, Any]]:
    rng = random.Random(int(seed))
    side_slots = [f"{side}@{slot}" for side in universe["sides"] for slot in universe["slots"]]
    generated: list[dict[str, Any]] = []
    signatures: set[str] = set()
    attempts = 0
    max_attempts = max(int(candidates_total) * 10, 1000)
    while len(generated) < int(candidates_total) and attempts < max_attempts:
        attempts += 1
        include_setup = _sample_subset(rng, universe["setup_kinds"], min_size=1, max_size=min(2, len(universe["setup_kinds"])))
        include_slots = _sample_subset(rng, universe["slots"], min_size=1, max_size=min(3, len(universe["slots"])))
        include_clusters = _sample_subset(rng, universe["clusters"], min_size=1, max_size=min(2, len(universe["clusters"])))
        include_roots = _sample_subset(rng, universe["roots"], min_size=3, max_size=min(18, len(universe["roots"])))
        include_instruments: list[str] = []
        if rng.random() < 0.2:
            include_instruments = _sample_subset(
                rng,
                universe["instruments"],
                min_size=1,
                max_size=min(4, len(universe["instruments"])),
            )
        exclude_side_slots: list[str] = []
        if side_slots and rng.random() < 0.5:
            exclude_side_slots = _sample_subset(rng, side_slots, min_size=1, max_size=1)
        candidate = {
            "include_setup_kinds": include_setup,
            "include_slots": include_slots,
            "include_clusters": include_clusters,
            "include_roots": include_roots,
            "include_instrument_ids": include_instruments,
            "exclude_side_slots": exclude_side_slots,
        }
        signature = json.dumps(candidate, sort_keys=True, ensure_ascii=True)
        if signature in signatures:
            continue
        signatures.add(signature)
        generated.append(candidate)
    return generated


def _filters_from_candidate(candidate: dict[str, Any]) -> HypothesisFilters:
    return HypothesisFilters(
        include_setup_kinds=frozenset(_coerce_tokens(candidate.get("include_setup_kinds"))),
        include_sides=frozenset(_coerce_tokens(candidate.get("include_sides"))),
        include_slots=frozenset(_coerce_tokens(candidate.get("include_slots"))),
        include_clusters=frozenset(token.lower() for token in _coerce_tokens(candidate.get("include_clusters"))),
        include_roots=frozenset(token.upper() for token in _coerce_tokens(candidate.get("include_roots"))),
        include_instrument_ids=frozenset(token.upper() for token in _coerce_tokens(candidate.get("include_instrument_ids"))),
        exclude_setup_kinds=frozenset(_coerce_tokens(candidate.get("exclude_setup_kinds"))),
        exclude_sides=frozenset(_coerce_tokens(candidate.get("exclude_sides"))),
        exclude_slots=frozenset(_coerce_tokens(candidate.get("exclude_slots"))),
        exclude_clusters=frozenset(token.lower() for token in _coerce_tokens(candidate.get("exclude_clusters"))),
        exclude_roots=frozenset(token.upper() for token in _coerce_tokens(candidate.get("exclude_roots"))),
        exclude_instrument_ids=frozenset(token.upper() for token in _coerce_tokens(candidate.get("exclude_instrument_ids"))),
        exclude_side_slots=frozenset(
            tuple(rule.split("@", 1))  # type: ignore[arg-type]
            for rule in _coerce_tokens(candidate.get("exclude_side_slots"))
            if "@" in rule
        ),
    )


def _extract_scalar(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary", {})
    selection = report.get("selection", {})
    acceptance = report.get("acceptance", {})
    return {
        "selected_rows": int(selection.get("selected_rows", 0)),
        "filled_trades": int(summary.get("filled_trades", 0)),
        "win_rate_net": float(summary.get("win_rate_net", 0.0)),
        "trades_per_week": float(summary.get("trades_per_week", 0.0)),
        "net_ticks_sum": float(summary.get("net_ticks_sum", 0.0)),
        "concentration_top_share": float(summary.get("concentration_top_share", 0.0)),
        "passed": bool(acceptance.get("passed", False)),
    }


def _approx_equal(left: float, right: float, tol: float = 1e-9) -> bool:
    return abs(float(left) - float(right)) <= float(tol)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark legacy vs tape hypothesis engines on many candidate filters.",
    )
    parser.add_argument("--in-json", required=True, help="Path to walk-forward report JSON.")
    parser.add_argument("--candidates", type=int, default=8192, help="Number of random candidates.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for candidate generation.")
    parser.add_argument("--gate-profile", choices=("stage_go", "final_go"), default="final_go")
    parser.add_argument("--tpw-period-scope", choices=("report", "filtered"), default="report")
    parser.add_argument("--out-json", default=None, help="Optional output path for benchmark artifact.")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    in_path = Path(args.in_json)
    report = json.loads(in_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError("report_json_root_must_be_object")
    universe = _collect_universe(report)
    candidates = _generate_candidates(
        universe=universe,
        candidates_total=max(int(args.candidates), 1),
        seed=int(args.seed),
    )
    filters = [_filters_from_candidate(candidate) for candidate in candidates]
    gates = HypothesisGates()

    legacy_rows: list[dict[str, Any]] = []
    started_legacy = perf_counter()
    for filter_cfg in filters:
        result = build_hypothesis_report(
            report=report,
            filters=filter_cfg,
            gates=gates,
            gate_profile=str(args.gate_profile),
            tpw_period_scope=str(args.tpw_period_scope),
            use_signal_tape=False,
        )
        legacy_rows.append(_extract_scalar(result))
    legacy_seconds = float(perf_counter() - started_legacy)

    tape = _compile_signal_tape([row for row in report.get("planned_signals", []) if isinstance(row, dict)])
    fast_rows: list[dict[str, Any]] = []
    started_fast = perf_counter()
    for filter_cfg in filters:
        result = build_hypothesis_report(
            report=report,
            filters=filter_cfg,
            gates=gates,
            gate_profile=str(args.gate_profile),
            tpw_period_scope=str(args.tpw_period_scope),
            use_signal_tape=True,
            precompiled_tape=tape,
            collect_rejected_by_reason=False,
            include_breakdowns=False,
        )
        fast_rows.append(_extract_scalar(result))
    fast_seconds = float(perf_counter() - started_fast)

    mismatches: list[dict[str, Any]] = []
    for idx, (legacy, fast) in enumerate(zip(legacy_rows, fast_rows)):
        if (
            legacy["selected_rows"] != fast["selected_rows"]
            or legacy["filled_trades"] != fast["filled_trades"]
            or legacy["passed"] != fast["passed"]
            or not _approx_equal(legacy["win_rate_net"], fast["win_rate_net"])
            or not _approx_equal(legacy["trades_per_week"], fast["trades_per_week"])
            or not _approx_equal(legacy["net_ticks_sum"], fast["net_ticks_sum"])
            or not _approx_equal(legacy["concentration_top_share"], fast["concentration_top_share"])
        ):
            mismatches.append(
                {
                    "index": int(idx),
                    "legacy": legacy,
                    "fast": fast,
                }
            )
            if len(mismatches) >= 20:
                break
    speedup = float(legacy_seconds / fast_seconds) if fast_seconds > 0 else 0.0
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_report_path": str(in_path),
        "gate_profile": str(args.gate_profile),
        "tpw_period_scope": str(args.tpw_period_scope),
        "candidates_total": int(len(candidates)),
        "seed": int(args.seed),
        "runtime_seconds": {
            "legacy": float(legacy_seconds),
            "tape": float(fast_seconds),
        },
        "speedup": float(speedup),
        "parity": {
            "checked": int(len(filters)),
            "mismatch_count": int(len(mismatches)),
            "sample_mismatches": mismatches,
        },
    }
    if args.out_json:
        out_path = Path(args.out_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.quiet:
        print("candidates_total", int(len(candidates)))
        print("legacy_seconds", round(float(legacy_seconds), 6))
        print("tape_seconds", round(float(fast_seconds), 6))
        print("speedup", round(float(speedup), 6))
        print("parity_mismatch_count", int(len(mismatches)))
        if args.out_json:
            print("out_json", str(Path(args.out_json)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
