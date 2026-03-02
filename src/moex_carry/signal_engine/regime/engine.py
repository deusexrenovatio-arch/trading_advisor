from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from moex_carry.signal_engine.core.calendar import MarketCalendar
from moex_carry.signal_engine.core.math_utils import clamp, price_to_ticks
from moex_carry.signal_engine.core.ohlcv import adx, atr, efficiency_ratio, ema, percentile_rank
from moex_carry.signal_engine.core.types import (
    Candle,
    Direction,
    LiquidityState,
    RegimeState,
    TrendState,
    VolState,
)


class RegimeEngine:
    def __init__(self, cfg: dict):
        self.cfg = cfg or {}

    def compute(
        self,
        as_of_ts: datetime,
        d1: list[Candle],
        h1: list[Candle],
        m5: list[Candle],
        tick_size: float,
        orderbook: dict | None,
        calendar: MarketCalendar,
    ) -> RegimeState:
        if tick_size <= 0:
            raise ValueError("tick_size must be > 0")
        d1_hist = sorted((row for row in d1 if row.ts <= as_of_ts), key=lambda item: item.ts)
        h1_hist = sorted((row for row in h1 if row.ts <= as_of_ts), key=lambda item: item.ts)
        m5_hist = sorted((row for row in m5 if row.ts <= as_of_ts), key=lambda item: item.ts)

        warnings: list[str] = []
        components: dict[str, Any] = {}
        if not d1_hist:
            warnings.append("d1_history_empty")
        if not h1_hist:
            warnings.append("h1_history_empty")
        if not m5_hist:
            warnings.append("m5_history_empty")

        d1_cfg = self.cfg.get("d1", {})
        d1_ema_fast = int(d1_cfg.get("ema_fast", 20))
        d1_ema_slow = int(d1_cfg.get("ema_slow", 50))
        d1_adx_period = int(d1_cfg.get("adx_period", 14))
        d1_er_period = int(d1_cfg.get("er_period", 20))
        d1_atr_period = int(d1_cfg.get("atr_period", 14))
        d1_band_mult = float(d1_cfg.get("dir_band_atr_mult", 0.25))
        d1_adx_trend = float(d1_cfg.get("adx_trend_min", 25.0))
        d1_adx_range = float(d1_cfg.get("adx_range_max", 18.0))
        d1_er_trend = float(d1_cfg.get("er_trend_min", 0.30))
        d1_er_range = float(d1_cfg.get("er_range_max", 0.20))
        d1_atr_rank_lookback = int(d1_cfg.get("atr_rank_lookback", 60))
        d1_vol_high = float(d1_cfg.get("vol_high_pct", 0.70))
        d1_vol_low = float(d1_cfg.get("vol_low_pct", 0.30))

        d1_closes = [float(item.close) for item in d1_hist]
        d1_ema_fast_series = ema(d1_closes, d1_ema_fast)
        d1_ema_slow_series = ema(d1_closes, d1_ema_slow)
        d1_atr_series = atr(d1_hist, d1_atr_period)
        d1_adx_series = adx(d1_hist, d1_adx_period)
        d1_er_series = efficiency_ratio(d1_closes, d1_er_period)

        d1_ema_fast_last = _last_finite(d1_ema_fast_series)
        d1_ema_slow_last = _last_finite(d1_ema_slow_series)
        d1_atr_last = _last_finite(d1_atr_series)
        d1_adx_last = _last_finite(d1_adx_series)
        d1_er_last = _last_finite(d1_er_series)

        daily_atr_ticks = price_to_ticks(d1_atr_last, tick_size) if d1_atr_last > 0.0 else 0
        diff_ticks = price_to_ticks(d1_ema_fast_last - d1_ema_slow_last, tick_size)
        band_ticks = price_to_ticks(max(d1_band_mult * d1_atr_last, 0.0), tick_size) if d1_atr_last > 0.0 else 0
        if diff_ticks > band_ticks:
            daily_dir = Direction.UP
        elif diff_ticks < -band_ticks:
            daily_dir = Direction.DOWN
        else:
            daily_dir = Direction.NEUTRAL

        if d1_adx_last >= d1_adx_trend and d1_er_last >= d1_er_trend and daily_dir != Direction.NEUTRAL:
            daily_trend_state = TrendState.TREND
        elif d1_adx_last <= d1_adx_range or d1_er_last <= d1_er_range:
            daily_trend_state = TrendState.RANGE
        else:
            daily_trend_state = TrendState.TRANSITION

        atr_samples = [value for value in d1_atr_series if math.isfinite(value)]
        if len(atr_samples) > d1_atr_rank_lookback:
            atr_samples = atr_samples[-d1_atr_rank_lookback:]
        d1_atr_rank = percentile_rank(d1_atr_last, atr_samples) if atr_samples else 0.5
        if d1_atr_rank >= d1_vol_high:
            daily_vol_state = VolState.HIGH
        elif d1_atr_rank <= d1_vol_low:
            daily_vol_state = VolState.LOW
        else:
            daily_vol_state = VolState.NORMAL

        daily_strength = clamp((d1_adx_last - 18.0) / max(35.0 - 18.0, 1e-9), 0.0, 1.0)

        h1_cfg = self.cfg.get("h1", {})
        h1_ema_fast = int(h1_cfg.get("ema_fast", 20))
        h1_ema_slow = int(h1_cfg.get("ema_slow", 50))
        h1_atr_period = int(h1_cfg.get("atr_period", 14))
        h1_band_mult = float(h1_cfg.get("dir_band_atr_mult", 0.20))

        h1_closes = [float(item.close) for item in h1_hist]
        h1_ema_fast_series = ema(h1_closes, h1_ema_fast)
        h1_ema_slow_series = ema(h1_closes, h1_ema_slow)
        h1_atr_series = atr(h1_hist, h1_atr_period)
        h1_ema_fast_last = _last_finite(h1_ema_fast_series)
        h1_ema_slow_last = _last_finite(h1_ema_slow_series)
        h1_atr_last = _last_finite(h1_atr_series)

        h1_atr_ticks = price_to_ticks(h1_atr_last, tick_size) if h1_atr_last > 0.0 else 0
        h1_diff_ticks = price_to_ticks(h1_ema_fast_last - h1_ema_slow_last, tick_size)
        h1_band_ticks = price_to_ticks(max(h1_band_mult * h1_atr_last, 0.0), tick_size) if h1_atr_last > 0.0 else 0
        if h1_diff_ticks > h1_band_ticks:
            h1_dir = Direction.UP
        elif h1_diff_ticks < -h1_band_ticks:
            h1_dir = Direction.DOWN
        else:
            h1_dir = Direction.NEUTRAL
        h1_alignment = bool(daily_dir != Direction.NEUTRAL and h1_dir == daily_dir)

        liquidity_state, liquidity_metrics = _resolve_liquidity_state(
            orderbook=orderbook,
            tick_size=tick_size,
            cfg=self.cfg.get("liquidity", {}),
            warnings=warnings,
        )

        if calendar.forbid_new_position(as_of_ts):
            warnings.append("forbid_new_position_window")

        components.update(
            {
                "adx_d1": float(d1_adx_last),
                "er_d1": float(d1_er_last),
                "ema_fast_d1": float(d1_ema_fast_last),
                "ema_slow_d1": float(d1_ema_slow_last),
                "atr_d1": float(d1_atr_last),
                "atr_rank_d1": float(d1_atr_rank),
                "ema_fast_h1": float(h1_ema_fast_last),
                "ema_slow_h1": float(h1_ema_slow_last),
                "atr_h1": float(h1_atr_last),
                "liquidity": liquidity_metrics,
                "d1_bars": len(d1_hist),
                "h1_bars": len(h1_hist),
                "m5_bars": len(m5_hist),
            }
        )

        return RegimeState(
            as_of_ts=as_of_ts,
            daily_trend_state=daily_trend_state,
            daily_dir=daily_dir,
            daily_strength=float(daily_strength),
            daily_atr_ticks=int(max(daily_atr_ticks, 0)),
            daily_vol_state=daily_vol_state,
            h1_dir=h1_dir,
            h1_alignment=bool(h1_alignment),
            h1_atr_ticks=int(max(h1_atr_ticks, 0)),
            liquidity_state=liquidity_state,
            components=components,
            warnings=sorted(set(warnings)),
        )


def _last_finite(values: list[float]) -> float:
    for value in reversed(values):
        if math.isfinite(value):
            return float(value)
    return 0.0


def _resolve_liquidity_state(
    *,
    orderbook: dict | None,
    tick_size: float,
    cfg: dict[str, Any],
    warnings: list[str],
) -> tuple[LiquidityState, dict[str, Any]]:
    if not orderbook:
        warnings.append("liquidity_unknown_no_orderbook")
        return LiquidityState.UNKNOWN, {"spread_ticks": None, "depth_lots": None}

    spread_vacuum = int(cfg.get("spread_vacuum_ticks", cfg.get("spread_vacuum", 4)))
    spread_thin = int(cfg.get("spread_thin_ticks", 2))
    depth_vacuum = float(cfg.get("depth_vacuum_lots", 20.0))
    depth_thin = float(cfg.get("depth_thin_lots", 50.0))
    depth_levels = int(cfg.get("depth_levels", 5))

    bid, ask = _best_bid_ask(orderbook)
    spread_ticks = None
    if bid is not None and ask is not None and ask >= bid:
        spread_ticks = int(price_to_ticks(float(ask - bid), tick_size))

    depth_lots = _depth_lots(orderbook, depth_levels)
    metrics = {
        "spread_ticks": spread_ticks,
        "depth_lots": depth_lots,
    }

    if spread_ticks is None or depth_lots is None:
        warnings.append("liquidity_unknown_orderbook_shape")
        return LiquidityState.UNKNOWN, metrics
    if spread_ticks >= spread_vacuum or depth_lots <= depth_vacuum:
        return LiquidityState.VACUUM, metrics
    if spread_ticks > spread_thin or depth_lots < depth_thin:
        return LiquidityState.THIN, metrics
    return LiquidityState.OK, metrics


def _best_bid_ask(orderbook: dict) -> tuple[float | None, float | None]:
    bid = _to_float(orderbook.get("bid"))
    ask = _to_float(orderbook.get("ask"))
    if bid is not None and ask is not None:
        return bid, ask
    bids = orderbook.get("bids")
    asks = orderbook.get("asks")
    best_bid = _to_float(bids[0].get("price")) if isinstance(bids, list) and bids else None
    best_ask = _to_float(asks[0].get("price")) if isinstance(asks, list) and asks else None
    return best_bid, best_ask


def _depth_lots(orderbook: dict, levels: int) -> float | None:
    if "depth_lots" in orderbook and _to_float(orderbook.get("depth_lots")) is not None:
        return float(orderbook.get("depth_lots"))
    bids = orderbook.get("bids")
    asks = orderbook.get("asks")
    if not isinstance(bids, list) or not isinstance(asks, list):
        return None
    level_count = max(int(levels), 1)
    bid_size = 0.0
    ask_size = 0.0
    for row in bids[:level_count]:
        bid_size += _to_float(row.get("size")) or 0.0
    for row in asks[:level_count]:
        ask_size += _to_float(row.get("size")) or 0.0
    return float(bid_size + ask_size)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed
