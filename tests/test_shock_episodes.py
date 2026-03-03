from __future__ import annotations

import pandas as pd

from moex_carry.shock_episodes import ShockEpisodeConfig, build_shock_episodes, summarize_mode_shock_capture


def _sample_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "BRN",
                "shock_ts": "2026-01-01T00:00:00Z",
                "z_score": 3.1,
                "shock_direction": "up",
                "abs_move_pct": 1.2,
                "logret": 0.012,
                "matched_current": 1,
                "delay_min_current": 10,
                "matched_proposed": 1,
                "delay_min_proposed": 12,
            },
            {
                "symbol": "BRN",
                "shock_ts": "2026-01-01T01:00:00Z",
                "z_score": 2.2,
                "shock_direction": "up",
                "abs_move_pct": 0.6,
                "logret": 0.006,
                "matched_current": 1,
                "delay_min_current": 15,
                "matched_proposed": 0,
                "delay_min_proposed": None,
            },
            {
                "symbol": "BRN",
                "shock_ts": "2026-01-01T02:00:00Z",
                "z_score": 1.3,
                "shock_direction": "up",
                "abs_move_pct": 0.2,
                "logret": 0.002,
                "matched_current": 0,
                "delay_min_current": None,
                "matched_proposed": 0,
                "delay_min_proposed": None,
            },
            {
                "symbol": "BRN",
                "shock_ts": "2026-01-01T05:00:00Z",
                "z_score": 2.8,
                "shock_direction": "down",
                "abs_move_pct": 1.0,
                "logret": -0.01,
                "matched_current": 0,
                "delay_min_current": None,
                "matched_proposed": 1,
                "delay_min_proposed": 20,
            },
            {
                "symbol": "BRN",
                "shock_ts": "2026-01-01T06:00:00Z",
                "z_score": 2.1,
                "shock_direction": "down",
                "abs_move_pct": 0.5,
                "logret": -0.005,
                "matched_current": 1,
                "delay_min_current": 61,
                "matched_proposed": 1,
                "delay_min_proposed": 30,
            },
        ]
    )


def test_build_shock_episodes_primary_aftershock_roles() -> None:
    rows = _sample_rows()
    config = ShockEpisodeConfig(
        primary_z_threshold=2.5,
        aftershock_z_threshold=2.0,
        episode_window_minutes=360,
        max_gap_minutes=120,
    )
    events_df, episodes_df = build_shock_episodes(rows, config)

    assert len(events_df) == 4
    assert len(episodes_df) == 2
    assert events_df["role"].value_counts().to_dict() == {"primary": 2, "aftershock": 2}


def test_summarize_mode_shock_capture_recall() -> None:
    rows = _sample_rows()
    config = ShockEpisodeConfig(
        primary_z_threshold=2.5,
        aftershock_z_threshold=2.0,
        episode_window_minutes=360,
        max_gap_minutes=120,
    )
    events_df, _ = build_shock_episodes(rows, config)
    capture = summarize_mode_shock_capture(
        detail_df=rows,
        events_df=events_df,
        mode="current",
        min_delay_minutes=0.0,
        max_delay_minutes=60.0,
    )

    primary = capture[(capture["symbol"] == "ALL") & (capture["role"] == "primary")].iloc[0]
    after = capture[(capture["symbol"] == "ALL") & (capture["role"] == "aftershock")].iloc[0]
    assert int(primary["total_events"]) == 2
    assert int(primary["caught_events"]) == 1
    assert round(float(primary["recall"]), 4) == 0.5
    assert int(after["total_events"]) == 2
    assert int(after["caught_events"]) == 1
    assert round(float(after["recall"]), 4) == 0.5
