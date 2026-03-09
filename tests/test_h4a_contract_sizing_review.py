from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

review_module = importlib.import_module("run_h4a_contract_sizing_review")
metric_invariance = review_module.metric_invariance
risk_resized_qty = review_module._resized_qty
risk_budget_summary = review_module.risk_budget_summary
repriced_source_report = review_module._repriced_source_report


def test_metric_invariance_flags_trade_count_fill_rate_and_win_rate_equality() -> None:
    fixed = {"filled_trades": 100, "fill_rate": 0.8, "win_rate_net": 0.75}
    sized = {"filled_trades": 100, "fill_rate": 0.8, "win_rate_net": 0.75}

    result = metric_invariance(sized, fixed)

    assert result == {
        "filled_trades_unchanged": True,
        "fill_rate_unchanged": True,
        "win_rate_net_unchanged": True,
    }


def test_risk_budget_summary_counts_granularity_exceptions_and_budget_hits() -> None:
    report = {
        "planned_signals": [
            {
                "qty_lots": 3,
                "simulated_filled": True,
                "estimated_risk_money_per_lot": 4_000.0,
                "estimated_position_risk_money": 12_000.0,
            },
            {
                "qty_lots": 1,
                "simulated_filled": True,
                "estimated_risk_money_per_lot": 25_000.0,
                "estimated_position_risk_money": 25_000.0,
            },
            {
                "qty_lots": 5,
                "simulated_filled": False,
                "estimated_risk_money_per_lot": 3_000.0,
                "estimated_position_risk_money": 15_000.0,
            },
        ]
    }

    summary = risk_budget_summary(report, risk_budget_money=20_000.0)

    assert summary["planned_signals_with_sizing"] == 3
    assert summary["filled_trades"] == 2
    assert summary["one_lot_over_budget_count"] == 1
    assert summary["position_over_budget_count"] == 1
    assert summary["max_qty_lots"] == 5
    assert summary["budget_money"] == 20_000.0


def test_resized_qty_uses_risk_budget_without_contract_count_cap() -> None:
    row = {"estimated_risk_money_per_lot": 100.0}

    qty = risk_resized_qty(row, mode="target_risk_money", risk_money=1_000.0)

    assert qty == 10


def test_repriced_source_report_applies_real_fees_and_removes_excluded_minis() -> None:
    report = {
        "cost_assumptions_ticks": {
            "commission_ticks_per_side": 0.5,
            "slippage_ticks_per_side": 0.0,
            "spread_half_ticks": 0.0,
        },
        "execution_policy": {
            "limit_entry_improve_ticks": 1,
            "limit_fallback_to_market_minutes": 10,
            "limit_fallback_slip_ticks": 1,
            "tp_cost_mult": 1.0,
            "sl_cost_mult": 1.0,
            "exit_cost_mult": 1.0,
        },
        "planned_signals": [
            {
                "instrument_id": "BR",
                "trade_date": "2026-02-01",
                "as_of_ts": "2026-02-01T10:30:00+03:00",
                "side": "BUY",
                "entry_order_type": "LIMIT",
                "entry_ticks": 100,
                "entry_range_low_ticks": 100,
                "entry_range_high_ticks": 100,
                "sl_ticks": 98,
                "tp_ticks": 105,
                "qty_lots": 1,
                "tick_value": 10.0,
                "estimated_risk_money_per_lot": 30.0,
                "estimated_position_risk_money": 30.0,
                "simulated_filled": True,
                "simulated_entry_ts": "2026-02-01T10:35:00+03:00",
                "simulated_outcome": "TP",
                "simulated_gross_ticks": 5.0,
                "simulated_cost_money": 10.0,
                "simulated_gross_money": 50.0,
                "simulated_net_money": 40.0,
            },
            {
                "instrument_id": "NR",
                "trade_date": "2026-02-01",
                "qty_lots": 1,
            },
        ],
    }

    repriced = repriced_source_report(report)

    assert [row["instrument_id"] for row in repriced["planned_signals"]] == ["BR"]
    row = repriced["planned_signals"][0]
    assert row["simulated_cost_money"] == pytest.approx(0.9)
    assert row["simulated_net_money"] == pytest.approx(49.1)
    assert row["estimated_risk_money_per_lot"] == pytest.approx(21.02936)
