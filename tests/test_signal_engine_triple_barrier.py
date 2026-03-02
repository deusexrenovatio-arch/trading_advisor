from __future__ import annotations

from datetime import datetime, timedelta

from moex_carry.signal_engine.core.types import AlphaProposal, Candle
from moex_carry.signal_engine.labeling.triple_barrier import label_with_triple_barrier


def _candle(minute: int, *, high: float, low: float, close: float) -> Candle:
    ts = datetime(2026, 1, 10, 10, 0, 0) + timedelta(minutes=minute)
    return Candle(ts=ts, open=close, high=high, low=low, close=close, volume=1.0)


def _proposal(side: str = "BUY") -> AlphaProposal:
    return AlphaProposal(
        strategy_id="unit_test",
        instrument_id="TEST",
        side=side,  # type: ignore[arg-type]
        entry_ts=datetime(2026, 1, 10, 10, 0, 0),
        horizon_sec=180,
        tp_ticks=5,
        sl_ticks=3,
        exit_rule={"type": "time_exit"},
    )


def test_triple_barrier_buy_tp_first():
    proposal = _proposal("BUY")
    result = label_with_triple_barrier(
        proposal=proposal,
        candles_forward=[
            _candle(1, high=1006, low=998, close=1004),
            _candle(2, high=1004, low=997, close=1000),
        ],
        entry_price_ticks=1000,
        tick_size=1.0,
    )
    assert result.label == "TP"
    assert result.exit_price_ticks == 1005


def test_triple_barrier_buy_sl_first():
    proposal = _proposal("BUY")
    result = label_with_triple_barrier(
        proposal=proposal,
        candles_forward=[
            _candle(1, high=1002, low=996, close=998),
            _candle(2, high=1008, low=998, close=1007),
        ],
        entry_price_ticks=1000,
        tick_size=1.0,
    )
    assert result.label == "SL"
    assert result.exit_price_ticks == 997


def test_triple_barrier_same_bar_tp_sl_uses_worst_case():
    proposal = _proposal("BUY")
    result = label_with_triple_barrier(
        proposal=proposal,
        candles_forward=[_candle(1, high=1006, low=996, close=1001)],
        entry_price_ticks=1000,
        tick_size=1.0,
        on_same_bar_tp_sl="worst_case",
    )
    assert result.label == "SL"
    assert result.exit_price_ticks == 997


def test_triple_barrier_timeout_exit():
    proposal = _proposal("BUY")
    result = label_with_triple_barrier(
        proposal=proposal,
        candles_forward=[
            _candle(1, high=1003, low=998, close=1000),
            _candle(2, high=1004, low=998, close=1001),
            _candle(3, high=1004, low=998, close=1002),
        ],
        entry_price_ticks=1000,
        tick_size=1.0,
    )
    assert result.label == "EXIT"
    assert result.exit_price_ticks == 1002
