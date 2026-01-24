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
