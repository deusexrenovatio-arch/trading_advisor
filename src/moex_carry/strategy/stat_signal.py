from __future__ import annotations

from typing import Sequence

from moex_carry.analytics.stats import spread_stats
from moex_carry.strategy.models import SignalDecision


def stat_signal(
    spread_series: Sequence[float],
    window: int,
    z_entry: float,
    z_exit: float,
    min_window: int = 20,
) -> SignalDecision:
    stats = spread_stats(spread_series, window=window, min_window=min_window)
    if stats["window"] < min_window:
        return SignalDecision(
            action="hold",
            direction=None,
            score=0.0,
            reasons=["insufficient_history"],
            metrics={},
        )
    z = stats["trend_zscore"]
    metrics = {
        "zscore": z,
        "zscore_raw": stats["zscore"],
        "spread_vol": stats["std"],
        "trend_pos": stats["trend_pos"],
        "trend_slope": stats["trend_slope"],
        "trend_zscore": stats["trend_zscore"],
    }
    if z >= z_entry:
        return SignalDecision(
            action="enter",
            direction="cash_and_carry",
            score=abs(z),
            reasons=["zscore_high"],
            metrics=metrics,
        )
    if z <= -z_entry:
        return SignalDecision(
            action="enter",
            direction="reverse",
            score=abs(z),
            reasons=["zscore_low"],
            metrics=metrics,
        )
    if abs(z) <= z_exit:
        return SignalDecision(
            action="exit",
            direction=None,
            score=abs(z),
            reasons=["zscore_revert"],
            metrics=metrics,
        )
    return SignalDecision(
        action="hold",
        direction=None,
        score=abs(z),
        reasons=["zscore_mid"],
        metrics=metrics,
    )
