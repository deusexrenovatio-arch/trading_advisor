from __future__ import annotations

import pandas as pd
from dash.dash_table.Format import Format, Scheme, Trim


def _table_columns(df):
    return [{"name": col, "id": col} for col in df.columns]


def _decision_columns():
    return [
        {"name": "Time", "id": "created_at"},
        {"name": "Decision", "id": "decision_id"},
        {"name": "Strategy", "id": "strategy_type"},
        {"name": "Instrument", "id": "primary_instrument"},
        {"name": "Action", "id": "action"},
        {"name": "Risk", "id": "risk_state"},
        {"name": "News", "id": "news_severity"},
        {
            "name": "Cost",
            "id": "cost_round_trip",
            "type": "numeric",
            "format": Format(precision=2, scheme=Scheme.fixed, trim=Trim.yes),
        },
        {
            "name": "Max DD",
            "id": "max_drawdown",
            "type": "numeric",
            "format": Format(precision=4, scheme=Scheme.fixed, trim=Trim.yes),
        },
    ]


def _prepare_decisions(decisions: pd.DataFrame) -> pd.DataFrame:
    if decisions.empty:
        return decisions
    decisions = decisions.copy()
    if "cost_summary.round_trip_cost" in decisions.columns:
        decisions["cost_round_trip"] = decisions["cost_summary.round_trip_cost"]
    if "backtest_metrics.max_drawdown" in decisions.columns:
        decisions["max_drawdown"] = decisions["backtest_metrics.max_drawdown"]
    display_columns = [
        "created_at",
        "decision_id",
        "strategy_type",
        "primary_instrument",
        "action",
        "risk_state",
        "news_severity",
        "cost_round_trip",
        "max_drawdown",
    ]
    for column in display_columns:
        if column not in decisions.columns:
            decisions[column] = None
    decisions["cost_round_trip"] = pd.to_numeric(decisions["cost_round_trip"], errors="coerce")
    decisions["max_drawdown"] = pd.to_numeric(decisions["max_drawdown"], errors="coerce")
    return decisions[display_columns].sort_values("created_at", ascending=False)
