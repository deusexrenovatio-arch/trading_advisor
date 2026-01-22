from __future__ import annotations

import pandas as pd


def add_spread_bps(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["spread_bps"] = ((df["ask"] - df["bid"]) / df["last"]) * 10000.0
    return df


def filter_by_liquidity(
    df: pd.DataFrame, min_volume: float, max_spread_bps: float
) -> pd.DataFrame:
    filtered = df[df["volume"] >= min_volume]
    filtered = filtered[filtered["spread_bps"] <= max_spread_bps]
    return filtered
