from __future__ import annotations

import pandas as pd


def score_pairs(metrics: pd.DataFrame) -> pd.DataFrame:
    df = metrics.copy()
    df["score"] = (
        df["expected_net_irr"]
        - 0.25 * df.get("mae", 0.0)
        - 0.1 * df.get("model_breaks", 0.0)
        - 0.2 * df.get("spread_vol_pct", 0.0)
        - 0.1 * df.get("spread_trend_z", 0.0).abs()
    )
    return df.sort_values("score", ascending=False)
