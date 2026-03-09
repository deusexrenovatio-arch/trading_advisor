from __future__ import annotations

from datetime import datetime, timedelta

from moex_carry.signal_engine.core.types import Candle
from moex_carry.signal_engine.strategies.orb import generate_orb_proposal


def _make_candles() -> list[Candle]:
    start = datetime(2026, 1, 10, 10, 0, 0)
    candles: list[Candle] = []
    for idx in range(20):
        high = 100.0 + (0.1 * idx)
        low = 99.0 + (0.1 * idx)
        close = 99.5 + (0.1 * idx)
        candles.append(
            Candle(
                ts=start + timedelta(minutes=idx),
                open=close,
                high=high,
                low=low,
                close=close,
                volume=100.0,
            )
        )
    candles[-1] = Candle(
        ts=candles[-1].ts,
        open=101.0,
        high=103.0,
        low=100.5,
        close=102.8,
        volume=200.0,
    )
    return candles


def test_orb_generates_buy_candidate_in_high_vol_regime():
    proposal = generate_orb_proposal(
        instrument_id="SBER",
        candles=_make_candles(),
        tick_size=0.1,
        context={"vol_regime": "HIGH"},
    )
    assert proposal is not None
    assert proposal.side == "BUY"
