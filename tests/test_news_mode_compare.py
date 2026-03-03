from __future__ import annotations

import pandas as pd

from moex_carry.news_mode_compare import (
    CompareConfig,
    _mode_rows,
    compare_modes,
    evaluate_news_to_shock_metrics,
    select_current_candidate,
    select_proposed_candidate,
)


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "NG_US",
                "shock_ts": "2026-01-01T10:00:00Z",
                "shock_direction": "up",
                "z_score": 3.2,
                "broad_event_id": "evt-broad-noise",
                "broad_delay_min": 8,
                "broad_title": "Football transfer rumors spark social media debate",
                "v2_event_id": "evt-v2-gas",
                "v2_delay_min": 11,
                "v2_title": "Colder weather forecast lifts natural gas demand outlook",
                "label_has_silver": 1,
                "silver_direction_match": 1,
            },
            {
                "symbol": "BRN",
                "shock_ts": "2026-01-01T11:00:00Z",
                "shock_direction": "down",
                "z_score": 2.9,
                "broad_event_id": "evt-broad-oil",
                "broad_delay_min": 9,
                "broad_title": "EIA crude inventories build weighs on oil prices",
                "v2_event_id": "",
                "v2_delay_min": "",
                "v2_title": "",
                "label_has_silver": 1,
                "silver_direction_match": 0,
            },
            {
                "symbol": "GOLD",
                "shock_ts": "2026-01-01T12:00:00Z",
                "shock_direction": "up",
                "z_score": 2.7,
                "broad_event_id": "evt-broad-gold",
                "broad_delay_min": 75,
                "broad_title": "Gold rises as geopolitical conflict escalates",
                "v2_event_id": "",
                "v2_delay_min": "",
                "v2_title": "",
                "label_has_silver": 1,
                "silver_direction_match": 1,
            },
            {
                "symbol": "NG_US",
                "shock_ts": "2026-01-01T13:00:00Z",
                "shock_direction": "down",
                "z_score": 2.6,
                "broad_event_id": "",
                "broad_delay_min": "",
                "broad_title": "",
                "v2_event_id": "",
                "v2_delay_min": "",
                "v2_title": "",
                "label_has_silver": 0,
                "silver_direction_match": 0,
            },
        ]
    )


def test_current_prefers_broad_first() -> None:
    df = _sample_df()
    row = df.iloc[0]
    current = select_current_candidate(row)
    assert current is not None
    assert current["source"] == "broad"
    assert current["event_id"] == "evt-broad-noise"


def test_proposed_prefers_relevant_candidate_and_filters_late() -> None:
    df = _sample_df()
    config = CompareConfig(max_delay_minutes=60.0, broad_min_relevance=1.0, v2_min_relevance=0.4)

    candidate_row0 = select_proposed_candidate(df.iloc[0], config)
    assert candidate_row0 is not None
    assert candidate_row0["source"] == "v2_clean"
    assert candidate_row0["event_id"] == "evt-v2-gas"

    candidate_row2 = select_proposed_candidate(df.iloc[2], config)
    assert candidate_row2 is None


def test_compare_modes_outputs_expected_deltas() -> None:
    df = _sample_df()
    config = CompareConfig(max_delay_minutes=60.0, broad_min_relevance=1.0, v2_min_relevance=0.4)
    detail, summary, delta = compare_modes(df, config)

    assert len(detail) == len(df)
    all_current = summary[(summary["symbol"] == "ALL") & (summary["mode"] == "current")].iloc[0]
    all_proposed = summary[(summary["symbol"] == "ALL") & (summary["mode"] == "proposed")].iloc[0]
    assert all_current["matched_shocks"] == 3
    assert all_proposed["matched_shocks"] == 2
    assert all_proposed["avg_relevance"] > all_current["avg_relevance"]

    all_delta = delta[delta["symbol"] == "ALL"].iloc[0]
    assert all_delta["delta_avg_relevance"] > 0


def test_news_to_shock_metrics_have_expected_columns() -> None:
    df = _sample_df()
    config = CompareConfig(max_delay_minutes=60.0, broad_min_relevance=1.0, v2_min_relevance=0.4)
    current = _mode_rows(df, "current", config)
    proposed = _mode_rows(df, "proposed", config)
    metrics = evaluate_news_to_shock_metrics([current, proposed], z_thresholds=(2.5,))

    assert not metrics.empty
    cols = {"mode", "symbol", "z_threshold", "precision", "recall", "f1", "tp", "fp", "fn"}
    assert cols.issubset(set(metrics.columns))
    all_rows = metrics[(metrics["symbol"] == "ALL") & (metrics["z_threshold"] == 2.5)]
    assert len(all_rows) == 2
