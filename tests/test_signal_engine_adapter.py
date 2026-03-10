from __future__ import annotations

from datetime import datetime

from moex_carry.signal_engine.adapter import to_strategy_signal
from moex_carry.signal_engine.core.types import AlphaProposal, StrategySignal as EngineStrategySignal


def test_adapter_maps_engine_signal_to_strategy_contract():
    proposal = AlphaProposal(
        strategy_id="orb_v1",
        instrument_id="SBER",
        side="BUY",
        entry_ts=datetime(2026, 1, 10, 12, 0, 0),
        horizon_sec=3600,
        tp_ticks=10,
        sl_ticks=6,
        exit_rule={"type": "time_exit"},
    )
    engine_signal = EngineStrategySignal(
        action="BUY",
        confidence=0.8,
        expected_return_ticks=2.4,
        risk_ticks=6.0,
        metadata={"p_tp": 0.55, "p_sl": 0.2, "p_exit": 0.25},
    )

    strategy_signal = to_strategy_signal(proposal=proposal, engine_signal=engine_signal)
    assert strategy_signal.action == "enter"
    assert strategy_signal.strategy_type == "speculative"
    assert strategy_signal.instruments == ["SBER"]
    assert strategy_signal.metadata["engine_action"] == "BUY"
