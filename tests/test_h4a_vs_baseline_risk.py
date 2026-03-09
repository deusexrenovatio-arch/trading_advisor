from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

analysis_module = importlib.import_module("run_h4a_vs_baseline_risk")
_bucket_stats = analysis_module._bucket_stats
classify_signal_row = analysis_module.classify_signal_row
execution_delta = analysis_module.execution_delta


def test_execution_delta_keeps_only_changed_keys() -> None:
    baseline = {"max_profit_rr": 0.3, "tp_rr": 0.6}
    candidate = {"max_profit_rr": 0.0, "tp_rr": 0.6}

    delta = execution_delta(baseline, candidate)

    assert delta == {"max_profit_rr": {"baseline_risk": 0.3, "candidate": 0.0}}


def test_classify_signal_row_distinguishes_filled_blocked_and_no_fill() -> None:
    assert classify_signal_row({"simulated_filled": True, "simulated_outcome": "TP"}) == "TP"
    assert classify_signal_row({"simulated_filled": False, "gate_status": "BLOCK"}) == "GATED_OUT"
    assert classify_signal_row({"simulated_filled": False, "gate_status": "DISABLED"}) == "NO_FILL"


def test_bucket_stats_tracks_fill_and_money_breakdown() -> None:
    rows = [
        {
            "simulated_filled": True,
            "outcome_class": "TP",
            "net_money": 120.0,
            "net_ticks": 12.0,
            "qty_lots": 2,
        },
        {
            "simulated_filled": True,
            "outcome_class": "SL",
            "net_money": -30.0,
            "net_ticks": -3.0,
            "qty_lots": 1,
        },
        {
            "simulated_filled": False,
            "outcome_class": "GATED_OUT",
            "net_money": 0.0,
            "net_ticks": 0.0,
            "qty_lots": 4,
        },
        {
            "simulated_filled": False,
            "outcome_class": "NO_FILL",
            "net_money": 0.0,
            "net_ticks": 0.0,
            "qty_lots": 1,
        },
    ]

    stats = _bucket_stats(rows)

    assert stats["setups_total"] == 4
    assert stats["filled_trades"] == 2
    assert stats["gated_out"] == 1
    assert stats["no_fill"] == 1
    assert stats["fill_rate"] == 0.5
    assert stats["tp_rate"] == 0.5
    assert stats["sl_rate"] == 0.5
    assert stats["exit_rate"] == 0.0
    assert stats["net_money_sum"] == 90.0
    assert stats["expectancy_net_money"] == 45.0
    assert stats["avg_qty_lots"] == 1.5
