from __future__ import annotations

from datetime import date

import pandas as pd

from moex_carry.domain.portfolio import PairSpec
from moex_carry.portfolio.minute_snapshot_adapter import build_minute_pair_tape


def _replay_frame() -> pd.DataFrame:
    rows = [
        {
            "date": "2026-01-10",
            "exec_ts": "2026-01-10 10:00:00",
            "spot_mid": 100.0,
            "future_mid": 101.0,
            "spread_mid": -1.0,
            "spread_pct": -0.01,
            "floor_rate_annual": 0.12,
            "floor_pass": True,
            "liquidity_pass": True,
            "zscore": -1.2,
            "tp_net": 0.02,
            "sl_net": 0.01,
            "signal_action": "enter",
            "entry_fill_status": "filled",
            "entry_fill_ts": "2026-01-10 10:20:00",
            "entry_wait_minutes": 20.0,
            "exit_fill_status": None,
            "exit_forced": None,
            "unfilled_reason": None,
            "trade_cycle": 1,
            "spot_volume": 1000.0,
            "future_volume": 900.0,
        },
        {
            "date": "2026-01-10",
            "exec_ts": "2026-01-10 18:40:00",
            "spot_mid": 101.0,
            "future_mid": 101.5,
            "spread_mid": -0.5,
            "spread_pct": -0.00495,
            "floor_rate_annual": 0.11,
            "floor_pass": True,
            "liquidity_pass": True,
            "zscore": -0.8,
            "tp_net": 0.02,
            "sl_net": 0.01,
            "signal_action": "hold",
            "entry_fill_status": None,
            "exit_fill_status": None,
            "exit_forced": None,
            "unfilled_reason": None,
            "trade_cycle": 1,
            "spot_volume": 1100.0,
            "future_volume": 950.0,
        },
        {
            "date": "2026-01-11",
            "exec_ts": "2026-01-11 10:00:00",
            "spot_mid": 102.0,
            "future_mid": 101.0,
            "spread_mid": 1.0,
            "spread_pct": 0.0098,
            "floor_rate_annual": 0.10,
            "floor_pass": True,
            "liquidity_pass": True,
            "zscore": 0.9,
            "tp_net": 0.02,
            "sl_net": 0.01,
            "signal_action": "exit",
            "entry_fill_status": None,
            "exit_fill_status": "forced",
            "exit_fill_ts": "2026-01-11 10:40:00",
            "exit_wait_minutes": 40.0,
            "exit_forced": True,
            "trade_return_pct_net": 0.03,
            "trade_pnl_cash": 300.0,
            "unfilled_reason": "exit_timeout_forced",
            "trade_cycle": 1,
            "spot_volume": 1200.0,
            "future_volume": 970.0,
        },
    ]
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame["exec_ts"] = pd.to_datetime(frame["exec_ts"])
    return frame


def test_build_minute_pair_tape_maps_snapshot_and_events():
    pair = PairSpec(stock_secid="AAA", future_secid="AAH6", expiry=date(2026, 3, 19), lot_size=1, multiplier=1)
    tape = build_minute_pair_tape(replay=_replay_frame(), pair=pair)

    assert len(tape.snapshots_by_day) == 2
    snap_day1 = tape.snapshots_by_day[date(2026, 1, 10)]
    assert snap_day1.spot_mid == 101.0
    assert snap_day1.future_mid == 101.5
    assert snap_day1.floor_pass is True
    assert snap_day1.lq.liquidity_pass is True
    assert snap_day1.scores.total_score is not None

    events_day1 = tape.events_by_day[date(2026, 1, 10)]
    assert len(events_day1) == 1
    assert events_day1[0].event_type == "entry_filled"
    assert events_day1[0].entry_wait_minutes == 20.0

    events_day2 = tape.events_by_day[date(2026, 1, 11)]
    assert len(events_day2) == 1
    assert events_day2[0].event_type == "exit_forced"
    assert events_day2[0].trade_pnl_cash == 300.0


def test_build_minute_pair_tape_keeps_fill_events_when_action_is_hold():
    frame = pd.DataFrame(
        [
            {
                "date": "2026-01-10",
                "exec_ts": "2026-01-10 10:00:00",
                "spot_mid": 100.0,
                "future_mid": 101.0,
                "spread_mid": -1.0,
                "spread_pct": -0.01,
                "floor_rate_annual": 0.10,
                "floor_pass": True,
                "liquidity_pass": True,
                "zscore": -1.0,
                "tp_net": 0.02,
                "sl_net": 0.01,
                "signal_action": "enter",
                "entry_fill_status": None,
                "exit_fill_status": None,
                "trade_cycle": 1,
                "spot_volume": 1000.0,
                "future_volume": 1000.0,
            },
            {
                "date": "2026-01-10",
                "exec_ts": "2026-01-10 10:35:00",
                "spot_mid": 100.1,
                "future_mid": 101.1,
                "spread_mid": -1.0,
                "spread_pct": -0.00999,
                "floor_rate_annual": 0.10,
                "floor_pass": True,
                "liquidity_pass": True,
                "zscore": -0.9,
                "tp_net": 0.02,
                "sl_net": 0.01,
                "signal_action": "hold",
                "entry_fill_status": "filled",
                "entry_fill_ts": "2026-01-10 10:35:00",
                "entry_wait_minutes": 35.0,
                "exit_fill_status": None,
                "trade_cycle": 1,
                "spot_volume": 1000.0,
                "future_volume": 1000.0,
            },
            {
                "date": "2026-01-11",
                "exec_ts": "2026-01-11 10:45:00",
                "spot_mid": 101.0,
                "future_mid": 100.0,
                "spread_mid": 1.0,
                "spread_pct": 0.0099,
                "floor_rate_annual": 0.10,
                "floor_pass": True,
                "liquidity_pass": True,
                "zscore": 0.8,
                "tp_net": 0.02,
                "sl_net": 0.01,
                "signal_action": "hold",
                "entry_fill_status": None,
                "exit_fill_status": "filled",
                "exit_fill_ts": "2026-01-11 10:45:00",
                "exit_wait_minutes": 30.0,
                "trade_return_pct_net": 0.01,
                "trade_pnl_cash": 10.0,
                "trade_cycle": 1,
                "exit_flag": True,
                "spot_volume": 1000.0,
                "future_volume": 1000.0,
            },
        ]
    )
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame["exec_ts"] = pd.to_datetime(frame["exec_ts"])

    pair = PairSpec(stock_secid="AAA", future_secid="AAH6", expiry=date(2026, 3, 19), lot_size=1, multiplier=1)
    tape = build_minute_pair_tape(replay=frame, pair=pair)

    day1_events = tape.events_by_day[date(2026, 1, 10)]
    assert len(day1_events) == 1
    assert day1_events[0].event_type == "entry_filled"
    assert day1_events[0].entry_wait_minutes == 35.0

    day2_events = tape.events_by_day[date(2026, 1, 11)]
    assert len(day2_events) == 1
    assert day2_events[0].event_type == "exit_filled"
    assert day2_events[0].trade_pnl_cash == 10.0
