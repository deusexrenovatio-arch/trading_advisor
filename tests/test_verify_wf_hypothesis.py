from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest


def _load_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "verify_wf_hypothesis.py"
    spec = importlib.util.spec_from_file_location("verify_wf_hypothesis_script", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _signal(
    *,
    instrument_id: str,
    setup_kind: str,
    side: str,
    slot: str,
    trade_date: str,
    filled: bool,
    net_ticks: float,
    gross_ticks: float,
    outcome: str,
) -> dict[str, object]:
    return {
        "instrument_id": instrument_id,
        "setup_kind": setup_kind,
        "side": side,
        "as_of_ts": f"{trade_date}T{slot}:00+03:00",
        "trade_date": trade_date,
        "simulated_filled": filled,
        "simulated_net_ticks": net_ticks,
        "simulated_gross_ticks": gross_ticks,
        "simulated_outcome": outcome,
    }


def test_build_hypothesis_report_applies_filters_and_passes_gates():
    mod = _load_module()
    report = {
        "period": {"start_date": "2025-03-01", "end_date": "2025-03-14"},
        "planned_signals": [
            _signal(
                instrument_id="MMH6",
                setup_kind="ORB_BREAKOUT",
                side="SELL",
                slot="12:00",
                trade_date="2025-03-03",
                filled=True,
                net_ticks=10.0,
                gross_ticks=12.0,
                outcome="TP",
            ),
            _signal(
                instrument_id="MMH6",
                setup_kind="ORB_BREAKOUT",
                side="BUY",
                slot="12:00",
                trade_date="2025-03-04",
                filled=True,
                net_ticks=-5.0,
                gross_ticks=-4.0,
                outcome="SL",
            ),
            _signal(
                instrument_id="SIH6",
                setup_kind="ORB_BREAKOUT",
                side="SELL",
                slot="14:15",
                trade_date="2025-03-05",
                filled=True,
                net_ticks=8.0,
                gross_ticks=9.5,
                outcome="TP",
            ),
            _signal(
                instrument_id="GDH6",
                setup_kind="ORB_BREAKOUT",
                side="SELL",
                slot="14:15",
                trade_date="2025-03-06",
                filled=True,
                net_ticks=4.0,
                gross_ticks=5.0,
                outcome="EXIT",
            ),
            _signal(
                instrument_id="MMH6",
                setup_kind="EMA_PULLBACK_LIMIT",
                side="SELL",
                slot="12:00",
                trade_date="2025-03-07",
                filled=False,
                net_ticks=0.0,
                gross_ticks=0.0,
                outcome="NO_FILL",
            ),
        ],
    }
    filters = mod.HypothesisFilters(
        include_setup_kinds=frozenset({"ORB_BREAKOUT"}),
        include_slots=frozenset({"12:00", "14:15"}),
        include_clusters=frozenset({"other"}),
        exclude_side_slots=frozenset({("BUY", "12:00")}),
    )
    gates = mod.HypothesisGates(
        min_filled_trades=2,
        min_win_rate_net=0.75,
        min_trades_per_week=0.90,
        min_net_ticks_sum=0.0,
        max_concentration_top_share=0.80,
    )

    result = mod.build_hypothesis_report(
        report=report,
        filters=filters,
        gates=gates,
        gate_profile=None,
        tpw_period_scope="report",
    )

    summary = result["summary"]
    assert result["selection"]["selected_rows"] == 2
    assert summary["setups_total"] == 2
    assert summary["filled_trades"] == 2
    assert summary["win_rate_net"] == pytest.approx(1.0)
    assert summary["net_ticks_sum"] == pytest.approx(18.0)
    assert summary["trades_per_week"] == pytest.approx(1.0)
    assert summary["concentration_top_share"] == pytest.approx(10.0 / 18.0)
    assert result["acceptance"]["passed"] is True


def test_build_hypothesis_report_stage_go_profile_fails_on_frequency():
    mod = _load_module()
    report = {
        "period": {"start_date": "2025-03-01", "end_date": "2025-03-14"},
        "planned_signals": [
            _signal(
                instrument_id="MMH6",
                setup_kind="ORB_BREAKOUT",
                side="SELL",
                slot="12:00",
                trade_date="2025-03-03",
                filled=True,
                net_ticks=10.0,
                gross_ticks=11.0,
                outcome="TP",
            ),
            _signal(
                instrument_id="SIH6",
                setup_kind="ORB_BREAKOUT",
                side="SELL",
                slot="14:15",
                trade_date="2025-03-05",
                filled=True,
                net_ticks=8.0,
                gross_ticks=9.0,
                outcome="TP",
            ),
        ],
    }
    result = mod.build_hypothesis_report(
        report=report,
        filters=mod.HypothesisFilters(),
        gates=mod.HypothesisGates(),
        gate_profile="stage_go",
        tpw_period_scope="report",
    )
    checks = {item["id"]: item for item in result["acceptance"]["checks"]}
    assert math.isclose(result["summary"]["trades_per_week"], 1.0)
    assert checks["min_win_rate_net"]["passed"] is True
    assert checks["min_net_ticks_sum"]["passed"] is True
    assert checks["min_trades_per_week"]["passed"] is False
    assert result["acceptance"]["passed"] is False


def test_parse_side_slot_rules_rejects_invalid_pattern():
    mod = _load_module()
    with pytest.raises(ValueError):
        mod._parse_side_slot_rules(["BUY1200"])


def test_tape_engine_matches_legacy_engine_with_full_summary():
    mod = _load_module()
    report = {
        "period": {"start_date": "2025-03-01", "end_date": "2025-03-14"},
        "planned_signals": [
            _signal(
                instrument_id="MMH6",
                setup_kind="ORB_BREAKOUT",
                side="SELL",
                slot="12:00",
                trade_date="2025-03-03",
                filled=True,
                net_ticks=10.0,
                gross_ticks=11.0,
                outcome="TP",
            ),
            _signal(
                instrument_id="MMH6",
                setup_kind="ORB_BREAKOUT",
                side="BUY",
                slot="12:00",
                trade_date="2025-03-04",
                filled=True,
                net_ticks=-6.0,
                gross_ticks=-5.0,
                outcome="SL",
            ),
            _signal(
                instrument_id="RIH6",
                setup_kind="ORB_BREAKOUT",
                side="SELL",
                slot="14:15",
                trade_date="2025-03-05",
                filled=True,
                net_ticks=9.0,
                gross_ticks=9.0,
                outcome="TP",
            ),
            _signal(
                instrument_id="GDH6",
                setup_kind="EMA_PULLBACK_LIMIT",
                side="SELL",
                slot="14:15",
                trade_date="2025-03-06",
                filled=True,
                net_ticks=4.0,
                gross_ticks=5.0,
                outcome="EXIT",
            ),
            _signal(
                instrument_id="BRH6",
                setup_kind="ORB_BREAKOUT",
                side="SELL",
                slot="10:30",
                trade_date="2025-03-07",
                filled=False,
                net_ticks=0.0,
                gross_ticks=0.0,
                outcome="NO_FILL",
            ),
        ],
    }
    filters = mod.HypothesisFilters(
        include_setup_kinds=frozenset({"ORB_BREAKOUT", "EMA_PULLBACK_LIMIT"}),
        include_slots=frozenset({"12:00", "14:15"}),
        include_clusters=frozenset({"other", "metals"}),
        exclude_side_slots=frozenset({("BUY", "12:00")}),
    )
    gates = mod.HypothesisGates(
        min_filled_trades=2,
        min_win_rate_net=0.70,
        min_trades_per_week=0.80,
        min_net_ticks_sum=0.0,
        max_concentration_top_share=0.80,
    )
    legacy = mod.build_hypothesis_report(
        report=report,
        filters=filters,
        gates=gates,
        gate_profile=None,
        tpw_period_scope="report",
        use_signal_tape=False,
    )
    tape = mod._compile_signal_tape(report["planned_signals"])
    fast = mod.build_hypothesis_report(
        report=report,
        filters=filters,
        gates=gates,
        gate_profile=None,
        tpw_period_scope="report",
        use_signal_tape=True,
        precompiled_tape=tape,
        collect_rejected_by_reason=True,
        include_breakdowns=True,
    )
    assert fast["selection"]["engine"] == "tape"
    assert legacy["selection"]["engine"] == "legacy"
    assert fast["selection"]["selected_rows"] == legacy["selection"]["selected_rows"]
    assert fast["selection"]["rejected_rows"] == legacy["selection"]["rejected_rows"]
    assert fast["selection"]["rejected_by_reason"] == legacy["selection"]["rejected_by_reason"]
    for key in (
        "setups_total",
        "filled_trades",
        "fill_rate",
        "tp_rate",
        "sl_rate",
        "exit_rate",
        "win_rate_net",
        "expectancy_net_ticks",
        "gross_ticks_sum",
        "net_ticks_sum",
        "trades_per_week",
        "concentration_top_share",
        "concentration_hhi",
    ):
        assert fast["summary"][key] == pytest.approx(legacy["summary"][key])
    assert fast["summary"]["by_setup_kind"] == legacy["summary"]["by_setup_kind"]
    assert fast["summary"]["by_instrument"] == legacy["summary"]["by_instrument"]
    assert fast["summary"]["by_slot"] == legacy["summary"]["by_slot"]
    assert fast["summary"]["by_cluster"] == legacy["summary"]["by_cluster"]
    assert fast["summary"]["by_side"] == legacy["summary"]["by_side"]
    assert fast["acceptance"] == legacy["acceptance"]


def test_tape_engine_lite_summary_keeps_scalar_parity():
    mod = _load_module()
    report = {
        "period": {"start_date": "2025-03-01", "end_date": "2025-03-14"},
        "planned_signals": [
            _signal(
                instrument_id="MMH6",
                setup_kind="ORB_BREAKOUT",
                side="SELL",
                slot="12:00",
                trade_date="2025-03-03",
                filled=True,
                net_ticks=10.0,
                gross_ticks=11.0,
                outcome="TP",
            ),
            _signal(
                instrument_id="RIH6",
                setup_kind="ORB_BREAKOUT",
                side="SELL",
                slot="14:15",
                trade_date="2025-03-05",
                filled=True,
                net_ticks=8.0,
                gross_ticks=9.0,
                outcome="TP",
            ),
            _signal(
                instrument_id="GDH6",
                setup_kind="EMA_PULLBACK_LIMIT",
                side="SELL",
                slot="14:15",
                trade_date="2025-03-06",
                filled=True,
                net_ticks=3.0,
                gross_ticks=4.0,
                outcome="EXIT",
            ),
        ],
    }
    filters = mod.HypothesisFilters(
        include_slots=frozenset({"12:00", "14:15"}),
        include_clusters=frozenset({"other", "metals"}),
    )
    gates = mod.HypothesisGates(min_trades_per_week=0.5, min_win_rate_net=0.6)
    baseline = mod.build_hypothesis_report(
        report=report,
        filters=filters,
        gates=gates,
        gate_profile=None,
        tpw_period_scope="report",
        use_signal_tape=False,
    )
    fast_lite = mod.build_hypothesis_report(
        report=report,
        filters=filters,
        gates=gates,
        gate_profile=None,
        tpw_period_scope="report",
        use_signal_tape=True,
        collect_rejected_by_reason=False,
        include_breakdowns=False,
    )
    for key in (
        "setups_total",
        "filled_trades",
        "win_rate_net",
        "trades_per_week",
        "net_ticks_sum",
        "expectancy_net_ticks",
        "concentration_top_share",
    ):
        assert fast_lite["summary"][key] == pytest.approx(baseline["summary"][key])
    assert fast_lite["summary"]["by_setup_kind"] == {}
    assert fast_lite["summary"]["by_instrument"] == {}
    assert fast_lite["summary"]["by_slot"] == {}
    assert fast_lite["summary"]["by_cluster"] == {}
    assert fast_lite["summary"]["by_side"] == {}
    assert fast_lite["selection"]["rejected_by_reason"] == {}
