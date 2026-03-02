from __future__ import annotations

import math

from moex_carry.signal_engine.core.math_utils import price_to_ticks, round_half_away_from_zero
from moex_carry.signal_engine.core.ohlcv import atr
from moex_carry.signal_engine.core.types import Candle, ExecutionParams, Level, Side


class ExecutionEngine:
    def __init__(self, cfg: dict):
        self.cfg = cfg or {}

    def compute_params(self, m5: list[Candle], tick_size: float) -> ExecutionParams:
        if tick_size <= 0:
            raise ValueError("tick_size must be > 0")
        warnings: list[str] = []
        ordered = sorted(m5, key=lambda item: item.ts)
        if len(ordered) < 2:
            return ExecutionParams(
                buffer_ticks=max(int(self.cfg.get("buffer_min_ticks", 1)), 1),
                limit_slip_ticks=max(int(self.cfg.get("limit_slip_ticks", 2)), 0),
                m5_atr_ticks=0,
                m5_noise_ratio=0.0,
                warnings=["m5_history_too_short"],
            )

        atr_period = max(int(self.cfg.get("m5_atr_period", 14)), 1)
        atr_series = atr(ordered, atr_period)
        atr_last = _last_finite(atr_series)
        m5_atr_ticks = price_to_ticks(atr_last, tick_size) if atr_last > 0.0 else 0
        buffer_mult = float(self.cfg.get("buffer_atr_mult", 0.10))
        buffer_min = max(int(self.cfg.get("buffer_min_ticks", 1)), 1)
        buffer_ticks = max(buffer_min, round_half_away_from_zero(buffer_mult * float(max(m5_atr_ticks, 1))))

        last = ordered[-1]
        m5_range_ticks = max(price_to_ticks(float(last.high) - float(last.low), tick_size), 0)
        m5_noise_ratio = float(m5_range_ticks / max(m5_atr_ticks, 1))
        warn_high = float(self.cfg.get("noise_warn_high", 2.5))
        warn_low = float(self.cfg.get("noise_warn_low", 0.4))
        if m5_noise_ratio > warn_high:
            warnings.append("too_spiky_for_set_wait")
        if m5_noise_ratio < warn_low:
            warnings.append("too_quiet_breakout_may_stall")

        return ExecutionParams(
            buffer_ticks=int(buffer_ticks),
            limit_slip_ticks=max(int(self.cfg.get("limit_slip_ticks", 2)), 0),
            m5_atr_ticks=int(max(m5_atr_ticks, 0)),
            m5_noise_ratio=float(m5_noise_ratio),
            warnings=warnings,
        )

    def choose_stop_from_m5_structure(
        self,
        m5: list[Candle],
        side: Side,
        entry_ticks: int,
        buffer_ticks: int,
    ) -> int:
        ordered = sorted(m5, key=lambda item: item.ts)
        tick_size = _infer_tick_size(ordered, entry_ticks)
        if not ordered:
            return int(entry_ticks - max(int(buffer_ticks), 1) if side == Side.BUY else entry_ticks + max(int(buffer_ticks), 1))
        swing_k = max(int(self.cfg.get("swing_k", 2)), 1)
        if side == Side.BUY:
            swing_price = _latest_swing_low(ordered, swing_k)
            if swing_price is None:
                return int(entry_ticks - max(int(buffer_ticks), 1))
            return int(price_to_ticks(swing_price, tick_size) - max(int(buffer_ticks), 1))
        swing_price = _latest_swing_high(ordered, swing_k)
        if swing_price is None:
            return int(entry_ticks + max(int(buffer_ticks), 1))
        return int(price_to_ticks(swing_price, tick_size) + max(int(buffer_ticks), 1))

    def choose_tp_from_levels(
        self,
        side: Side,
        entry_ticks: int,
        candidate_levels: list[Level],
        min_target_ticks: int,
    ) -> int | None:
        target_min = max(int(min_target_ticks), 1)
        if side == Side.BUY:
            valid = sorted(
                (int(level.price_ticks) for level in candidate_levels if int(level.price_ticks) >= int(entry_ticks) + target_min),
            )
            return valid[0] if valid else None
        valid = sorted(
            (int(level.price_ticks) for level in candidate_levels if int(level.price_ticks) <= int(entry_ticks) - target_min),
            reverse=True,
        )
        return valid[0] if valid else None


def _latest_swing_low(candles: list[Candle], k: int) -> float | None:
    for idx in range(len(candles) - 1 - k, k - 1, -1):
        current = float(candles[idx].low)
        is_swing = True
        for j in range(idx - k, idx + k + 1):
            if j == idx:
                continue
            if current >= float(candles[j].low):
                is_swing = False
                break
        if is_swing:
            return current
    return None


def _latest_swing_high(candles: list[Candle], k: int) -> float | None:
    for idx in range(len(candles) - 1 - k, k - 1, -1):
        current = float(candles[idx].high)
        is_swing = True
        for j in range(idx - k, idx + k + 1):
            if j == idx:
                continue
            if current <= float(candles[j].high):
                is_swing = False
                break
        if is_swing:
            return current
    return None


def _last_finite(values: list[float]) -> float:
    for value in reversed(values):
        if math.isfinite(value):
            return float(value)
    return 0.0


def _infer_tick_size(candles: list[Candle], entry_ticks: int) -> float:
    if not candles or int(entry_ticks) == 0:
        return 1.0
    close_price = abs(float(candles[-1].close))
    inferred = close_price / float(abs(int(entry_ticks)))
    if not math.isfinite(inferred) or inferred <= 0.0:
        return 1.0
    return float(inferred)
