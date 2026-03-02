from __future__ import annotations

from datetime import datetime

from moex_carry.signal_engine.core.types import AlphaProposal, MarketRegimeFlags, OutcomeForecast
from moex_carry.signal_engine.gate.gate import GateConfig, apply_signal_gate


def _proposal() -> AlphaProposal:
    return AlphaProposal(
        strategy_id="orb_v1",
        instrument_id="TEST",
        side="BUY",
        entry_ts=datetime(2026, 1, 10, 12, 0, 0),
        horizon_sec=60 * 30,
        tp_ticks=8,
        sl_ticks=5,
        exit_rule={"type": "time_exit"},
    )


def test_gate_low_tier_returns_advisory():
    signal = apply_signal_gate(
        proposal=_proposal(),
        forecast=OutcomeForecast(
            p_tp=0.5,
            p_sl=0.2,
            p_exit=0.3,
            n_effective=20,
            confidence_tier="low",
            probability_source="unit",
        ),
        expected_return_ticks_value=3.0,
        cost_ticks=1.0,
        vol_regime="HIGH",
    )
    assert signal.action == "ADVISORY"
    assert "reason_low_confidence" in signal.metadata


def test_gate_blocks_expected_return_below_threshold():
    signal = apply_signal_gate(
        proposal=_proposal(),
        forecast=OutcomeForecast(
            p_tp=0.55,
            p_sl=0.15,
            p_exit=0.30,
            n_effective=200,
            confidence_tier="mid",
            probability_source="unit",
        ),
        expected_return_ticks_value=0.9,
        cost_ticks=1.0,
        vol_regime="HIGH",
        config=GateConfig(min_expected_return_ticks=1.0),
    )
    assert signal.action == "NO_TRADE"
    assert "expected_return_below_threshold" in signal.metadata["gate_reasons"]


def test_gate_blocks_clearing_window():
    signal = apply_signal_gate(
        proposal=_proposal(),
        forecast=OutcomeForecast(
            p_tp=0.6,
            p_sl=0.2,
            p_exit=0.2,
            n_effective=600,
            confidence_tier="high",
            probability_source="unit",
        ),
        expected_return_ticks_value=2.0,
        cost_ticks=1.0,
        regime_flags=MarketRegimeFlags(is_intraday_clearing_window=True),
        vol_regime="HIGH",
    )
    assert signal.action == "NO_TRADE"
    assert "clearing_window_block" in signal.metadata["gate_reasons"]
