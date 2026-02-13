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


def score_pairs_alpha(
    metrics: pd.DataFrame,
    weights: dict[str, float] | None = None,
    primary_metric: str | None = "avg_trade_return_annual_operational_recent",
) -> pd.DataFrame:
    df = metrics.copy()
    weights = weights or {}
    w_floor = float(weights.get("floor", 1.0))
    w_alpha = float(weights.get("alpha", 1.0))
    w_liq = float(weights.get("liq", 1.0))
    w_event = float(weights.get("event", 1.0))
    df["total_score"] = (
        w_floor * df.get("score_floor", 0.0)
        + w_alpha * df.get("score_alpha", 0.0)
        - w_liq * df.get("penalty_liq", 0.0)
        - w_event * df.get("penalty_event", 0.0)
    )
    metric_name = str(primary_metric or "").strip()
    if not metric_name or metric_name == "total_score" or metric_name not in df.columns:
        return df.sort_values("total_score", ascending=False)

    df["_primary_metric_value"] = pd.to_numeric(df[metric_name], errors="coerce")
    ranked = df.sort_values(
        by=["_primary_metric_value", "total_score"],
        ascending=[False, False],
        na_position="last",
    )
    return ranked.drop(columns=["_primary_metric_value"], errors="ignore")
