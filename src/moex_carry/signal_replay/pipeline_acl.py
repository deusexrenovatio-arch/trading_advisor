from __future__ import annotations

from typing import Any

import pandas as pd


# Anti-corruption adapter between signal_replay and pipeline internals.
# Keeps replay context independent from direct imports of moex_carry.pipeline.
def apply_spread_carry_signals(*args: Any, **kwargs: Any):
    from moex_carry.pipeline import _apply_spread_carry_signals

    return _apply_spread_carry_signals(*args, **kwargs)


def execution_quality_stats(series_df: pd.DataFrame) -> dict[str, float | None]:
    from moex_carry.pipeline import _execution_quality_stats

    return _execution_quality_stats(series_df)


def avg_recent_trade_return_annual(series_df: pd.DataFrame) -> float | None:
    from moex_carry.pipeline import _avg_recent_trade_return_annual

    return _avg_recent_trade_return_annual(series_df)


def avg_recent_trade_return_annual_operational(series_df: pd.DataFrame) -> float | None:
    from moex_carry.pipeline import _avg_recent_trade_return_annual_operational

    return _avg_recent_trade_return_annual_operational(series_df)