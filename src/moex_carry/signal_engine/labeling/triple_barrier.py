from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from moex_carry.signal_engine.core.math_utils import price_to_ticks
from moex_carry.signal_engine.core.types import AlphaProposal, Candle, OutcomeLabel

SameBarRule = Literal["worst_case", "best_case"]


@dataclass(frozen=True)
class TripleBarrierResult:
    label: OutcomeLabel
    exit_ts: datetime | None
    exit_price_ticks: int


def _barrier_levels(entry_price_ticks: int, proposal: AlphaProposal) -> tuple[int, int]:
    if proposal.side == "BUY":
        tp_level = int(entry_price_ticks) + int(proposal.tp_ticks)
        sl_level = int(entry_price_ticks) - int(proposal.sl_ticks)
    else:
        tp_level = int(entry_price_ticks) - int(proposal.tp_ticks)
        sl_level = int(entry_price_ticks) + int(proposal.sl_ticks)
    return tp_level, sl_level


def label_with_triple_barrier(
    *,
    proposal: AlphaProposal,
    candles_forward: list[Candle],
    entry_price_ticks: int,
    tick_size: float,
    on_same_bar_tp_sl: SameBarRule = "worst_case",
) -> TripleBarrierResult:
    if tick_size <= 0:
        raise ValueError("tick_size must be > 0")
    if not candles_forward:
        return TripleBarrierResult(
            label="EXIT",
            exit_ts=None,
            exit_price_ticks=int(entry_price_ticks),
        )

    deadline = proposal.entry_ts + timedelta(seconds=max(int(proposal.horizon_sec), 1))
    tp_level_ticks, sl_level_ticks = _barrier_levels(int(entry_price_ticks), proposal)
    last_seen = None

    for candle in sorted(candles_forward, key=lambda item: item.ts):
        if candle.ts <= proposal.entry_ts:
            continue
        if candle.ts > deadline:
            break
        last_seen = candle
        high_ticks = price_to_ticks(float(candle.high), tick_size)
        low_ticks = price_to_ticks(float(candle.low), tick_size)

        if proposal.side == "BUY":
            tp_hit = high_ticks >= tp_level_ticks
            sl_hit = low_ticks <= sl_level_ticks
        else:
            tp_hit = low_ticks <= tp_level_ticks
            sl_hit = high_ticks >= sl_level_ticks

        if tp_hit and sl_hit:
            if on_same_bar_tp_sl == "best_case":
                return TripleBarrierResult("TP", candle.ts, int(tp_level_ticks))
            return TripleBarrierResult("SL", candle.ts, int(sl_level_ticks))
        if tp_hit:
            return TripleBarrierResult("TP", candle.ts, int(tp_level_ticks))
        if sl_hit:
            return TripleBarrierResult("SL", candle.ts, int(sl_level_ticks))

    if last_seen is None:
        last_seen = min(candles_forward, key=lambda item: abs(item.ts - deadline))
    return TripleBarrierResult(
        label="EXIT",
        exit_ts=last_seen.ts,
        exit_price_ticks=price_to_ticks(float(last_seen.close), tick_size),
    )
