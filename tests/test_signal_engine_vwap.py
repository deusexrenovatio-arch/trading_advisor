from __future__ import annotations

from datetime import datetime, timedelta

from moex_carry.signal_engine.core.types import Candle
from moex_carry.signal_engine.strategies.vwap_mr import generate_vwap_mr_proposal


def _make_candles_with_discount() -> list[Candle]:
    start = datetime(2026, 1, 10, 10, 0, 0)
    candles: list[Candle] = []
    for idx in range(70):
        base = 100.0
        close = base if idx < 69 else 96.0
        candles.append(
            Candle(
                ts=start + timedelta(minutes=idx),
                open=close,
                high=close + 0.3,
                low=close - 0.3,
                close=close,
                volume=100.0,
            )
        )
    return candles


def test_vwap_mr_generates_buy_on_negative_zscore():
    proposal = generate_vwap_mr_proposal(
        instrument_id="SBER",
        candles=_make_candles_with_discount(),
        tick_size=0.1,
    )
    assert proposal is not None
    assert proposal.side == "BUY"
