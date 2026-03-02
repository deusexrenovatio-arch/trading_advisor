from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from moex_carry.signal_engine.core.types import Candle, Level, Side, TF
from moex_carry.signal_engine.execution.engine import ExecutionEngine


def _candles_for_execution() -> list[Candle]:
    tz = ZoneInfo("Europe/Moscow")
    start = datetime(2026, 2, 1, 10, 0, tzinfo=tz)
    lows = [99, 98, 95, 98, 99, 100]
    highs = [101, 102, 100, 106, 103, 104]
    closes = [100, 100, 98, 101, 102, 100]
    rows: list[Candle] = []
    for idx in range(len(closes)):
        rows.append(
            Candle(
                ts=start + timedelta(minutes=5 * idx),
                open=closes[idx] - 0.2,
                high=float(highs[idx]),
                low=float(lows[idx]),
                close=float(closes[idx]),
                volume=1_000.0,
            )
        )
    return rows


def test_execution_engine_computes_buffer_ticks():
    engine = ExecutionEngine(
        {
            "m5_atr_period": 3,
            "buffer_atr_mult": 0.10,
            "buffer_min_ticks": 1,
            "limit_slip_ticks": 2,
            "noise_warn_high": 2.5,
            "noise_warn_low": 0.4,
        }
    )
    params = engine.compute_params(_candles_for_execution(), tick_size=1.0)
    assert params.buffer_ticks >= 1
    assert params.limit_slip_ticks == 2
    assert params.m5_atr_ticks >= 1


def test_execution_engine_chooses_stop_from_m5_structure():
    engine = ExecutionEngine({"swing_k": 2})
    sl_buy = engine.choose_stop_from_m5_structure(
        m5=_candles_for_execution(),
        side=Side.BUY,
        entry_ticks=100,
        buffer_ticks=1,
    )
    sl_sell = engine.choose_stop_from_m5_structure(
        m5=_candles_for_execution(),
        side=Side.SELL,
        entry_ticks=100,
        buffer_ticks=1,
    )
    assert sl_buy == 94
    assert sl_sell == 107


def test_execution_engine_selects_nearest_target_level():
    engine = ExecutionEngine({})
    levels = [
        Level(tf=TF.D1, kind="L1", price_ticks=103, score=0.8, meta={}),
        Level(tf=TF.D1, kind="L2", price_ticks=110, score=0.7, meta={}),
        Level(tf=TF.D1, kind="L3", price_ticks=96, score=0.6, meta={}),
    ]
    tp_buy = engine.choose_tp_from_levels(Side.BUY, entry_ticks=100, candidate_levels=levels, min_target_ticks=2)
    tp_sell = engine.choose_tp_from_levels(Side.SELL, entry_ticks=100, candidate_levels=levels, min_target_ticks=2)
    assert tp_buy == 103
    assert tp_sell == 96
