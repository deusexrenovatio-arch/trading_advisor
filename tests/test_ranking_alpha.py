import pandas as pd

from moex_carry.selection.ranking import score_pairs_alpha


def test_score_pairs_alpha_orders_by_total_score():
    df = pd.DataFrame(
        {
            "score_floor": [0.1, 0.0],
            "score_alpha": [0.02, 0.5],
            "penalty_liq": [0.0, 0.1],
            "penalty_event": [0.0, 0.0],
        }
    )
    ranked = score_pairs_alpha(df)
    assert ranked.iloc[0]["total_score"] >= ranked.iloc[1]["total_score"]


def test_score_pairs_alpha_uses_primary_metric_when_available():
    df = pd.DataFrame(
        {
            "pair": ["A", "B"],
            "score_floor": [0.5, 0.1],
            "score_alpha": [0.1, 0.0],
            "penalty_liq": [0.0, 0.0],
            "penalty_event": [0.0, 0.0],
            "avg_trade_return_annual_operational_recent": [0.12, 0.25],
        }
    )

    ranked = score_pairs_alpha(df)
    assert ranked.iloc[0]["pair"] == "B"


def test_score_pairs_alpha_falls_back_to_total_score_when_metric_not_present():
    df = pd.DataFrame(
        {
            "pair": ["A", "B"],
            "score_floor": [0.5, 0.1],
            "score_alpha": [0.1, 0.0],
            "penalty_liq": [0.0, 0.0],
            "penalty_event": [0.0, 0.0],
        }
    )

    ranked = score_pairs_alpha(df, primary_metric="avg_trade_return_annual_operational_recent")
    assert ranked.iloc[0]["pair"] == "A"
